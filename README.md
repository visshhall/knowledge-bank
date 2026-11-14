# Knowledge Bank

An offline Windows desktop app that turns a collection of cybersecurity PDFs and images into one interactive, animated, de-duplicated knowledge bank: merged topic articles with sources on every line, an animated Knowledge Map, generated answer pages, and Learn mode.

**Status:** v0.1 — Phase 0 (foundation) complete. See [docs/KB_PENDING.md](docs/KB_PENDING.md).
**Full explanation of what, why and how:** [docs/KB_REFERENCE.md](docs/KB_REFERENCE.md)

---

## Quick start (Windows)

Open **PowerShell** in this folder, then:

1. **Install everything (one time, ~15 GB of AI models):**
   ```powershell
   powershell -ExecutionPolicy Bypass -File setup\setup.ps1
   ```
2. **Run the model benchmark** on a folder of 5–10 of your PDFs:
   ```powershell
   powershell -ExecutionPolicy Bypass -File setup\run-benchmark.ps1 "C:\path\to\bench-pdfs"
   ```
   Send the `.md` report it creates to Claude in the KB chat.
3. **Open the app:**
   ```powershell
   powershell -ExecutionPolicy Bypass -File setup\start-app.ps1
   ```

`-ExecutionPolicy Bypass` lets Windows run these scripts once without changing any system setting.

## Project layout

```
knowledge-bank/
├── app/                    Desktop window (Electron + React)
│   ├── electron/main.cjs   Starts the engine, creates the window, relays requests
│   ├── electron/preload.cjs  The only bridge the page may use (window.kb)
│   ├── src/App.jsx         Interface (Phase 0: status + readiness dashboard)
│   ├── src/Constellation.jsx  Animated background (seed of the Knowledge Map)
│   └── src/styles.css      Look and feel
├── engine/                 Python engine (all heavy work)
│   └── kb_engine/
│       ├── config.py       Paths, port, model names
│       ├── db.py           Database schema (sources → pages → passages → topics)
│       ├── server.py       Private local server the window talks to
│       ├── system_check.py GPU / RAM / disk / Ollama / models readiness
│       ├── ollama_client.py  Talks to the local AI models
│       └── benchmark.py    Picks the best models for this laptop
├── setup/                  Windows scripts: setup, benchmark, start
└── docs/                   KB_REFERENCE.md (why/what/how) + KB_PENDING.md (tasks)
```

## Privacy

Everything runs on this laptop. The engine listens only on `127.0.0.1` and requires a per-launch secret token. Your data lives in `%LOCALAPPDATA%\KnowledgeBank`, outside this folder, and is never committed to Git.
