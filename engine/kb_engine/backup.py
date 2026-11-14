"""
backup.py — Phase 7 encrypted backup and restore of the whole knowledge bank.

WHAT:  create(path, password) — a consistent snapshot of the bank database
         (SQLite's online backup, safe while the app is in use), compressed
         and encrypted into one ".kbbackup" file.
       restore(path, password) — decrypts and checks a backup, then stages it;
         the swap happens on the next start of the engine (the app offers
         "Restart now"), and the bank it replaces is kept as
         "before-restore-<date>.sqlite3" in the data folder, just in case.
       status() — progress of the running job; info() — last backup time.
HOW (security):
       - Key: scrypt(password, random 16-byte salt, N=2^15, r=8, p=1) → 256
         bits. scrypt makes guessing passwords slow and memory-hungry.
       - Cipher: AES-256-GCM (authenticated): a wrong password or any change
         to the file is detected and nothing is restored.
       - Streamed in 1 MB chunks, so multi-GB banks don't need multi-GB RAM.
       - File layout: "KBBACKUP1" | salt(16) | nonce(12) | ciphertext | tag(16).
         The plaintext is zlib-compressed SQLite. The password is never
         stored anywhere; if it's lost, the backup can't be opened.
WHAT IS INCLUDED: everything in the bank — passages, topics, articles,
       lessons, flashcard progress, answers, settings. NOT included: your
       original PDFs/images (they stay where they are) and the AI models
       (re-downloaded from Setup).
WHY:   Months of overnight writing and study progress shouldn't depend on one
       laptop; an encrypted file can safely go to a USB drive or cloud folder.
WHEN:  POST /backup/create, POST /backup/restore, GET /backup/status
       (server.py), from Setup → "Backup & restore" (Backup.jsx).
       apply_pending_restore() runs at engine start (server.py lifespan,
       before the database is opened).
CONNECTED TO: config.DATA_DIR / config.DB_PATH, db.py, server.py, Backup.jsx.
"""

from __future__ import annotations

import os
import sqlite3
import threading
import time
import zlib
from pathlib import Path

from . import config, db

MAGIC = b"KBBACKUP1"
CHUNK = 1 << 20
PENDING_NAME = "restore-pending.sqlite3"

_lock = threading.Lock()
_state: dict = {"state": "idle"}


def _set(**kw) -> None:
    with _lock:
        _state.update(kw)


def status() -> dict:
    with _lock:
        out = dict(_state)
    out["last_backup"] = db.get_setting("last_backup")
    out["restore_pending"] = (config.DATA_DIR / PENDING_NAME).exists()
    return out


def _key(password: str, salt: bytes) -> bytes:
    from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

    return Scrypt(salt=salt, length=32, n=2 ** 15, r=8, p=1).derive(password.encode("utf-8"))


def _start(target, *args) -> dict:
    with _lock:
        if _state.get("state") == "running":
            return {"ok": False, "message": "A backup or restore is already running."}
        _state.clear()
        _state.update(state="running", stage="Starting…", started_at=time.time())
    threading.Thread(target=target, args=args, name="kb-backup", daemon=True).start()
    return {"ok": True}


def create(path: str, password: str) -> dict:
    if len(password or "") < 8:
        return {"ok": False, "message": "Use a password of at least 8 characters."}
    if not str(path).lower().endswith(".kbbackup"):
        return {"ok": False, "message": "Backup files must end in .kbbackup."}
    return _start(_create, Path(path), password)


