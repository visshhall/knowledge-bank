"""
libtrain.py — v0.23 "Learn from my library": every page of every file becomes training material, then a real fine-tune.

WHAT:  1. READ EVERY PAGE. A background loop walks every page of the owner's own files (not web-learned pages), one page
          at a time, oldest file first. For each page the local chat model writes question-and-answer pairs that the page
          fully answers (2 to 6, depending on how much text the page has).
       2. CHECK EVERY ANSWER. A pair is kept only if (a) every number, ID, IP, event ID and query line in the answer is on
          the page (lessons.Checker, the same checker Chat uses), (b) at least GROUNDED_SHARE of the answer's content
          words are on the page, and (c) it reads on its own (no "this page", "the document"). Anything else is dropped
          and counted, never fixed by guessing. Pages too short to teach anything are marked done as "skipped".
       3. TRAINING PACKAGE. build_package() writes one folder + one zip with:
            kb_text.jsonl   the full cleaned text of EVERY page (raw text: the model reads the files themselves),
            kb_qa.jsonl     every kept question-and-answer pair,
            kb_chat.jsonl   the Free-chat examples from training.py (liked answers and corrections),
            manifest.json   counts, base model, the name the trained model will get,
            KB_finetune.ipynb  a Google Colab notebook that trains the chat model on all of it on a free GPU and saves
                            kb-model.gguf (to Google Drive and as a download), and README.txt with the steps.
       4. BRING IT BACK. start_import(path) checks the .gguf file, builds an Ollama Modelfile from the base model's own
          (so the chat format matches), runs `ollama create kb-tuned`, and switches Chat to it. The previous model is
          remembered so the owner can switch back in one click.
WHY:   Owner (18 Nov 2026): "I want the model to read all the pdf and learn directly instead of half knowledge", and the
       training count was stuck because v0.16 only collected rated Free-chat answers. He chose: every page as checked Q&A
       plus the raw text, trained on a free cloud GPU (his ~4 GB laptop GPU cannot train a 4B model; Unsloth's Qwen3.5-4B
       LoRA needs about 10 GB). Honest limit, shown in the app: a fine-tuned model knows the subject far better but does not
       recall every exact fact; answers with page references still come from the library search.
WHEN:  start() (server.py lifespan) runs _loop: every LOOP_SECONDS it reads PAGES_PER_ROUND page(s) unless switched off
       (setting libtrain_on), Ollama is not running, or Chat / the Answers screen is writing (they always go first).
       build_package() on POST /libtrain/package; start_import() on POST /libtrain/import; status() for the Learning screen.
CONNECTED TO: db.py (tables lib_pages_done, lib_qa — schema v23; pages, passages, sources), lessons.Checker (fact check),
       facts._STOP (stop-words), chat.py (chat_model, status), answers.py (status), training.py (chat examples),
       ollama_client.py (generate, is_running, has_model), setup_manager.find_ollama_exe (ollama create), config.py (data
       folder), server.py (/libtrain/*), Learning.jsx → LibraryTraining.jsx (pictures + controls).
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
import shutil
import subprocess
import threading
import time
import zipfile
from pathlib import Path

from . import __version__, config, db

# --- tuning -----------------------------------------------------------------------------------------------------------
LOOP_SECONDS = 20            # pause between rounds (a round is quick to skip when there is nothing to do)
PAGES_PER_ROUND = 2          # pages read per round when the machine is free
MIN_PAGE_CHARS = 250         # pages shorter than this (covers, blank pages, tables of contents) teach nothing
MAX_PROMPT_CHARS = 5000      # longer pages are cut here for the question writer (the full text still goes in kb_text)
GROUNDED_SHARE = 0.7         # share of an answer's content words that must be on the page
MIN_ANSWER_CHARS = 25
MAX_ANSWER_CHARS = 1200
TEXT_CHUNK_CHARS = 2000      # raw-text pieces in kb_text.jsonl (~500 tokens: fits the 2048-token training window)
TUNED_NAME = "kb-tuned"      # the Ollama name the trained model gets
MIN_GGUF_BYTES = 50_000_000  # anything smaller is not a real model file

# Chat model in Ollama -> the same model's weights for training (Unsloth on Hugging Face). Anything else trains on the
# default (the app's own default chat model), and the owner is told so.
BASES = {
    "qwen3.5:4b": "unsloth/Qwen3.5-4B",
    "qwen3.5:2b": "unsloth/Qwen3.5-2B",
}
DEFAULT_BASE = "qwen3.5:4b"

_SELF_REF = re.compile(r"\b(this|the|above|following)\s+(page|document|text|passage|excerpt|section|pdf|file)\b", re.I)
_WORD = re.compile(r"[a-z0-9]+(?:[.\-_][a-z0-9]+)*")

_state: dict = {"message": "", "current": None}
_import: dict = {"state": "idle", "message": "", "step": ""}
_lock = threading.Lock()
_started = False
_wake = threading.Event()

PROMPT = """Below is page {page} of "{title}".

