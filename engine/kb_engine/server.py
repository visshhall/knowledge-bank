"""
server.py — the private local web server the desktop window talks to.

WHAT:  A small FastAPI server on 127.0.0.1:8765 (this computer only).
       Phase 0 endpoints:
         GET /health  — "are you alive?" + engine version (used at startup)
         GET /system  — full readiness report (GPU, RAM, disk, Ollama, models)
         GET /stats   — what the knowledge bank holds (for the dashboard)
       Later phases add import, search, topics, learn mode, etc.

WHY:   Separating the window (Electron) from the engine (Python) means
       hours-long processing never freezes the interface, and each side uses
       the language best suited to it.

WHEN:  Started automatically by app/electron/main.js when the app opens:
           python -m kb_engine.server
       and stopped when the app closes. Can also be run by hand for testing.

SECURITY:
       - Listens on 127.0.0.1 only → unreachable from the network.
       - Every request must carry the header  X-KB-Token: <secret>.
         main.js creates a fresh random secret each launch and passes it to
         this process (env var KB_ENGINE_TOKEN). This stops other programs or
         malicious web pages in a browser from quietly querying the engine on
         localhost. If no token is set (manual testing), the check is skipped
         and a warning is printed.

CONNECTED TO: config.py, db.py, system_check.py; called by
       app/electron/main.js (which relays requests from the window).
"""

import hmac
import os
import sys
from contextlib import asynccontextmanager

import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException

from . import __version__, config, db, system_check

# Secret shared with the Electron app for this launch only.
_TOKEN = os.environ.get("KB_ENGINE_TOKEN", "")

def require_token(x_kb_token: str = Header(default="")) -> None:
    """
    Reject any request without the correct secret header.

    HOW:   hmac.compare_digest compares in constant time, so the secret can't
           be guessed by measuring how fast wrong guesses are rejected.
    WHEN:  Runs before every endpoint below (FastAPI "dependency").
    """
    if _TOKEN and not hmac.compare_digest(x_kb_token, _TOKEN):
        raise HTTPException(status_code=401, detail="Invalid engine token")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """
    Runs once when the server starts (before `yield`) and once when it stops.

    WHY:   First launch creates the database; later launches upgrade it if
           the app was updated with a newer schema. Doing it here guarantees
           every endpoint can assume the database is ready.
    """
    version = db.init_db()
    print(f"[engine] database ready at {config.DB_PATH} (schema v{version})", flush=True)
    yield
    print("[engine] shutting down", flush=True)


app = FastAPI(title="Knowledge Bank Engine", version=__version__, lifespan=lifespan,
              docs_url=None, redoc_url=None)  # no public API docs page needed


@app.get("/health", dependencies=[Depends(require_token)])
def health() -> dict:
    """Alive-check. main.js polls this until it answers, then shows the window content."""
    return {"ok": True, "engine_version": __version__}


@app.get("/system", dependencies=[Depends(require_token)])
def system() -> dict:
    """Readiness report shown on the status screen (see system_check.run_checks)."""
    return system_check.run_checks()


@app.get("/stats", dependencies=[Depends(require_token)])
def stats() -> dict:
    """Knowledge bank totals and coverage % (see db.stats)."""
    return db.stats()


def main() -> None:
    """
    Start the server.

    log_level="warning" keeps the console quiet; errors still appear.
    The '[engine] ready' line is printed by _startup and is what main.js
    could watch for, though it relies on polling /health to be robust.
    """
    if not _TOKEN:
        print("[engine] WARNING: KB_ENGINE_TOKEN not set — running without "
              "request authentication (OK for manual testing only).",
              file=sys.stderr, flush=True)
    uvicorn.run(app, host=config.ENGINE_HOST, port=config.ENGINE_PORT, log_level="warning")


if __name__ == "__main__":
    main()
