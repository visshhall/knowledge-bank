# Knowledge Bank

An offline Windows desktop app that turns a collection of cybersecurity PDFs and images into one interactive, animated, de-duplicated knowledge bank: merged topic articles with sources on every line, an animated Knowledge Map, generated answer pages, and Learn mode.

**Status:** v0.23.0 — reads every page of your files into checked question-and-answer pairs, packages them with the full text for a free Google Colab fine-tune, and brings the trained model back into Chat; v0.22.1 — fix: screens no longer freeze or go blank (one crashed screen no longer takes the window down; refreshes never pile up); v0.22.0 — Overview, Library, Topics and Learning now lead with pictures (file-kind donut, subject treemap, 30-day bars, health rings, topic sizes) with a text caption beside each; v0.21.0 — a Live learning screen shows every file and web page as a dot that connects to related ones; new dots light up and link as they are learned, with a replay of how the library grew; v0.20.0 — an Insights screen draws the patterns: a knowledge map of your categories, a weekly coverage heatmap, mistake trends with the lessons marked, and a timeline of what the app did by itself (animated, offline); v0.19.0 — categories and sub-categories grow from your data instead of a fixed list (you can rename, merge or delete the ones it adds); v0.18.0 — it finds what the library lacks per category and fetches it, judges the pages it learned, and stops reading sites that keep giving junk (you can block or allow any site); v0.17.0 — it learns from its own mistakes: bad answers are logged, patterns found (counting how you correct it, and with the AI), turned into lessons it follows, and switched off again if they do not help; v0.16.0 — the app learns by itself: a Learning screen where it reads the web for topics you choose (switch, daily limit, everything it learned can be removed in one click) and turns the Free-chat answers you like or correct into training examples you can export for a cloud fine-tune; v0.15.0 — the app is chat-first: it opens on a new chat with a ChatGPT/Claude-style sidebar (chat history by day, a Knowledge section for the library screens), a message box with attach / add-a-web-page / answer-mode, and Copy, Regenerate and Edit under messages; v0.14.0 — memory about you (short facts you control, used by Free chat); v0.13.0 — read a web address (one page, a section or a whole site) or paste text straight into the bank; v0.12.0 — Free Chat: a switch for each chat (My files / Files + general / Free chat, a plain AI chat with no files) and personas such as an Ākāra copywriter you can edit; v0.11.0 — Chat: talk to your library in saved conversations (cited and fact-checked, general knowledge only when you ask), plus a model picker that can download other small models and compare them on your own files; v0.10.0 — the AI works out what each point is for (what it is, how it works, steps, detection, response, examples) and what it is about; topics are shown and articles written by that logic, with contradictions and gaps called out; v0.9.2 — remove one or many files and everything built from them (topics, articles, flashcards, saved answers) goes too; v0.9.1 — repeated statements are folded inside topics (same sentence from other files/pages shown once, every source kept, AI judges borderline cases); v0.9.0 — cleaner imports (junk lines, garbled text, real titles, categories; Word, PowerPoint, web, text), older versions replaced, better search, hand-edited topics, weak articles rewritten, big-library tuning, self-updating app; v0.8.3 — content already in the bank is never added twice (copies set aside, only new paragraphs added); v0.8.2 — unrelated (non-cybersecurity) files set aside automatically, removed files stay removed, AI tuned to stay on the graphics card; v0.8.1 — faster import (files searchable first, pictures after, parallel and graphics-card OCR); v0.8.0 — spreadsheets become calculated topics (charts, sheet checks, Subnet Lab), animated walk-through diagrams with Play lesson, 3× faster live article writing with line-by-line fact checks — on top of all planned phases (answers, topic map, Learn mode, analyst tools, incremental updates, encrypted backup); Windows installer. See [docs/KB_PENDING.md](docs/KB_PENDING.md).
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
│   ├── electron/updater.cjs  v0.9: the app updates itself (check, download, verify, install)
│   ├── src/App.jsx           Side rail, engine status, Setup screen
│   ├── src/Overview.jsx      Home: schematic of the bank, totals, next step
│   ├── src/FlowMap.jsx       Overview map: files → topics (interactive, animated)
│   ├── src/QuickSearch.jsx   Ctrl+K search by meaning + words
│   ├── src/Answers.jsx       Cited answer pages
│   ├── src/Chat.jsx          v0.11/v0.12: saved chats — My files, Files + general, Free chat, personas
│   ├── src/ModelCard.jsx     v0.11: model picker + compare on my files (Setup)
│   ├── src/MemoryPanel.jsx   v0.14: memory about you (Chat)
│   ├── src/Sidebar.jsx       v0.15: chat history + Knowledge section (left side)
│   ├── src/Learning.jsx      v0.16: web learning + training data screen
│   ├── src/WebAdd.jsx        v0.13: add from the web / paste text (Library)
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
│       ├── facts.py          Folds repeated statements inside a topic (rules + AI judge)
│       ├── understand.py     AI roles + subjects per point, topic outline, article material
│       ├── chat.py           v0.11: saved multi-turn chats over the library (cited, fact-checked)
│       ├── modelpick.py      v0.11: choose/download models, compare them on your files
│       ├── personas.py       v0.12: built-in and own personas (instructions for Free chat)
│       ├── memory.py         v0.14: facts about the owner for Free chat (he approves every one)
│       ├── libtrain.py       v0.23: learn from every page, training package, import trained model
│       ├── glance.py         v0.22: numbers for the at-a-glance pictures
│       ├── brain.py          v0.21: a dot per file/page, related by meaning (live learning view)
│       ├── insights.py       v0.20: numbers behind the Insights screen (map, heatmap, trends, timeline)
│       ├── taxonomy.py       v0.19: categories and sub-categories that grow from the data
│       ├── coverage.py       v0.18: coverage per category, gap topics, page usefulness, junk-site learning
│       ├── mistakes.py       v0.17: mistake log, patterns, lessons, effectiveness check
│       ├── training.py       v0.16: feedback signals, training examples, dataset export
│       ├── learner.py        v0.16: web learning loop (topics, watch addresses, daily budget)
│       ├── websearch.py      v0.16: finds page addresses for a topic
│       ├── crawler.py        v0.13: read a web page / section / site into the bank (polite, same site, never local)
│       ├── search.py         Instant exact-word search
│       ├── meaning.py        Meaning search (vectors) blended with word search
│       ├── answers.py        Cited, fact-checked answers
│       ├── learn.py          Flashcards + spaced repetition
│       ├── tools.py          IOCs, ATT&CK coverage, query library (+ data/mitre_techniques.json)
│       ├── backup.py         AES-256 encrypted backup/restore
│       ├── distill.py        Phase 2: embeddings, topics, repeats, links, names
│       ├── writer.py         Phase 3: one structured, cited, fact-checked article per topic (streamed live)
│       ├── cleaning.py       v0.9: removes junk pages/lines, detects garbled text
│       ├── titles.py         v0.9: readable titles and categories for files
│       ├── officefiles.py    v0.9: reads Word, PowerPoint, web pages, text, Markdown
│       ├── topicedit.py      v0.9: rename / merge / move / split topics by hand
│       ├── storage.py        v0.9: disk space report and clean-up
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
