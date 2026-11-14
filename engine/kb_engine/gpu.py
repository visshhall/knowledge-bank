"""
gpu.py — keeps the AI work on the graphics card (v0.8.2).

WHAT:  1. apply_ollama_settings(): turns on two Ollama memory savers
          (flash attention + 8-bit attention cache) so the writing model fits
          the 4 GB card completely, and restarts Ollama once to apply them.
       2. tune(model): measures writing speed with Ollama's own layer split
          and with ALL layers forced onto the graphics card, and keeps the
          faster one (saved per model; ollama_client.generate uses it).
       3. report(): what the Setup screen shows — the card, how much of each
          loaded model sits on it, measured speeds, and plain advice.

WHY:   Owner: "make sure all this training part is done on GPU and not CPU,
       it's very slow". His benchmark showed 11.6 tokens/s writing and 1.2
       passages/s embedding — processor-like numbers. An RTX 3050 runs a 4B
       model at roughly 30–50 tokens/s when the WHOLE model is on the card.
       Ollama decides the split itself; on a 4 GB card (minus what Windows
       uses for the screen) it often leaves part of the model on the
       processor, and every token then waits for the processor.
         - Flash attention + q8_0 cache shrink the attention memory by about
           half, which is often exactly what is missing for a full fit.
         - Forcing all layers ("num_gpu": 999) can make it fit when Ollama's
           estimate is too cautious — but on Windows the NVIDIA driver may
           then spill into shared system memory, which is SLOWER. So it is
           only kept when the measurement proves it faster.

WHEN:  apply_ollama_settings(): once at engine start (Windows only; the
       setting "ollama_env_applied" prevents repeats). tune(): automatically
       before the first writing job (writer.py) and from Setup → "Test and
       tune speed". report(): GET /gpu/status.

CONNECTED TO: ollama_client.py (num_gpu choice, speeds), setup_manager.py
       (starts Ollama with these settings), system_check.py (nvidia-smi),
       writer.py, server.py (/gpu/*), App.jsx GpuCard.

Note: topic grouping (k-means) and the fact checks are plain arithmetic
       that take seconds on the processor; only the AI models need the card.
       Picture reading (OCR) uses the card through DirectML (ocr.py).
"""

import os
import subprocess
import sys
import threading
import time

from . import config, db, ollama_client, system_check

# Ollama settings that cut the attention memory roughly in half.
OLLAMA_ENV = {"OLLAMA_FLASH_ATTENTION": "1", "OLLAMA_KV_CACHE_TYPE": "q8_0"}

TUNE_PROMPT = ("Explain in about 120 words how a security team should respond when many failed "
               "sign-ins are followed by one successful sign-in from a new country.")
TUNE_TOKENS = 120
FORCE_LAYERS = 999      # "all layers on the graphics card"
FASTER_BY = 1.15        # forcing must be at least 15% faster to be kept

_state = {"state": "idle", "message": None, "results": None}
_lock = threading.Lock()


def _set(**kw) -> None:
    with _lock:
        _state.update(kw)


# ---------------------------------------------------------------------------
# 1. Ollama memory settings
# ---------------------------------------------------------------------------

def _no_window() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0


def apply_ollama_settings() -> bool:
    """
    Windows: save OLLAMA_ENV as the owner's user environment variables
    (read by Ollama's own tray app at every start), and restart Ollama once
    so the running copy uses them. RETURNS True if anything changed.
    Never restarts while an AI job is running.
    """
    if sys.platform != "win32" or db.get_setting("ollama_env_applied"):
        return False
    changed = False
    for key, value in OLLAMA_ENV.items():
        if os.environ.get(key) != value:
            subprocess.run(["setx", key, value], capture_output=True, creationflags=_no_window())
            os.environ[key] = value  # so an Ollama started by us inherits it now
            changed = True
    if changed and ollama_client.is_running() and not ollama_client.running_models():
        restart_ollama()
    db.set_setting("ollama_env_applied", True)
    return changed


def restart_ollama() -> None:
    """Stop every Ollama process and start `ollama serve` with OLLAMA_ENV."""
    from . import setup_manager  # late import: setup_manager imports many modules
    if sys.platform == "win32":
        for image in ("ollama app.exe", "ollama.exe"):
            subprocess.run(["taskkill", "/F", "/IM", image], capture_output=True,
                           creationflags=_no_window())
        for _ in range(20):
            if not ollama_client.is_running():
                break
            time.sleep(0.5)
    setup_manager.start_ollama()