Write {n} question-and-answer pairs that this page fully answers. Rules:
- Each question is one a security professional would really ask. Each answer is 1-4 sentences.
- Use ONLY facts written on this page. Do not add anything you know from elsewhere.
- Every answer must make sense on its own: name the subject (tool, technique, product, setting) instead of saying "this page", "the document" or "the text".
- Copy numbers, IDs, commands and names exactly as written.
- If the page has fewer useful facts, write fewer pairs. If it has none (a cover, contents, index, blank), reply [].

Reply with JSON only, like: [{{"q": "...", "a": "..."}}]

PAGE TEXT:
{text}
"""

SYSTEM = "You write study questions and answers strictly from the given text. You reply with JSON only."


# --- reading pages ----------------------------------------------------------------------------------------------------
# Own files only (web-learned pages are excluded: the owner chose his PDFs; web pages can be thin or wrong), current
# versions only (a replaced file's pages would teach outdated text), and only files whose text was read.
_LIVE = ("s.status = 'extracted' AND s.replaced_by IS NULL AND COALESCE(s.origin, '') != 'learned'")


def page_text(conn, page_id: int) -> str:
    """The cleaned text of one page: its passages in order (cleaned at import), else the raw page text."""
    rows = conn.execute("SELECT text FROM passages WHERE page_id = ? ORDER BY ordinal", (page_id,)).fetchall()
    if rows:
        return "\n".join(r["text"] for r in rows).strip()
    r = conn.execute("SELECT text FROM pages WHERE id = ?", (page_id,)).fetchone()
    return (r["text"] if r else "").strip()


def pairs_wanted(n_chars: int) -> int:
    """More text, more pairs: 2 for a short page, up to 6 for a dense one."""
    return max(2, min(6, n_chars // 700 + 1))


def _ask(prompt: str) -> str:
    """Ask the chat model (replaceable in tests). Low temperature: we want faithful copying, not creativity."""
    from . import chat, ollama_client
    r = ollama_client.generate(chat.chat_model(), prompt, system=SYSTEM, temperature=0.2, num_ctx=8192,
                               think=False, num_predict=1400)
    return r.text


def parse_pairs(text: str) -> list[tuple[str, str]]:
    """Pull [{"q","a"}] out of the model's reply, tolerating code fences and text around the JSON."""
    text = (text or "").strip()
    start, end = text.find("["), text.rfind("]")
    if start < 0 or end <= start:
        return []
    try:
        data = json.loads(text[start:end + 1])
    except ValueError:
        return []
    out = []
    for item in data if isinstance(data, list) else []:
        if isinstance(item, dict):
            q = str(item.get("q") or item.get("question") or "").strip()
            a = str(item.get("a") or item.get("answer") or "").strip()
            if q and a:
                out.append((q, a))
    return out


def _content_words(text: str) -> list[str]:
    from .facts import _STOP
    return [w for w in _WORD.findall(text.lower()) if len(w) > 3 and w not in _STOP]


def check_pair(q: str, a: str, page: str) -> tuple[bool, str]:
    """
    Is this pair safe to teach? RETURNS (ok, reason). Strict on purpose: a dropped pair costs nothing (the raw text of
    the page is still trained on), a wrong pair teaches a wrong fact.
    """
    from .lessons import Checker
    if len(a) < MIN_ANSWER_CHARS:
        return False, "too short"
    if len(a) > MAX_ANSWER_CHARS or len(q) > 400:
        return False, "too long"
    if _SELF_REF.search(q) or _SELF_REF.search(a):
        return False, "refers to the page"
    ck = Checker([page])
    ck.clean_text(a, max_len=MAX_ANSWER_CHARS)
    if ck.removed:  # any sentence with a number / ID / command not on the page → the whole pair goes
        return False, "a fact is not on the page"
    words = _content_words(a)
    if words:
        on_page = set(_WORD.findall(page.lower()))
        if sum(w in on_page for w in words) / len(words) < GROUNDED_SHARE:
            return False, "not enough of it is on the page"
    return True, ""


