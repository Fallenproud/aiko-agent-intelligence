"""Durable single-operator demo runtime. No LLM or external tools."""
import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone


def stamp():
    return datetime.now(timezone.utc).isoformat()


class Conflict(Exception):
    pass


class Store:
    def __init__(self, path):
        self.path = str(path)
        with self.tx() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, version INTEGER NOT NULL,
              status TEXT NOT NULL, approval TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT,
              run_id TEXT NOT NULL, type TEXT NOT NULL, title TEXT NOT NULL,
              detail TEXT NOT NULL, time TEXT NOT NULL, correlation_id TEXT);
            CREATE TABLE IF NOT EXISTS receipts(run_id TEXT NOT NULL, key TEXT NOT NULL,
              body TEXT NOT NULL, result TEXT NOT NULL, PRIMARY KEY(run_id,key));
            CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS run_owners(run_id TEXT PRIMARY KEY,owner TEXT NOT NULL);
            """)

    @contextmanager
    def tx(self):
        db = sqlite3.connect(self.path, timeout=15, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def event(self, db, rid, typ, title, detail, correlation=None):
        db.execute("INSERT INTO events(run_id,type,title,detail,time,correlation_id) VALUES(?,?,?,?,?,?)",
                   (rid, typ, title, detail, stamp(), correlation))

    def snapshot(self, db, rid, owner):
        if not db.execute("SELECT 1 FROM run_owners WHERE run_id=? AND owner=?", (rid,owner)).fetchone():
            raise KeyError(rid)
        row = db.execute("SELECT * FROM runs WHERE id=?", (rid,)).fetchone()
        if row is None:
            raise KeyError(rid)
        return {**dict(row), "events": [dict(e) for e in db.execute(
            "SELECT * FROM events WHERE run_id=? ORDER BY seq", (rid,))],
            "runtime": "simulated", "authority": "authenticated-owner"}

    def get(self, rid, owner):
        with self.tx() as db:
            return self.snapshot(db, rid, owner)

    def current(self, owner):
        with self.tx() as db:
            row = db.execute("SELECT value FROM meta WHERE key=?", ("current:"+owner,)).fetchone()
            return self.snapshot(db, row[0], owner) if row else None

    def create(self, owner):
        rid = "RUN-" + uuid.uuid4().hex[:12]
        with self.tx() as db:
            db.execute("INSERT INTO run_owners VALUES(?,?)",(rid,owner))
            db.execute("INSERT INTO runs VALUES(?,1,'waiting','pending')", (rid,))
            for typ, title, detail in [
                ("run.created", "Kjøring opprettet", "Ny lokal demokjøring."),
                ("scope.validated", "Omfang kontrollert", "Tre demofiler. Ingen eksterne systemer."),
                ("approval.required", "Venter på operatør", "evidence.validate på demo/evidence/*; simulert verktøy.")]:
                self.event(db, rid, typ, title, detail)
            db.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", ("current:"+owner,rid))
            return self.snapshot(db, rid, owner)

    def decide(self, rid, action, owner):
        body = json.dumps(action, sort_keys=True)
        with self.tx() as db:
            run = self.snapshot(db, rid, owner)
            receipt = db.execute("SELECT body,result FROM receipts WHERE run_id=? AND key=?",
                                 (rid, action["idempotency_key"])).fetchone()
            if receipt:
                if receipt["body"] != body:
                    raise Conflict("Idempotency-nøkkelen gjelder en annen forespørsel.")
                return json.loads(receipt["result"])
            if action["expected_version"] != run["version"]:
                raise Conflict("Grunnlaget har endret seg. Hent oppdatert kjøring.")
            if run["approval"] != "pending" or run["status"] != "waiting":
                raise Conflict("Godkjenningen er allerede behandlet.")
            if action["type"] not in ("approve", "reject"):
                raise ValueError("Ukjent handling.")
            approved = action["type"] == "approve"
            status, approval = ("running", "approved") if approved else ("rejected", "rejected")
            db.execute("UPDATE runs SET status=?,approval=?,version=version+1 WHERE id=?",
                       (status, approval, rid))
            self.event(db, rid, "approval." + approval,
                       "Godkjent av lokal operatør" if approved else "Avvist av lokal operatør",
                       "Beslutning lagret i SQLite. Verktøyet er fortsatt simulert.",
                       action["correlation_id"])
            result = self.snapshot(db, rid, owner)
            db.execute("INSERT INTO receipts VALUES(?,?,?,?)",
                       (rid, action["idempotency_key"], body, json.dumps(result)))
            return result

    def tick(self):
        """Atomic simulated execution; durable running jobs survive process restart."""
        with self.tx() as db:
            ids = [r[0] for r in db.execute("SELECT id FROM runs WHERE status='running'")]
            for rid in ids:
                self.event(db, rid, "tool.completed", "Evidenssjekk fullført",
                           "Simulert resultat: 3/3 demofiler. Ingen faktiske filer ble kontrollert.")
                self.event(db, rid, "run.completed", "Kjøring fullført",
                           "Demoverktøyet er ferdig. Dette er ikke reell agentutførelse.")
                db.execute("UPDATE runs SET status='completed',version=version+1 WHERE id=?", (rid,))
            return len(ids)
