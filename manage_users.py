import argparse
import getpass
import os
from pathlib import Path
from auth import Auth
from store import Store

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Provision a local AIKO account.")
    parser.add_argument("username")
    args = parser.parse_args()
    password = getpass.getpass("Password (minimum 12 characters): ")
    if password != getpass.getpass("Repeat password: "):
        raise SystemExit("Passwords do not match.")
    auth = Auth(Store(os.environ.get("AIKO_DB",str(Path(__file__).parent/"aiko-v03.sqlite3"))))
    auth.provision(args.username,password)
    print("Account created.")