def process_page(page_id: int) -> dict:
    """Read one page, write its pairs, keep the checked ones. RETURNS {kept, dropped, skipped, seconds}."""
    started = time.time()
    with db.connect() as conn:
        row = conn.execute("SELECT p.id, p.page_number, p.source_id, COALESCE(s.title, s.file_name) AS title "
                           "FROM pages p JOIN sources s ON s.id = p.source_id WHERE p.id = ?", (page_id,)).fetchone()
        if not row:
            return {"kept": 0, "dropped": 0, "skipped": True, "seconds": 0}
        text = page_text(conn, page_id)
    kept, dropped, reasons, skipped = [], 0, {}, False
    if len(text) < MIN_PAGE_CHARS:
        skipped = True
    else:
        n = pairs_wanted(len(text))
        reply = _ask(PROMPT.format(page=row["page_number"], title=row["title"], n=n, text=text[:MAX_PROMPT_CHARS]))
        seen = set()
        for q, a in parse_pairs(reply)[:n + 2]:
            ok, why = check_pair(q, a, text)
            key = q.lower()
            if ok and key not in seen:
                seen.add(key)
                kept.append((q, a))
            else:
                dropped += 1
                reasons[why or "repeat"] = reasons.get(why or "repeat", 0) + 1
    seconds = round(time.time() - started, 1)
    with db.connect() as conn:
        for q, a in kept:
            conn.execute("INSERT OR IGNORE INTO lib_qa(page_id, source_id, question, answer) VALUES (?, ?, ?, ?)",
                         (page_id, row["source_id"], q, a))
        conn.execute("INSERT INTO lib_pages_done(page_id, source_id, kept, dropped, skipped, seconds, reasons_json) "
                     "VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(page_id) DO UPDATE SET kept = excluded.kept, "
                     "dropped = excluded.dropped, skipped = excluded.skipped, seconds = excluded.seconds, "
                     "reasons_json = excluded.reasons_json, done_at = datetime('now')",
                     (page_id, row["source_id"], len(kept), dropped, int(skipped), seconds, json.dumps(reasons)))
    return {"kept": len(kept), "dropped": dropped, "skipped": skipped, "seconds": seconds}


def next_pages(limit: int) -> list[int]:
    """Pages not read yet, oldest file first, page order within a file (so a file completes before the next starts)."""
    with db.connect() as conn:
        return [r[0] for r in conn.execute(
            f"SELECT p.id FROM pages p JOIN sources s ON s.id = p.source_id LEFT JOIN lib_pages_done d ON d.page_id = p.id "
            f"WHERE {_LIVE} AND d.page_id IS NULL ORDER BY s.id, p.page_number LIMIT ?", (limit,))]


def is_on() -> bool:
    return bool(db.get_setting("libtrain_on", True))


def set_on(on: bool) -> dict:
    db.set_setting("libtrain_on", bool(on))
    _wake.set()
    return {"ok": True, "on": bool(on)}


def _machine_busy() -> str | None:
    """Why reading should wait right now, or None. The owner's own questions always go first."""
    from . import answers, chat, ollama_client
    if not ollama_client.is_running():
        return "Waiting for the AI engine (Ollama) to start."
    if chat.status().get("state") == "running":
        return "Paused while Chat is answering."
    try:
        if answers.status().get("state") == "running":
            return "Paused while an answer is being written."
    except Exception:
        pass
    return None


def run_round(n: int = PAGES_PER_ROUND) -> dict:
    """One round: read up to n pages if allowed. Used by the loop and by tests."""
    if not is_on():
        _state.update(message="Switched off.", current=None)
        return {"read": 0, "reason": "off"}
    busy = _machine_busy()
    if busy:
        _state.update(message=busy, current=None)
        return {"read": 0, "reason": busy}
    read = 0
    for pid in next_pages(n):
        _state.update(current=pid, message="Reading your files page by page.")
        try:
            process_page(pid)
            read += 1
        except Exception as exc:  # a page that fails (model error, timeout) is retried next round, not marked done
            _state.update(message=f"Reading paused: {exc}", current=None)
            return {"read": read, "reason": str(exc)}
    _state.update(current=None, message="Reading your files page by page." if read else "Every page has been read.")
    return {"read": read, "reason": ""}


def _loop() -> None:
    time.sleep(45)  # let the import and the other start-up jobs go first
    while True:
        try:
            run_round()
        except Exception as exc:
            _state.update(message=f"Reading paused: {exc}", current=None)
        _wake.wait(LOOP_SECONDS)
        _wake.clear()


def start() -> None:
    """server.py lifespan: start the page-reading loop once."""
    global _started
    if _started:
        return
    _started = True
    threading.Thread(target=_loop, name="libtrain", daemon=True).start()


