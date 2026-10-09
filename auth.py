"""Local account provisioning and opaque, revocable cookie sessions."""
import hashlib
import hmac
import secrets
import sqlite3
import time

from fastapi import HTTPException


class Auth:
    def __init__(self, store):
        self.store = store
        with store.tx() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY,username TEXT UNIQUE NOT NULL,
              salt TEXT NOT NULL,digest TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY,owner TEXT NOT NULL,
              csrf TEXT NOT NULL,expires REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS login_attempts(bucket TEXT NOT NULL,time REAL NOT NULL);
            """)

    @staticmethod
    def digest(password, salt):
        return hashlib.scrypt(password.encode(),salt=bytes.fromhex(salt),
                              n=16384,r=8,p=1).hex()

    def provision(self, username, password):
        username = username.strip().lower()
        if not 3 <= len(username) <= 64 or not 12 <= len(password) <= 256:
            raise ValueError("Username: 3–64 characters. Password: 12–256 characters.")
        salt = secrets.token_hex(16)
        digest = self.digest(password, salt)
        owner = secrets.token_hex(16)
        with self.store.tx() as db:
            db.execute("INSERT INTO users VALUES(?,?,?,?)",(owner,username,salt,digest))
        return owner

    def login(self, username, password, ip):
        username = username.strip().lower()
        now = time.time()
        # Per IP, including nonexistent names; limits username rotation.
        with self.store.tx() as db:
            db.execute("DELETE FROM login_attempts WHERE time<?",(now-60,))
            if db.execute("SELECT count(*) FROM login_attempts WHERE bucket=?",(ip,)).fetchone()[0]>=5:
                raise HTTPException(429,"For mange forsøk. Vent ett minutt.")
            db.execute("INSERT INTO login_attempts VALUES(?,?)",(ip,now))
            user = db.execute("SELECT * FROM users WHERE username=?",(username,)).fetchone()
        salt = user["salt"] if user else "00"*16
        candidate = self.digest(password,salt)
        expected = user["digest"] if user else "00"*64
        if not hmac.compare_digest(candidate,expected) or user is None:
            raise HTTPException(401,"Feil brukernavn eller passord.")
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        with self.store.tx() as db:
            db.execute("DELETE FROM sessions WHERE expires<?",(now,))
            db.execute("INSERT INTO sessions VALUES(?,?,?,?)",
                       (hashlib.sha256(token.encode()).hexdigest(),user["id"],csrf,now+28800))
        return token, {"owner":user["id"],"username":user["username"],"csrf":csrf}

    def session(self, token):
        if not token:
            raise HTTPException(401,"Innlogging kreves.")
        hashed = hashlib.sha256(token.encode()).hexdigest()
        with self.store.tx() as db:
            row = db.execute("SELECT sessions.*,users.username FROM sessions JOIN users ON users.id=owner WHERE token_hash=? AND expires>?",
                             (hashed,time.time())).fetchone()
        if row is None:
            raise HTTPException(401,"Sesjonen er utløpt eller avsluttet.")
        return dict(row)

    def logout(self, token):
        with self.store.tx() as db:
            db.execute("DELETE FROM sessions WHERE token_hash=?",
                       (hashlib.sha256(token.encode()).hexdigest(),))
