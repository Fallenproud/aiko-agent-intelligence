"""Start one worker with a canonical hosted origin and mounted database."""
import os
from pathlib import Path
import uvicorn

if __name__ == "__main__":
    # Render supplies this origin. Never infer it from browser headers.
    origin=os.environ.get("AIKO_PUBLIC_BASE_URL") or os.environ.get("RENDER_EXTERNAL_URL")
    if not origin:
        raise SystemExit("Configure AIKO_PUBLIC_BASE_URL or a verified provider origin.")
    os.environ["AIKO_PUBLIC_BASE_URL"]=origin.rstrip("/")
    db=os.environ.get("AIKO_DB")
    if not db or not Path(db).is_absolute():
        raise SystemExit("Configure AIKO_DB as an absolute persistent-volume path.")
    if not Path(db).parent.is_dir():
        raise SystemExit("Database parent directory is missing. Verify the persistent mount.")
    uvicorn.run("app:create_app",factory=True,host="0.0.0.0",
                port=int(os.environ.get("PORT","10000")),workers=1,proxy_headers=False)