# --- status for the Learning screen --------------------------------------------------------------------------------------
def status() -> dict:
    """
    Everything the "Learn from your files" card draws. RETURNS {on, message, pages:{total, done, skipped, left, pct},
    pairs:{kept, dropped, reasons}, eta_hours, sec_per_page, daily:[{date, pages, pairs}] x30, categories:[{name, total,
    done, pct}], files:{total, done}, recent:[{id, q, a, file, page}], tuned:{installed, active, previous}, import}.
    """
    from . import chat, ollama_client
    with db.connect() as conn:
        total = conn.execute(f"SELECT COUNT(*) FROM pages p JOIN sources s ON s.id = p.source_id WHERE {_LIVE}").fetchone()[0]
        d = conn.execute(f"SELECT COUNT(*) AS n, COALESCE(SUM(d.skipped), 0) AS sk, COALESCE(SUM(d.kept), 0) AS k, "
                         f"COALESCE(SUM(d.dropped), 0) AS dr FROM lib_pages_done d JOIN pages p ON p.id = d.page_id "
                         f"JOIN sources s ON s.id = p.source_id WHERE {_LIVE}").fetchone()
        kept = conn.execute(f"SELECT COUNT(*) FROM lib_qa q JOIN sources s ON s.id = q.source_id "
                            f"WHERE {_LIVE} AND q.status = 'kept'").fetchone()[0]
        reasons: dict = {}
        for r in conn.execute("SELECT reasons_json FROM lib_pages_done WHERE reasons_json != '{}' ORDER BY done_at DESC LIMIT 2000"):
            for k, v in json.loads(r[0]).items():
                reasons[k] = reasons.get(k, 0) + v
        recent_secs = [r[0] for r in conn.execute(
            "SELECT seconds FROM lib_pages_done WHERE skipped = 0 ORDER BY done_at DESC, page_id DESC LIMIT 50")]
        today = _dt.date.today()
        start = (today - _dt.timedelta(days=29)).isoformat()
        per_day = {r["d"]: (r["n"], r["k"]) for r in conn.execute(
            "SELECT date(done_at) AS d, COUNT(*) AS n, SUM(kept) AS k FROM lib_pages_done WHERE date(done_at) >= ? "
            "GROUP BY date(done_at)", (start,))}
        cats: dict = {}
        for r in conn.execute(
                f"SELECT s.categories AS c, COUNT(p.id) AS n, COUNT(d.page_id) AS done FROM sources s "
                f"JOIN pages p ON p.source_id = s.id LEFT JOIN lib_pages_done d ON d.page_id = p.id "
                f"WHERE {_LIVE} GROUP BY s.id"):
            try:
                name = (json.loads(r["c"] or "[]") or ["Uncategorised"])[0]
            except ValueError:
                name = "Uncategorised"
            t = cats.setdefault(name, [0, 0])
            t[0] += r["n"]
            t[1] += r["done"]
        files_total = conn.execute(f"SELECT COUNT(*) FROM sources s WHERE {_LIVE}").fetchone()[0]
        files_done = conn.execute(
            f"SELECT COUNT(*) FROM sources s WHERE {_LIVE} AND NOT EXISTS (SELECT 1 FROM pages p LEFT JOIN lib_pages_done d "
            f"ON d.page_id = p.id WHERE p.source_id = s.id AND d.page_id IS NULL)").fetchone()[0]
        recent = [{"id": r["id"], "q": r["question"], "a": r["answer"], "file": r["f"], "page": r["page_number"]}
                  for r in conn.execute(
                      "SELECT q.id, q.question, q.answer, COALESCE(s.title, s.file_name) AS f, p.page_number "
                      "FROM lib_qa q JOIN sources s ON s.id = q.source_id JOIN pages p ON p.id = q.page_id "
                      "WHERE q.status = 'kept' ORDER BY q.id DESC LIMIT 6")]
    done = d["n"]
    left = max(0, total - done)
    spp = (sum(recent_secs) / len(recent_secs)) if recent_secs else None
    daily = []
    for i in range(30):
        day = (today - _dt.timedelta(days=29 - i)).isoformat()
        n, k = per_day.get(day, (0, 0))
        daily.append({"date": day, "pages": n, "pairs": k or 0})
    installed = active = False
    try:
        if ollama_client.is_running():
            installed = ollama_client.has_model(TUNED_NAME)
            active = chat.chat_model().split(":")[0] == TUNED_NAME
    except Exception:
        pass
    return {
        "on": is_on(), "message": _state.get("message", ""), "reading": _state.get("current") is not None,
        "pages": {"total": total, "done": done, "skipped": d["sk"], "left": left,
                  "pct": round(100 * done / total) if total else 0},
        "pairs": {"kept": kept, "dropped": d["dr"], "reasons": reasons},
        "sec_per_page": round(spp, 1) if spp is not None else None,
        "eta_hours": 0 if not left else (round(left * spp / 3600, 1) if spp is not None else None),
        "daily": daily,
        "categories": sorted(({"name": k, "total": v[0], "done": v[1], "pct": round(100 * v[1] / v[0]) if v[0] else 0}
                              for k, v in cats.items()), key=lambda c: -c["total"]),
        "files": {"total": files_total, "done": files_done},
        "recent": recent,
        "tuned": {"installed": installed, "active": active, "name": TUNED_NAME,
                  "previous": db.get_setting("chat_model_before_tuned")},
        "import": dict(_import),
        "last_package": db.get_setting("libtrain_last_package"),
    }


def reject(qa_id: int) -> dict:
    """The owner thinks a pair is wrong: it is never trained on (and stays out of the next package)."""
    with db.connect() as conn:
        conn.execute("UPDATE lib_qa SET status = 'rejected' WHERE id = ?", (int(qa_id),))
    return {"ok": True}


# --- training package ----------------------------------------------------------------------------------------------------
def _chunks(text: str, size: int = TEXT_CHUNK_CHARS) -> list[str]:
    """Split page text into pieces of at most `size` characters at line, then sentence, boundaries."""
    out, cur = [], ""
    for part in re.split(r"(?<=\n)|(?<=[.!?])\s+", text):
        if not part:
            continue
        while len(part) > size:  # a single enormous line (a table dump) is cut hard
            if cur:
                out.append(cur.strip())
                cur = ""
            out.append(part[:size].strip())
            part = part[size:]
        if len(cur) + len(part) + 1 > size and cur:
            out.append(cur.strip())
            cur = ""
        cur += part if part.endswith("\n") else part + " "
    if cur.strip():
        out.append(cur.strip())
    return [c for c in out if len(c) >= 40]


