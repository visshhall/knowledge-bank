"""
modelpick.py — v0.11 model picker: choose the AI model Chat uses, download
other models, and compare models on YOUR files.

WHAT:  - choices(): the models installed on this laptop (with size and last
           measured speed), which one Chat uses now, a short list of other
           small models that fit a 4 GB graphics card, and the state of any
           download in progress.
       - select(model): save the owner's pick (setting `chat_model`); Chat
           uses it from the next message. Articles and Answers keep their
           own model, so trying a model here cannot disturb the library.
       - download(model): fetch a model through the same background job the
           Setup wizard uses (setup_manager.start_model_downloads).
       - start_compare(models, questions): the "compare on my files" test.
           The SAME questions are put to each chosen model with the SAME
           passages from the owner's bank, using exactly the prompt Chat
           sends (chat.build_prompt). For each model it records writing
           speed, time, how many source markers the answer used and how many
           sentences the fact check had to remove. The answers are kept so
           the owner can read them side by side.
WHY:   The owner asked for a picker so a different small model (for example
       Phi-4-mini or Gemma 3 4B) can be tried against qwen3.5:4b. Public
       rankings say little about cybersecurity PDFs on a 4 GB card, so the
       test uses his own library. Fewer removed sentences, more cited
       sources and a faster speed are all better — but he reads the answers
       and decides.
WHEN:  GET /models/choices, POST /models/select, POST /models/download,
       POST /models/compare/start, GET /models/compare/status, POST
       /models/compare/cancel (server.py), from the Setup screen
       (ModelCard.jsx) and the model list in Chat.jsx.
CONNECTED TO: chat.py (chat_model, build_prompt), answers.py (_sources,
       finalize), ollama_client.py (installed_details, generate, speeds,
       clear_gpu_except), setup_manager.py (downloads), db.py (settings,
       topics for the automatic questions).
"""

from __future__ import annotations

import re
import threading
import time

from . import answers, chat, db, ollama_client, setup_manager

# Other small models worth trying on a 4 GB card. Names are Ollama tags; the
# sizes are approximate and only a guide (Ollama shows the real size while
# downloading). They are SUGGESTIONS, never installed without the owner
# pressing Download.
SUGGESTED = [
    {"name": "phi4-mini", "approx_gb": 3.2, "note": "Microsoft's small model; reported to give the best quality that fits 4 GB."},
    {"name": "gemma3:4b", "approx_gb": 3.3, "note": "Google's small model; check its licence terms before any commercial use."},
    {"name": "llama3.2:3b", "approx_gb": 2.0, "note": "Meta's small model; fast, good at long documents."},
    {"name": "qwen3.5:2b", "approx_gb": 2.7, "note": "A smaller, faster sibling of your current model."},
]

MAX_COMPARE_MODELS = 3
MAX_QUESTIONS = 5
_NAME_OK = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{1,80}$")

_lock = threading.Lock()
_cmp: dict = {"state": "idle"}
_cancel = threading.Event()


def _is_chat_model(name: str) -> bool:
    """Embedding models cannot write answers, so they are not offered."""
    return "embed" not in name.lower()


def choices() -> dict:
    """
    Everything the picker shows.

    RETURNS {"ollama": bool, "current": model Chat uses, "installed": [{name,
    size_mb, current, speed}], "suggested": [{name, approx_gb, note}] (those
    not yet installed), "download": {state, message, current, progress}}.
    """
    running = ollama_client.is_running()
    current = chat.chat_model()
    installed = []
    if running:
        speeds = ollama_client.speeds()
        for m in ollama_client.installed_details():
            if _is_chat_model(m["name"]):
                installed.append({**m, "current": m["name"] in (current, f"{current}:latest"),
                                  "speed": speeds.get(m["name"]) or speeds.get(m["name"].split(":")[0])})
    names = [m["name"] for m in installed]
    suggested = [s for s in SUGGESTED if not ollama_client.has_model(s["name"], names)]
    snap = setup_manager.status()
    job = dict(snap.get("models", {}).get("job", {}))
    return {"ollama": running, "current": current, "installed": installed, "suggested": suggested,
            "download": job}


def select(model: str) -> dict:
    """Use `model` for Chat from now on. It must already be downloaded."""
    model = (model or "").strip()
    if not _NAME_OK.match(model) or not _is_chat_model(model):
        return {"ok": False, "message": "That is not a model that can write answers."}
    if not ollama_client.is_running():
        return {"ok": False, "message": "Start the AI engine first (Setup)."}
    if not ollama_client.has_model(model):
        return {"ok": False, "message": f"{model} is not downloaded yet. Press Download first."}
    db.set_setting("chat_model", model)
    return {"ok": True, "message": f"Chat will now use {model}.", "current": model}


def download(model: str) -> dict:
    """Download one model in the background (progress appears in choices())."""
    model = (model or "").strip()
    if not _NAME_OK.match(model) or not _is_chat_model(model):
        return {"ok": False, "message": "That is not a model name Ollama can download."}
    return setup_manager.start_model_downloads(names=[model])


