# Knowledge Bank

An offline Windows desktop app that turns a collection of cybersecurity PDFs and images into one interactive, animated, de-duplicated knowledge bank: merged topic articles with sources on every line, an animated Knowledge Map, generated answer pages, and Learn mode.

**Status:** v0.8.2 — unrelated (non-cybersecurity) files set aside automatically, removed files stay removed, AI tuned to stay on the graphics card; v0.8.1 — faster import (files searchable first, pictures after, parallel and graphics-card OCR); v0.8.0 — spreadsheets become calculated topics (charts, sheet checks, Subnet Lab), animated walk-through diagrams with Play lesson, 3× faster live article writing with line-by-line fact checks — on top of all planned phases (answers, topic map, Learn mode, analyst tools, incremental updates, encrypted backup); Windows installer. See [docs/KB_PENDING.md](docs/KB_PENDING.md).
**Full explanation of what, why and how:** [docs/KB_REFERENCE.md](docs/KB_REFERENCE.md)

---

## For the owner: install and use

1. Double-click **`KnowledgeBank-Setup-<version>.exe`**.
   - Windows may show *"Windows protected your PC"* because the installer isn't code-signed (signing certificates are a paid service). Click **More info → Run anyway**.
2. Choose the install folder (default is fine) → **Install**. No administrator rights needed.
3. Open **Knowledge Bank** from the Desktop or Start menu.
4. Follow the **Setup** panel inside the app:
   1. **AI engine** → *Install AI engine* (downloads and opens Ollama's official installer — click Install there).
   2. **AI models** → *Download AI models* (~15 GB, with progress bars).
   3. **Benchmark** → *Choose PDF folder & run* (pick a folder with 5–10 typical PDFs). When it finishes, *Open report folder* and send the `.md` report to Claude.

No PowerShell, no commands, no Python install — the app carries its own.

## For developers: build from source

Requirements (Linux or WSL): Node 20+, Python 3.12 (the OCR package doesn't support 3.13 yet), `wine64` + `wine32` (electron-builder uses Wine to generate the Windows uninstaller).

```bash
bash tools/build-windows.sh            # → app/release/KnowledgeBank-Setup-<version>.exe
```

Run the app in development mode (live reload):

```bash
cd engine && python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt \
  && .venv/bin/pip install --no-deps -r requirements-nodeps.txt
cd ../app && npm install && npm run dev
```

## Project layout

```
knowledge-bank/
├── app/                      Desktop app (Electron + React)
│   ├── electron/main.cjs     Starts the engine, creates the window, relays allow-listed requests
│   ├── electron/preload.cjs  The only bridge the page may use (window.kb)
│   ├── src/App.jsx           Side rail, engine status, Setup screen
│   ├── src/Overview.jsx      Home: schematic of the bank, totals, next step
│   ├── src/FlowMap.jsx       Overview map: files → topics (interactive, animated)
│   ├── src/QuickSearch.jsx   Ctrl+K search by meaning + words
│   ├── src/Answers.jsx       Cited answer pages
│   ├── src/TopicMap.jsx      Animated topic network
│   ├── src/Learn.jsx         Flashcards, spaced repetition, progress
│   ├── src/Tools.jsx         IOC extractor, ATT&CK coverage, query library
│   ├── src/Backup.jsx        Encrypted backup & restore (Setup)
│   ├── src/SourceChip.jsx    Click a source to open the PDF at that page
│   ├── src/Topics.jsx        Build topics, write articles, topic cards, lesson/article/sources tabs
│   ├── src/Lesson.jsx        Step-by-step visual lesson, quiz, fact-check note
│   ├── src/Diagrams.jsx      Draws lesson visuals: ELK diagrams, walk-throughs, charts, sheet checks, Subnet Lab
│   ├── src/Formatted.jsx     Structured display of passages and articles (no raw HTML)
│   ├── src/Updates.jsx       AI updates card (Setup)
│   ├── src/icons.jsx         Inline line icons
│   ├── src/Library.jsx       Import, watched folders, search, file list
│   ├── src/SetupWizard.jsx   In-app setup: AI engine, model downloads, benchmark
│   ├── src/bridge.js         Shared access to window.kb + helpers
│   ├── src/styles.css        Look and feel
│   ├── build/icon.*          App icon
│   ├── build/after-pack.cjs  Sets the .exe icon and version details during the build
│   └── package.json          Scripts + installer settings ("build" section)
├── engine/                   Python engine (all heavy work)
│   └── kb_engine/
│       ├── config.py         Paths, port, model names
│       ├── db.py             Database schema (sources → pages → passages → topics)
│       ├── server.py         Private local server the window talks to
│       ├── setup_manager.py  Background jobs for the setup wizard
│       ├── importer.py       Phase 1: import PDFs/images/spreadsheets, duplicates, watched folders
│       ├── ocr.py            Reads text from scans, screenshots, diagrams (offline)
│       ├── chunking.py       Cuts page text into citable passages
│       ├── search.py         Instant exact-word search
│       ├── meaning.py        Meaning search (vectors) blended with word search
│       ├── answers.py        Cited, fact-checked answers
│       ├── learn.py          Flashcards + spaced repetition
│       ├── tools.py          IOCs, ATT&CK coverage, query library (+ data/mitre_techniques.json)
│       ├── backup.py         AES-256 encrypted backup/restore
│       ├── distill.py        Phase 2: embeddings, topics, repeats, links, names
│       ├── writer.py         Phase 3: one structured, cited, fact-checked article per topic (streamed live)
│       ├── relevance.py      v0.8.2: is this file about cybersecurity? (vocabulary check, no AI)
│       ├── gpu.py            v0.8.2: keeps the AI on the graphics card (memory savers, speed tuning)
│       ├── datapages.py      v0.8: spreadsheet → calculated topic (charts, checks, Subnet Lab, quiz; no AI)
│       ├── lessons.py        v0.6: designs + fact-checks a visual lesson per topic
│       ├── updates.py        Checks/updates Ollama and the AI models
│       ├── system_check.py   GPU / RAM / disk / Ollama / models readiness
│       ├── ollama_client.py  Talks to the local AI models
│       └── benchmark.py      Picks the best models for this laptop
├── tools/build-windows.sh    Builds the Windows installer
└── docs/                     KB_REFERENCE.md (why/what/how) + KB_PENDING.md (tasks)
```

## Privacy

Everything runs on the laptop. The engine listens only on `127.0.0.1` and requires a per-launch secret token. Your data lives in `%LOCALAPPDATA%\KnowledgeBank`, outside the program folder, survives app updates/uninstalls, and is never committed to Git.