# ---------------------------------------------------------------------------
# 2. Speed tuning
# ---------------------------------------------------------------------------

def _measure(model: str, num_gpu: int | None) -> dict:
    """One clean measurement: unload, generate TUNE_TOKENS, read the split."""
    ollama_client.clear_gpu_except(None)
    try:
        r = ollama_client.generate(model, TUNE_PROMPT, temperature=0.2, num_ctx=4096,
                                   num_predict=TUNE_TOKENS, num_gpu=num_gpu, fallback=False)
        share = ollama_client.gpu_share(model)
        return {"ok": True, "tokens_per_s": round(r.tokens_per_second, 1), "gpu_share": share}
    except ollama_client.OllamaError as exc:
        return {"ok": False, "error": str(exc)[:200]}


def tune(model: str | None = None) -> dict:
    """
    Compare Ollama's own split with all layers on the card; keep the faster.
    RETURNS {"model", "auto": {...}, "forced": {...}, "chosen": "auto"|"forced"}.
    Takes about a minute (two model loads + two short answers).
    """
    model = model or config.FAST_MODEL
    if not ollama_client.is_running():
        _set(state="idle", message="The AI engine isn't running — start it in Setup first.")
        return {"ok": False}
    _set(state="running", message=f"Measuring {model} with Ollama's own split…")
    auto = _measure(model, None)
    _set(message=f"Measuring {model} with every layer on the graphics card…")
    forced = _measure(model, FORCE_LAYERS)
    choose_forced = (forced.get("ok") and auto.get("ok")
                     and forced["tokens_per_s"] >= auto["tokens_per_s"] * FASTER_BY)
    layers = dict(db.get_setting("ollama_num_gpu", {}) or {})
    if choose_forced:
        layers[model] = FORCE_LAYERS
    else:
        layers.pop(model, None)
    db.set_setting("ollama_num_gpu", layers)
    ollama_client.set_layer_choices(layers)
    result = {"ok": True, "model": model, "auto": auto, "forced": forced,
              "chosen": "forced" if choose_forced else "auto", "at": time.strftime("%Y-%m-%d %H:%M")}
    tuned = dict(db.get_setting("gpu_tuned", {}) or {})
    tuned[model] = result
    db.set_setting("gpu_tuned", tuned)
    best = forced if choose_forced else auto
    _set(state="done", results=result,
         message=(f"{model}: {best.get('tokens_per_s', '?')} tokens/s"
                  + (" with every layer on the graphics card." if choose_forced else " with Ollama's own split.")))
    return result


def tune_once(model: str) -> None:
    """Tune a model the first time it is used for writing (writer.py)."""
    if model not in (db.get_setting("gpu_tuned", {}) or {}):
        try:
            tune(model)
        except Exception:
            pass  # tuning is an optimisation; writing goes ahead regardless


def start_tune(model: str | None = None) -> dict:
    with _lock:
        if _state["state"] == "running":
            return {"ok": False, "message": "Already measuring."}
        _state.update(state="running", message="Starting…")
    threading.Thread(target=tune, args=(model,), name="kb-gpu-tune", daemon=True).start()
    return {"ok": True, "message": "Measuring speed — about a minute."}


# ---------------------------------------------------------------------------
# 3. Report for the Setup screen
# ---------------------------------------------------------------------------

def report() -> dict:
    """The card, each loaded model's share on it, measured speeds, advice."""
    gpu = system_check.gpu_info()
    loaded = ollama_client.loaded_split() if ollama_client.is_running() else []
    advice = []
    if not gpu.get("available"):
        advice.append("No NVIDIA graphics card was found by its driver, so the AI runs on the processor. "
                      "Install or update the NVIDIA driver, then restart the laptop.")
    for m in loaded:
        if m["gpu_share"] is not None and m["gpu_share"] < 0.99:
            advice.append(f"{m['name']} is only {round(m['gpu_share'] * 100)}% on the graphics card. "
                          "Close games, video players and browser tabs playing video, then press "
                          "\"Test and tune speed\".")
    with _lock:
        tuning = dict(_state)
    return {
        "gpu": gpu,
        "loaded": loaded,
        "speeds": ollama_client.speeds(),
        "tuned": db.get_setting("gpu_tuned", {}) or {},
        "memory_savers": all(os.environ.get(k) == v for k, v in OLLAMA_ENV.items())
                          or bool(db.get_setting("ollama_env_applied")),
        "tuning": tuning,
        "advice": advice,
    }
