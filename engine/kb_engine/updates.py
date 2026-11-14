"""
updates.py — checks whether the AI engine (Ollama) and the AI models have
newer versions, and updates them on request.

WHAT:  check() — ONE online check, only when the owner presses "Check for
       updates" (never automatically, never in the background):
         - Ollama: installed version (asked from the local Ollama) vs the
           latest release published on GitHub (ollama/ollama).
         - Each model: the fingerprint (digest) of the copy on this laptop
           vs the fingerprint currently published in Ollama's model library
           (registry.ollama.ai). Different fingerprint = the publisher
           updated that model → "Update available".
       update_model(name) — re-downloads one model (Ollama only fetches the
           parts that changed) with the same progress bars as Setup.
       update_ollama() — downloads and opens the latest official Ollama
           installer (the same flow as first-time setup). Note: the Ollama
           app on Windows also updates itself from its tray icon.

WHY:   Models and Ollama improve over time (better answers, speed, bug and
       security fixes). The owner asked how he would know if what he has is
       old or new. Comparing fingerprints is exact: it doesn't guess from
       dates, it detects any change the publisher made.

PRIVACY: The check sends only public names (model names, "ollama") to
       registry.ollama.ai and api.github.com. No document content, file
       names or anything from the bank ever leaves the laptop.

WHEN:  Setup screen → "AI updates" card (server.py → /updates/*).

CONNECTED TO: ollama_client.py (local versions/digests), setup_manager.py
       (re-uses its download jobs and progress), config.py, server.py,
       app/src/Updates.jsx.
"""

import hashlib
import threading
import time

import httpx

from . import config, setup_manager

REGISTRY = "https://registry.ollama.ai/v2"
GITHUB_LATEST = "https://api.github.com/repos/ollama/ollama/releases/latest"
MANIFEST_TYPE = "application/vnd.docker.distribution.manifest.v2+json"

_lock = threading.Lock()
_last: dict = {"checked_at": None, "ollama": None, "models": [], "error": None}


def _local_models() -> dict[str, dict]:
    """{name: {"digest", "modified_at", "size"}} for every model on this laptop."""
    r = httpx.get(f"{config.OLLAMA_URL}/api/tags", timeout=10)
    r.raise_for_status()
    return {m["name"]: m for m in r.json().get("models", [])}


def _registry_path(name: str) -> tuple[str, str]:
    """
    'qwen3.5:4b' → ('library/qwen3.5', '4b'); 'nomic-embed-text' →
    ('library/nomic-embed-text', 'latest'); 'user/model:tag' → ('user/model', 'tag').
    """
    base, _, tag = name.partition(":")
    repo = base if "/" in base else f"library/{base}"
    return repo, tag or "latest"


def _remote_digest(name: str) -> str | None:
    """
    The fingerprint of the model as currently published. Ollama's local
    'digest' is the SHA-256 of this same manifest, so the two compare
    directly. Returns None if the registry can't be reached.
    """
    repo, tag = _registry_path(name)
    r = httpx.get(f"{REGISTRY}/{repo}/manifests/{tag}", headers={"Accept": MANIFEST_TYPE},
                  timeout=20, follow_redirects=True)
    if r.status_code != 200:
        return None
    return hashlib.sha256(r.content).hexdigest()


def _latest_ollama() -> str | None:
    """Latest Ollama release version from GitHub, e.g. '0.13.2' (None if unreachable)."""
    r = httpx.get(GITHUB_LATEST, headers={"Accept": "application/vnd.github+json"},
                  timeout=20, follow_redirects=True)
    if r.status_code != 200:
        return None
    return str(r.json().get("tag_name", "")).lstrip("v") or None


def _version_tuple(v: str) -> tuple:
    return tuple(int(x) if x.isdigit() else 0 for x in v.split("-")[0].split("."))


def check() -> dict:
    """
    Run the online check (takes a few seconds) and remember the result.
    RETURNS the same structure as last_result().
    """
    from . import ollama_client  # local import keeps module load light

    result: dict = {"checked_at": time.strftime("%Y-%m-%d %H:%M"), "ollama": None,
                    "models": [], "error": None}
    try:
        installed = ollama_client.version()
        latest = _latest_ollama()
        state = "unknown"
        if installed and latest:
            state = "update_available" if _version_tuple(latest) > _version_tuple(installed) else "up_to_date"
        result["ollama"] = {"installed": installed, "latest": latest, "state": state}

        local = _local_models() if installed else {}
        for name in setup_manager.WIZARD_MODELS:
            key = name if name in local else (f"{name}:latest" if f"{name}:latest" in local else None)
            if not key:
                result["models"].append({"name": name, "state": "not_installed"})
                continue
            remote = _remote_digest(name)
            mine = local[key].get("digest", "")
            if remote is None or not mine:
                state = "unknown"          # couldn't compare — never claim an update we can't prove
            else:
                state = "up_to_date" if remote == mine else "update_available"
            result["models"].append({
                "name": name, "state": state,
                "local_digest": mine[:12], "remote_digest": (remote or "")[:12],
                "downloaded": (local[key].get("modified_at") or "")[:10],
            })
    except httpx.HTTPError as exc:
        result["error"] = f"Couldn't reach the update servers ({exc.__class__.__name__}). Check the internet connection."
    with _lock:
        _last.clear()
        _last.update(result)
    return result


def last_result() -> dict:
    """The most recent check (empty until the owner presses Check)."""
    with _lock:
        snap = dict(_last)
    snap["downloads"] = setup_manager.status()["models"]["job"]
    return snap


def update_model(name: str) -> dict:
    """Re-download one model; Ollama fetches only the changed parts."""
    if name not in setup_manager.WIZARD_MODELS:
        return {"ok": False, "message": "Unknown model."}
    return setup_manager.start_model_downloads(names=[name], force=True)


def update_ollama() -> dict:
    """Download and open the latest official Ollama installer."""
    return setup_manager.start_ollama_install(force=True)