def _create(path: Path, password: str) -> None:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    snap = config.DATA_DIR / "backup-snapshot.tmp"
    try:
        _set(stage="Taking a consistent snapshot of the bank…")
        src = sqlite3.connect(config.DB_PATH)
        dst = sqlite3.connect(snap)
        with dst:
            src.backup(dst, pages=4096)
        src.close()
        dst.close()

        _set(stage="Compressing and encrypting…")
        salt, nonce = os.urandom(16), os.urandom(12)
        enc = Cipher(algorithms.AES(_key(password, salt)), modes.GCM(nonce)).encryptor()
        comp = zlib.compressobj(6)
        tmp = path.with_suffix(".kbbackup.part")
        total, done = snap.stat().st_size, 0
        with open(snap, "rb") as fin, open(tmp, "wb") as fout:
            fout.write(MAGIC + salt + nonce)
            while chunk := fin.read(CHUNK):
                fout.write(enc.update(comp.compress(chunk)))
                done += len(chunk)
                _set(stage=f"Compressing and encrypting… {round(100 * done / max(1, total))}%")
            fout.write(enc.update(comp.flush()))
            enc.finalize()
            fout.write(enc.tag)
        os.replace(tmp, path)
        db.set_setting("last_backup", {"at": time.strftime("%Y-%m-%d %H:%M"), "file": str(path),
                                       "bytes": path.stat().st_size})
        _set(state="done", stage=None, message=f"Backup saved: {path.name}", path=str(path))
    except Exception as exc:
        _set(state="error", stage=None, message=f"Backup failed: {exc}")
    finally:
        snap.unlink(missing_ok=True)


def restore(path: str, password: str) -> dict:
    p = Path(path)
    if not p.exists() or p.suffix.lower() != ".kbbackup":
        return {"ok": False, "message": "Choose a .kbbackup file."}
    return _start(_restore, p, password)


def _restore(path: Path, password: str) -> None:
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    out = config.DATA_DIR / "restore-check.tmp"
    try:
        _set(stage="Decrypting…")
        size = path.stat().st_size
        with open(path, "rb") as fin:
            if fin.read(len(MAGIC)) != MAGIC:
                raise ValueError("This isn't a Knowledge Bank backup file.")
            salt, nonce = fin.read(16), fin.read(12)
            body_len = size - len(MAGIC) - 28 - 16
            if body_len <= 0:
                raise ValueError("The backup file is damaged (too short).")
            fin.seek(size - 16)
            tag = fin.read(16)
            fin.seek(len(MAGIC) + 28)
            dec = Cipher(algorithms.AES(_key(password, salt)), modes.GCM(nonce, tag)).decryptor()
            dcomp = zlib.decompressobj()
            left = body_len
            with open(out, "wb") as fout:
                while left > 0:
                    chunk = fin.read(min(CHUNK, left))
                    left -= len(chunk)
                    try:
                        fout.write(dcomp.decompress(dec.update(chunk)))
                    except zlib.error:
                        # Garbage after decryption = wrong key or altered file.
                        raise ValueError("Wrong password, or the backup file was changed or damaged.") from None
                try:
                    dec.finalize()  # verifies the password and that nothing was altered
                except InvalidTag:
                    raise ValueError("Wrong password, or the backup file was changed or damaged.") from None
                fout.write(dcomp.flush())

        _set(stage="Checking the restored bank…")
        con = sqlite3.connect(out)
        ok = con.execute("PRAGMA quick_check").fetchone()[0]
        has_meta = con.execute("SELECT 1 FROM sqlite_master WHERE name = 'schema_meta'").fetchone()
        con.close()
        if ok != "ok" or not has_meta:
            raise ValueError("The backup decrypted but doesn't contain a valid knowledge bank.")
        os.replace(out, config.DATA_DIR / PENDING_NAME)
        _set(state="done", stage=None, restart=True,
             message="Backup checked and ready. Restart the app to switch to it.")
    except Exception as exc:
        _set(state="error", stage=None, message=str(exc))
    finally:
        out.unlink(missing_ok=True)


def apply_pending_restore() -> bool:
    """
    At engine start, before the database opens: if a checked restore is
    waiting, keep the current bank aside and put the restored one in place.
    RETURNS True if a restore was applied.
    """
    pending = config.DATA_DIR / PENDING_NAME
    if not pending.exists():
        return False
    current = Path(config.DB_PATH)
    # On "Restart now" the previous engine may still be letting go of the
    # file for a moment (Windows locks open files): retry for up to ~10 s.
    for attempt in range(20):
        try:
            aside = config.DATA_DIR / f"before-restore-{time.strftime('%Y%m%d-%H%M%S')}.sqlite3"
            if current.exists():
                os.replace(current, aside)
            for side in ("-wal", "-shm"):  # the journal files belong with the set-aside copy
                if Path(str(current) + side).exists():
                    os.replace(str(current) + side, str(aside) + side)
            os.replace(pending, current)
            return True
        except PermissionError:
            time.sleep(0.5)
    return False  # still locked: the restore stays pending for the next start
