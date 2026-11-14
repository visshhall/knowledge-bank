# KB — Pending Work Tracker

Living document. Updated after every change. Companion to [KB_REFERENCE.md](KB_REFERENCE.md).

**Current version:** v0.1 (Phase 0 code complete — waiting on owner's laptop run)
**Last updated:** 14 November 2026

---

## Waiting on the owner (blocks Phase 1 model decisions)

- [ ] Grant Claude's GitHub app access to `visshhall/knowledge-bank` so code can be pushed (currently read-only from Claude's side)
- [ ] Download the project and run `setup\setup.ps1`
- [ ] Open the app with `setup\start-app.ps1` — confirm the status screen shows "Engine ready" and the readiness checks
- [ ] Copy 5–10 representative PDFs into a new folder and run `setup\run-benchmark.ps1 "<folder>"`
- [ ] Send the benchmark `.md` report to Claude

## Phase 0 — Foundation ✅ code complete

- [x] Repository structure (app / engine / setup / docs)
- [x] Engine config (paths, port, models — all overridable by environment variable)
- [x] Database schema v1: sources, pages, passages (+ full-text index with auto-sync triggers), images, topics, topic_passages (coverage), topic_links (map), conflicts, jobs
- [x] System check (Python, FTS5, GPU via nvidia-smi, RAM, disk, Ollama, required models)
- [x] Local engine server on 127.0.0.1 with per-launch secret token
- [x] Ollama client (generate, embed, list, unload)
- [x] Benchmark tool (PDF read speed, scanned-page detection, model speed/VRAM/quality, embedding speed, Markdown + JSON report)
- [x] Electron + React shell: starts/stops engine, locked-down window, allow-listed bridge, CSP in builds
- [x] Phase 0 status screen with animated constellation background
- [x] Windows scripts: setup.ps1, run-benchmark.ps1, start-app.ps1
- [x] Tested in Claude's workspace: DB create/upgrade/cascade/full-text sync, server token enforcement, benchmark end-to-end (against a mock AI service), Electron app launched and screenshotted, engine stops on close, PowerShell scripts parse-checked
- [ ] Final model choice — from owner's benchmark

## Phase 1 — Import (next)

- [ ] Import PDFs and images (manual + watched folder)
- [ ] Exact duplicate detection by SHA-256
- [ ] Page-by-page extraction for very large PDFs (background job, resumable)
- [ ] OCR for scanned pages and images (Tesseract vs PaddleOCR decision)
- [ ] Image extraction from PDFs + diagram descriptions (vision model)
- [ ] Passage chunking with source/page tracking
- [ ] Import progress in the interface

## Phase 2 — Distil
- [ ] Embeddings for all passages; vector index (sqlite-vec vs LanceDB decision)
- [ ] Near-duplicate grouping, topic list, topic connections
- [ ] Coverage check

## Phase 3 — Write the knowledge bank
- [ ] Merged topic articles with per-line sources and conflict flags (overnight job)

## Phase 4 — Interface
- [ ] Knowledge Map home (animated), topic pages, animated diagrams
- [ ] Global hotkey search → generated answer pages

## Phase 5 — Learn mode
- [ ] Flashcards, quizzes, scenarios, spaced repetition, progress

## Phase 6 — Web assist + cyber tools
- [ ] Optional web search fallback (labelled; only search words sent)
- [ ] MITRE ATT&CK tagging, IOC extraction, KQL library

## Phase 7 — Updates + release
- [ ] Incremental updates for new PDFs
- [ ] Encrypted backup
- [ ] Windows .exe installer

## Ideas parking lot
_(Ideas tagged "KB idea:" from any chat land here until scheduled.)_