def base_model() -> tuple[str, str, str]:
    """(Ollama base name, Hugging Face training name, note for the owner) for the current chat model."""
    from . import chat
    current = chat.chat_model()
    key = current if current in BASES else (current + ":latest" if current + ":latest" in BASES else None)
    if current.split(":")[0] == TUNED_NAME:  # already tuned: train again from the same base
        key = db.get_setting("tuned_base") or DEFAULT_BASE
    if key:
        return key, BASES[key], ""
    return DEFAULT_BASE, BASES[DEFAULT_BASE], (
        f"Your chat model ({current}) cannot be trained by the notebook, so {DEFAULT_BASE} is trained instead. "
        f"It must be downloaded in Setup → Models before the trained model can be brought in.")


def build_package() -> dict:
    """
    Write the training package. Works at any time: the raw text always covers every page; question-and-answer pairs
    cover the pages read so far (the result says how many). RETURNS {ok, folder, zip, notebook, counts, note, message}.
    """
    from . import training
    ollama_base, hf_base, note = base_model()
    with db.connect() as conn:
        pages = conn.execute(
            f"SELECT p.id, p.page_number, COALESCE(s.title, s.file_name) AS title FROM pages p "
            f"JOIN sources s ON s.id = p.source_id WHERE {_LIVE} ORDER BY s.id, p.page_number").fetchall()
        text_lines = []
        for p in pages:
            for c in _chunks(page_text(conn, p["id"])):
                text_lines.append(json.dumps({"text": f"From {p['title']}, page {p['page_number']}:\n{c}"},
                                             ensure_ascii=False))
        qa = conn.execute(f"SELECT q.question, q.answer FROM lib_qa q JOIN sources s ON s.id = q.source_id "
                          f"WHERE {_LIVE} AND q.status = 'kept' ORDER BY q.id").fetchall()
        rejected = {(r[0].strip().lower(), r[1].strip().lower())
                    for r in conn.execute("SELECT question, answer FROM lib_qa WHERE status = 'rejected'")}
    # The same pair from several pages (repeated slides, headers) is trained once; a pair the owner rejected anywhere
    # is left out everywhere.
    qa_lines, seen = [], set()
    for r in qa:
        key = (r["question"].strip().lower(), r["answer"].strip().lower())
        if key in seen or key in rejected:
            continue
        seen.add(key)
        qa_lines.append(json.dumps({"messages": [{"role": "user", "content": r["question"]},
                                                 {"role": "assistant", "content": r["answer"]}]}, ensure_ascii=False))
    chat_lines = training.chat_lines()
    if not text_lines:
        return {"ok": False, "message": "There is no text to train on yet. Add files in Library first."}
    stamp = _dt.datetime.now().strftime("%Y-%m-%d-%H%M")
    folder = config.DATA_DIR / "training" / f"package-{stamp}"
    folder.mkdir(parents=True, exist_ok=True)
    counts = {"text_pieces": len(text_lines), "qa_pairs": len(qa_lines), "chat_examples": len(chat_lines),
              "pages": len(pages)}
    st = status()
    manifest = {"created": _dt.datetime.now().isoformat(timespec="seconds"), "app_version": __version__,
                "ollama_base": ollama_base, "hf_base": hf_base, "model_name": TUNED_NAME, "counts": counts,
                "pages_read_pct": st["pages"]["pct"]}
    files = {
        "kb_text.jsonl": "\n".join(text_lines) + "\n",
        "kb_qa.jsonl": ("\n".join(qa_lines) + "\n") if qa_lines else "",
        "kb_chat.jsonl": ("\n".join(chat_lines) + "\n") if chat_lines else "",
        "manifest.json": json.dumps(manifest, indent=2),
    }
    for name, body in files.items():
        (folder / name).write_text(body, encoding="utf-8")
    zip_path = folder / f"KB-training-data-{stamp}.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for name in files:
            z.write(folder / name, arcname=name)
    nb_path = folder / "KB_finetune.ipynb"
    nb_path.write_text(json.dumps(notebook(manifest), indent=1), encoding="utf-8")
    (folder / "README.txt").write_text(README.format(zip=zip_path.name, **counts, pct=st["pages"]["pct"],
                                                     base=hf_base, name=TUNED_NAME), encoding="utf-8")
    db.set_setting("libtrain_last_package", str(folder))
    msg = (f"Package ready: every page as raw text ({counts['text_pieces']:,} pieces), {counts['qa_pairs']:,} checked "
           f"question-and-answer pairs and {counts['chat_examples']:,} chat examples.")
    if st["pages"]["pct"] < 100:
        msg += f" Only {st['pages']['pct']}% of pages have question-and-answer pairs so far; you can train now and again later."
    return {"ok": True, "folder": str(folder), "zip": str(zip_path), "notebook": str(nb_path), "counts": counts,
            "note": note, "message": msg}


