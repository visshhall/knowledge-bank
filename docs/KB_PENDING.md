# KB — Pending Work Tracker

Living document. Updated after every change. Companion to [KB_REFERENCE.md](KB_REFERENCE.md).

**Current version:** v0.5 (articles, readable text, AI updates — benchmark report still pending)
**Last updated:** 14 November 2026

---

## Waiting on the owner (blocks Phase 1 model decisions)

- [x] GitHub access granted — code is pushed to `visshhall/knowledge-bank`
- [x] Installed v0.2 — app runs on the owner's laptop (RTX 3050 4 GB, 16 GB RAM)
- [x] All AI models downloaded (14 Nov)
- [x] First real test with 6 PDFs (topics built) — feedback: text unreadable → fixed in v0.5
- [ ] Install `KnowledgeBank-Setup-0.5.0.exe` over the previous version (data and models are kept) — after model downloads finish
- [ ] Topics → Rebuild topics (needed once after v0.5's text re-organise), then Write articles
- [ ] Read a few articles; report anything wrong (missing facts, wrong citations, bad sections)
- [ ] Setup → AI updates → Check for updates
- [ ] Add PDFs in Library and check: scanned pages show a count in the Scanned column (confirms OCR works on Windows)
- [ ] Open the app → confirm "Engine ready" and the Setup panel
- [ ] Setup step 1: Install AI engine · step 2: Download AI models · step 3: run the benchmark on a folder of 5–10 PDFs
- [ ] Send the benchmark `.md` report (Open report folder) to Claude

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
- [x] ~~Windows PowerShell scripts~~ — replaced in v0.2 (owner wants a normal .exe)
- [x] v0.2: in-app setup wizard (AI engine install/start, model downloads with progress, benchmark with folder picker, open reports)
- [x] v0.2: Windows installer with bundled private Python 3.12, per-user install, shortcuts, custom icon + version details
- [x] v0.2: installer verified under Wine (installs, shortcuts, bundled engine runs and passes setup/benchmark flow against a mock AI service)
- [x] Tested in Claude's workspace: DB create/upgrade/cascade/full-text sync, server token enforcement, benchmark end-to-end (against a mock AI service), Electron app launched and screenshotted, engine stops on close, PowerShell scripts parse-checked
- [ ] Final model choice — from owner's benchmark

## Phase 1 — Import ✅ delivered in v0.3

- [x] Import PDFs and images (buttons, drag-and-drop, folders recursive)
- [x] Watched folders (scanned every 3 minutes)
- [x] Exact duplicate detection by SHA-256 (renamed copies too), shown per file
- [x] Page-by-page extraction for very large PDFs (background, resumable after closing the app)
- [x] OCR for scanned pages and images — RapidOCR, bundled, offline, CPU
- [x] Text from diagrams inside PDFs (OCR → labelled passage)
- [x] Passage chunking with file + page tracking; passage fingerprints
- [x] Import progress, remove file, retry failed
- [x] Instant exact-word search with highlights (bonus, ahead of Phase 4)
- [x] New blueprint design + side-rail navigation + Overview schematic
- [ ] Diagram descriptions by the vision model (needs benchmark → moved to Phase 2)
- [ ] Enter a PDF password inside the app (improvement)
- [ ] Open the original PDF at the cited page from a search result (Phase 4)

## Phase 2 — Distil ✅ delivered in v0.4
- [x] Embeddings for all passages (nomic-embed-text via Ollama; only new passages re-embedded)
- [x] Topic grouping by meaning (spherical k-means, restarts, merge of near-identical topics)
- [x] Repeat groups (same or ≥ 0.95-similar passages shown once with all sources)
- [x] Coverage check (100% assignment) + loose fits flagged for review
- [x] Topic connections (for the Knowledge Map)
- [x] Topic names + one-line summaries (fast AI model; keyword fallback)
- [x] Topics screen (build with live stages, results, colourful cards, topic detail)
- [x] Sage Vivid design across the whole app (owner's choice)
- [ ] Vector index for meaning-based search (Phase 4, with answer pages)
- [ ] Tune thresholds on the owner's real library after first run

## Phase 3 — Write the knowledge bank ✅ delivered in v0.5
- [x] One structured article per topic (Overview, Key points, How it works, Detection, Queries, MITRE, Response, Disagreements)
- [x] Citations on every statement → clickable source panel (file + page)
- [x] Big topics read in batches (up to 96 points)
- [x] Resumable overnight job with progress and Cancel
- [x] Articles carried over when topics are rebuilt
- [x] Readable structured source text (chunker v2 + Formatted display)
- [x] AI update checker (Ollama + models) with Update buttons
- [ ] Choose writing model from the benchmark report (setting `write_model`)
- [ ] "Rewrite all articles" button (engine supports it; UI later)
- [ ] Deeper conflict detection between sources (beyond the article's "Where sources disagree")

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