# ---------------------------------------------------------------------------
# Compare models on the owner's files
# ---------------------------------------------------------------------------

def compare_status() -> dict:
    with _lock:
        return dict(_cmp)


def cancel_compare() -> dict:
    _cancel.set()
    return {"ok": True}


def _sample_questions(n: int = 3) -> list[str]:
    """Questions made from the owner's biggest topics, so the test uses his own subject matter."""
    try:
        with db.connect() as conn:
            rows = conn.execute(
                "SELECT t.title FROM topics t JOIN topic_passages tp ON tp.topic_id = t.id "
                "WHERE COALESCE(t.kind, 'subject') != 'data' GROUP BY t.id "
                "ORDER BY COUNT(*) DESC LIMIT ?", (n,)).fetchall()
    except Exception:
        rows = []
    return [f"Explain {r['title']} and how to detect it or respond to it." for r in rows]


def start_compare(models: list[str], questions: list[str] | None = None) -> dict:
    """
    Begin the comparison in the background.

    models    — 2 or 3 installed model names.
    questions — up to 5 of the owner's own questions, or None for three
                questions made from his biggest topics.
    """
    models = [m.strip() for m in (models or []) if m and m.strip()]
    models = list(dict.fromkeys(models))
    if not 2 <= len(models) <= MAX_COMPARE_MODELS:
        return {"ok": False, "message": f"Choose 2 or {MAX_COMPARE_MODELS} models to compare."}
    if not ollama_client.is_running():
        return {"ok": False, "message": "Start the AI engine first (Setup)."}
    installed = ollama_client.installed_models()
    missing = [m for m in models if not ollama_client.has_model(m, installed) or not _is_chat_model(m)]
    if missing:
        return {"ok": False, "message": f"Not downloaded yet: {', '.join(missing)}."}
    qs = [" ".join(q.split()) for q in (questions or []) if q and len(q.strip()) >= 4][:MAX_QUESTIONS]
    qs = qs or _sample_questions()
    if not qs:
        return {"ok": False, "message": "The bank has no topics yet. Build topics first, or type your own questions."}
    with _lock:
        if _cmp.get("state") == "running":
            return {"ok": False, "message": "A comparison is already running."}
        _cmp.clear()
        _cmp.update(state="running", models=models, questions=qs, results=[], stage="Starting…",
                    total=len(models) * len(qs), done=0, started_at=time.time())
    _cancel.clear()
    threading.Thread(target=_compare_worker, args=(models, qs), name="kb-compare", daemon=True).start()
    return {"ok": True, "message": f"Comparing {len(models)} models on {len(qs)} questions."}


def _compare_worker(models: list[str], questions: list[str]) -> None:
    """
    One model after another (a 4 GB card holds only one), each answering every
    question from the same passages. Passages are looked up once per
    question, so every model sees identical material.
    """
    try:
        passages = {q: answers._sources(q, limit=chat.MAX_SOURCES) for q in questions}
        results = []
        for model in models:
            if _cancel.is_set():
                break
            ollama_client.clear_gpu_except(model)
            rows = []
            for i, q in enumerate(questions, start=1):
                if _cancel.is_set():
                    break
                with _lock:
                    _cmp["stage"] = f"{model}: question {i} of {len(questions)}…"
                src = passages[q]
                system, prompt = chat.build_prompt(q, [], src, general=False)
                r = ollama_client.generate(model, prompt, system=system, temperature=0.2,
                                           num_ctx=chat.NUM_CTX, num_predict=chat.MAX_OUTPUT)
                text = r.text.strip()
                if "NOT IN SOURCES" in text.upper()[:60] or not src:
                    final, removed = "(The model said the files do not cover this.)", []
                else:
                    final, removed = answers.finalize(text, src)
                rows.append({"question": q, "answer": final or "(Nothing survived the fact check.)",
                             "seconds": round(r.total_seconds, 1),
                             "tokens_per_s": round(r.tokens_per_second, 1),
                             "removed_count": len(removed),
                             "cited": len(set(re.findall(r"\[(\d+)\]", final)))})
                with _lock:
                    _cmp["done"] += 1
            if rows:
                n = len(rows)
                results.append({"model": model, "answers": rows,
                                "avg_tokens_per_s": round(sum(x["tokens_per_s"] for x in rows) / n, 1),
                                "avg_seconds": round(sum(x["seconds"] for x in rows) / n, 1),
                                "removed_total": sum(x["removed_count"] for x in rows),
                                "cited_total": sum(x["cited"] for x in rows)})
                with _lock:
                    _cmp["results"] = list(results)
            ollama_client.unload(model)
        with _lock:
            _cmp.update(state="done" if not _cancel.is_set() else "cancelled", stage=None,
                        results=results, seconds=round(time.time() - _cmp["started_at"], 1))
    except Exception as exc:
        with _lock:
            _cmp.update(state="error", stage=None, message=str(exc))