README = """KNOWLEDGE BANK — TRAINING PACKAGE
==================================

What is in it
  {zip}   the training data (upload this when the notebook asks)
      kb_text.jsonl   every page of your files as plain text ({text_pieces} pieces from {pages} pages)
      kb_qa.jsonl     {qa_pairs} checked question-and-answer pairs ({pct}% of pages read so far)
      kb_chat.jsonl   {chat_examples} Free-chat answers you liked or corrected
  KB_finetune.ipynb   the training notebook (trains {base})

Steps (about 2-4 hours, free, nothing to install on your laptop)
  1. Open https://colab.research.google.com and sign in with a Google account.
  2. File > Upload notebook > choose KB_finetune.ipynb from this folder.
  3. Runtime > Change runtime type > T4 GPU > Save.
  4. Runtime > Run all. Allow Google Drive access when asked (the trained model is saved there).
  5. When the upload button appears, choose {zip}.
  6. Leave the tab open until it says DONE. The file kb-model.gguf is saved to Google Drive in the folder
     KnowledgeBank (and offered as a download).
  7. Download kb-model.gguf to your laptop. In Knowledge Bank > Learning > "Learn from your files", press
     "Bring in the trained model" and choose the file. Chat then answers with "{name}".

Your files leave your laptop only in step 5, to your own Google Colab session. Delete the session afterwards
(Runtime > Disconnect and delete runtime) and the files in Drive if you do not want to keep them.
"""


def _cell(kind: str, src: str) -> dict:
    c = {"cell_type": kind, "metadata": {}, "source": src.strip("\n").splitlines(keepends=True)}
    if kind == "code":
        c.update(execution_count=None, outputs=[])
    return c


def notebook(manifest: dict) -> dict:
    """
    The Google Colab notebook. Install cell copied from Unsloth's official Qwen3.5 notebooks (Nov 2026); text-only loading
    pattern from their Qwen3.5 text notebook (FastLanguageModel returns a processor; its .tokenizer is used). Trains a
    16-bit LoRA (Unsloth: 4-bit is not recommended for Qwen3.5) on raw text + Q&A + chat examples for one pass, stops
    early at MAX_MINUTES so a free session does not end before the model is saved, then saves q4_k_m GGUF.
    """
    hf = manifest["hf_base"]
    cells = [
        _cell("markdown", f"""
# Knowledge Bank: train your model on your files

Trains **{hf}** on everything in your library: the text of every page, the checked question-and-answer pairs and your
chat examples. Uses a free T4 GPU. Steps: **Runtime > Change runtime type > T4 GPU**, then **Runtime > Run all**.
When asked, allow Google Drive and upload the `KB-training-data-....zip` from your training package folder.
The trained model is saved as **kb-model.gguf** in Google Drive > KnowledgeBank.
"""),
        _cell("code", """
#@title Settings
MAX_MINUTES = 150   #@param {type:"integer"}  stop training after this long, so the model is saved before Colab ends the session
TEXT_PASSES = 1     #@param {type:"integer"}  how many times the model reads every page (2 = better memory, twice as long)
SAVE_TO_DRIVE = True #@param {type:"boolean"}
"""),
        _cell("code", """
%%capture
import os, importlib.util
!pip install --upgrade -qqq uv
if importlib.util.find_spec("torch") is None or "COLAB_" in "".join(os.environ.keys()):
    try: import numpy, PIL; _numpy = f"numpy=={numpy.__version__}"; _pil = f"pillow=={PIL.__version__}"
    except: _numpy = "numpy"; _pil = "pillow"
    !uv pip install -qqq \\
        "torch==2.8.0" "triton>=3.3.0" {_numpy} {_pil} torchvision "torchaudio==2.8.0" bitsandbytes xformers==0.0.32.post2 \\
        "unsloth_zoo[base] @ git+https://github.com/unslothai/unsloth-zoo" \\
        "unsloth[base] @ git+https://github.com/unslothai/unsloth"
    !uv pip install -qqq --no-deps "torchcodec==0.7.0"
elif importlib.util.find_spec("unsloth") is None:
    !uv pip install -qqq unsloth
!uv pip install --upgrade --no-deps "tokenizers>=0.22.0,<=0.23.0" trl==0.22.2 unsloth unsloth_zoo
!uv pip install transformers==5.2.0
!unsloth install-kernels
!uv pip install --no-deps --upgrade "torchao>=0.16.0"
"""),
        _cell("code", """
# Upload the training data zip from your Knowledge Bank training package folder.
import zipfile, json, io, os
from google.colab import files
up = files.upload()
name = next(n for n in up if n.endswith(".zip"))
zipfile.ZipFile(io.BytesIO(up[name])).extractall("kb_data")
manifest = json.load(open("kb_data/manifest.json"))
print("Package from", manifest["created"], manifest["counts"])
"""),
        _cell("code", f"""
from unsloth import FastLanguageModel
import torch
model, processor = FastLanguageModel.from_pretrained(
    "{hf}",
    max_seq_length = 2048,
    load_in_4bit = False,   # Unsloth: 16-bit LoRA for Qwen3.5 (4-bit is not recommended)
)
tokenizer = getattr(processor, "tokenizer", processor)
model = FastLanguageModel.get_peft_model(
    model,
    r = 16, lora_alpha = 16, lora_dropout = 0, bias = "none",
    target_modules = ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
    use_gradient_checkpointing = "unsloth",
    random_state = 3407,
)
"""),
        _cell("code", """
# One training set: the text of every page (read TEXT_PASSES times) + Q&A pairs + chat examples, shuffled.
import random
from datasets import Dataset
def read_jsonl(path):
    if not os.path.exists(path): return []
    return [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
def chat_text(messages):
    try:
        return tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=False, enable_thinking=False)
    except TypeError:
        return tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=False)
raw = [r["text"] + tokenizer.eos_token for r in read_jsonl("kb_data/kb_text.jsonl")]
qa = [chat_text(r["messages"]) for r in read_jsonl("kb_data/kb_qa.jsonl") + read_jsonl("kb_data/kb_chat.jsonl")]
texts = raw * max(1, TEXT_PASSES) + qa
random.Random(3407).shuffle(texts)
dataset = Dataset.from_dict({"text": texts})
print(f"{len(raw)} page pieces x{TEXT_PASSES}, {len(qa)} question-answer examples, {len(texts)} total")
"""),
        _cell("code", """
import time
from trl import SFTTrainer, SFTConfig
from transformers import TrainerCallback
class StopInTime(TrainerCallback):
    # Free Colab sessions end after a few hours; stop early so the model is always saved.
    def on_train_begin(self, args, state, control, **kw): self.t0 = time.time()
    def on_step_end(self, args, state, control, **kw):
        if time.time() - self.t0 > MAX_MINUTES * 60:
            print("Time limit reached; saving what has been learned so far.")
            control.should_training_stop = True
trainer = SFTTrainer(
    model = model,
    tokenizer = tokenizer,
    train_dataset = dataset,
    callbacks = [StopInTime()],
    args = SFTConfig(
        dataset_text_field = "text",
        max_length = 2048,
        per_device_train_batch_size = 2,
        gradient_accumulation_steps = 4,
        warmup_steps = 10,
        num_train_epochs = 1,
        learning_rate = 2e-4,
        logging_steps = 10,
        optim = "adamw_8bit",
        weight_decay = 0.001,
        lr_scheduler_type = "linear",
        seed = 3407,
        output_dir = "outputs",
        report_to = "none",
    ),
)
stats = trainer.train()
print("Trained for", round(stats.metrics.get("train_runtime", 0) / 60), "minutes")
"""),
        _cell("code", """
# Quick check: ask the trained model one question from your own files.
FastLanguageModel.for_inference(model)
sample = (read_jsonl("kb_data/kb_qa.jsonl") or [{"messages": [{"role": "user", "content": "What topics do my files cover?"}]}])[0]
q = sample["messages"][0]["content"]
try:
    prompt = tokenizer.apply_chat_template([{"role": "user", "content": q}], tokenize=False, add_generation_prompt=True, enable_thinking=False)
except TypeError:
    prompt = tokenizer.apply_chat_template([{"role": "user", "content": q}], tokenize=False, add_generation_prompt=True)
out = model.generate(**tokenizer(prompt, return_tensors="pt").to("cuda"), max_new_tokens=200, temperature=0.7, top_p=0.8, top_k=20)
print("Q:", q)
print("A:", tokenizer.decode(out[0][len(tokenizer(prompt)["input_ids"]):], skip_special_tokens=True))
"""),
        _cell("code", """
# Save as kb-model.gguf (4-bit, the size Ollama runs on your laptop) to Google Drive and as a download.
import glob, shutil
model.save_pretrained_gguf("kb_model", tokenizer, quantization_method = "q4_k_m")
found = [f for f in glob.glob("**/*.gguf", recursive=True) if "mmproj" not in f.lower()]
best = sorted(found, key=lambda f: ("q4_k_m" not in f.lower(), -os.path.getsize(f)))[0]
shutil.copy(best, "kb-model.gguf")
print("Saved", best, round(os.path.getsize("kb-model.gguf") / 1e9, 2), "GB")
if SAVE_TO_DRIVE:
    from google.colab import drive
    drive.mount("/content/drive")
    os.makedirs("/content/drive/MyDrive/KnowledgeBank", exist_ok=True)
    shutil.copy("kb-model.gguf", "/content/drive/MyDrive/KnowledgeBank/kb-model.gguf")
    print("In Google Drive: MyDrive/KnowledgeBank/kb-model.gguf")
try:
    files.download("kb-model.gguf")
except Exception as e:
    print("Browser download did not start; use the Google Drive copy.", e)
print("DONE. In Knowledge Bank > Learning, press 'Bring in the trained model' and choose kb-model.gguf.")
"""),
    ]
    return {"cells": cells, "metadata": {"accelerator": "GPU", "colab": {"provenance": [], "gpuType": "T4"},
                                         "kernelspec": {"name": "python3", "display_name": "Python 3"},
                                         "language_info": {"name": "python"}},
            "nbformat": 4, "nbformat_minor": 0}


# --- bringing the trained model back -------------------------------------------------------------------------------------
def _set_import(**kw) -> None:
    with _lock:
        _import.update(kw)


def check_gguf(path: str) -> str | None:
    """Why this file cannot be the trained model, or None if it looks right (GGUF header, realistic size)."""
    p = Path(path or "")
    if not p.is_file():
        return "File not found."
    if p.suffix.lower() != ".gguf":
        return "Choose the .gguf file the notebook saved (kb-model.gguf)."
    if p.stat().st_size < MIN_GGUF_BYTES:
        return "That file is too small to be a model. Download kb-model.gguf again (it is about 2–3 GB)."
    with open(p, "rb") as f:
        if f.read(4) != b"GGUF":
            return "That file is not a GGUF model (it may be incomplete). Download kb-model.gguf again."
    return None


def _modelfile(base_text: str, gguf: str) -> str:
    """The base model's own Modelfile with its FROM line pointed at the trained weights (keeps the chat format)."""
    lines, replaced = [], False
    for line in base_text.splitlines():
        if line.strip().upper().startswith("FROM "):
            if not replaced:
                lines.append(f'FROM "{gguf}"')
                replaced = True
            continue  # extra FROM lines (e.g. a vision adapter) do not belong to the trained weights
        lines.append(line)
    if not replaced:
        lines.insert(0, f'FROM "{gguf}"')
    return "\n".join(lines) + "\n"


def _run(args: list[str], timeout: int) -> subprocess.CompletedProcess:
    """Run the ollama program without a console window (replaceable in tests)."""
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout, creationflags=flags)


def start_import(path: str) -> dict:
    """Check the file, then create the Ollama model in the background (copying a 2–3 GB file takes a few minutes)."""
    why = check_gguf(path)
    if why:
        return {"ok": False, "message": why}
    with _lock:
        if _import.get("state") == "running":
            return {"ok": False, "message": "Already bringing a model in."}
        _import.update(state="running", message="Starting…", step="check")
    threading.Thread(target=_import_worker, args=(str(path),), name="libtrain-import", daemon=True).start()
    return {"ok": True, "message": "Bringing the trained model in…"}


def _import_worker(path: str) -> None:
    from . import chat, ollama_client, setup_manager
    try:
        exe = setup_manager.find_ollama_exe()
        if not exe or not ollama_client.is_running():
            raise RuntimeError("The AI engine (Ollama) is not running. Start it from Setup, then try again.")
        ollama_base, _, _ = base_model()
        if not ollama_client.has_model(ollama_base):
            raise RuntimeError(f"The base model {ollama_base} is needed for the chat format. Download it in Setup → Models first.")
        _set_import(step="modelfile", message=f"Reading {ollama_base}'s settings…")
        shown = _run([exe, "show", ollama_base, "--modelfile"], timeout=120)
        if shown.returncode != 0:
            raise RuntimeError(f"Could not read {ollama_base}: {shown.stderr.strip()[:200]}")
        folder = config.DATA_DIR / "training" / "model"
        folder.mkdir(parents=True, exist_ok=True)
        mf = folder / "Modelfile"
        mf.write_text(_modelfile(shown.stdout, path), encoding="utf-8")
        _set_import(step="create", message="Copying the model into the AI engine (a few minutes for 2–3 GB)…")
        made = _run([exe, "create", TUNED_NAME, "-f", str(mf)], timeout=3600)
        if made.returncode != 0:
            raise RuntimeError(f"The AI engine refused the file: {(made.stderr or made.stdout).strip()[-300:]}")
        _set_import(step="switch", message="Switching Chat to the trained model…")
        current = chat.chat_model()
        if current.split(":")[0] != TUNED_NAME:
            db.set_setting("chat_model_before_tuned", current)
        db.set_setting("tuned_base", ollama_base)
        db.set_setting("chat_model", f"{TUNED_NAME}:latest")
        _set_import(state="done", step="done", message=f"Chat now answers with {TUNED_NAME}, trained on your files.")
    except Exception as exc:
        _set_import(state="error", step="", message=str(exc))


def use_model(which: str) -> dict:
    """Switch Chat between the trained model ('tuned') and the one used before it ('previous')."""
    from . import modelpick
    if which == "tuned":
        return modelpick.select(f"{TUNED_NAME}:latest")
    prev = db.get_setting("chat_model_before_tuned")
    if not prev:
        return {"ok": False, "message": "No earlier model is remembered."}
    return modelpick.select(prev)
