# KB — Pending Work Tracker

Living document. Updated after every change. Companion to [KB_REFERENCE.md](KB_REFERENCE.md).

**Current version:** v0.9.0 (eleven improvements; v0.8.3 same content never added twice; v0.8.2 relevance filter, removed files stay removed, graphics-card tuning; v0.8.1 faster import; v0.8.0 diagrams, writing speed, spreadsheet topics — in owner testing)
**Last updated:** 15 November 2026

---

## Waiting on the owner (blocks Phase 1 model decisions)

- [x] GitHub access granted — code is pushed to `visshhall/knowledge-bank`
- [x] Installed v0.2 — app runs on the owner's laptop (RTX 3050 4 GB, 16 GB RAM)
- [x] All AI models downloaded (14 Nov)
- [x] First real test with 6 PDFs (topics built) — feedback: text unreadable → fixed in v0.5
- [ ] Install `KnowledgeBank-Setup-0.9.0.exe` (future versions install themselves from Setup → App updates)
- [ ] (0.8.3) check files marked "Already in the bank" really are copies (Keep anyway if not, and tell Claude)
- [ ] (0.8.2 checks) open Library: unrelated files show "Not cybersecurity" — check none of your security PDFs was set aside (use Keep anyway if one was, and tell Claude its name)
- [ ] Setup → Graphics card → "Test and tune speed"; report the words/s and the "% on graphics card"
- [ ] Remove a file that sits in a watched folder; confirm it does not come back after 3+ minutes
- [ ] Import a few PDFs with v0.8.1+: Library should say "read on the graphics card" — report seconds per scanned page and whether it says "processor" instead
- [ ] Install `KnowledgeBank-Setup-0.8.1.exe` (was 0.8.0) — then open Topics: Subnet-Guide appears as a "Spreadsheet · calculated" topic within seconds (no rebuild needed); check charts, "Checking your sheet", Subnet Lab
- [ ] Press **Regenerate lesson** on a couple of topics (lessons written before v0.8 often have no diagrams) and try **Play lesson** / **Walk me through**
- [ ] Time one topic with **Write this topic now** on the GPU and report the minutes (target 2–3)
- [ ] (was) Install `KnowledgeBank-Setup-0.7.0.exe` (keep the original PDFs where they are: the app re-reads them once on first start; watch Library until all are "In the bank")
- [ ] Topics → Rebuild topics (expect roughly 10–14 topics for the 6 PDFs, none holding most of the points)
- [ ] Source points → check reading order, document-part headers and "Read in context"
- [ ] Import Subnet-Guide.xlsx in Library, Rebuild topics, then "Write remaining" (writes lessons too) — check the lesson for that topic
- [ ] Report lesson quality: wrong diagrams, missing facts, or too many items removed
- [ ] Setup → Remove comparison models (frees ~13 GB)
- [ ] While topics build, note the "passages/s" speed shown and tell Claude (checks the embedding fix) (data and models are kept) — after model downloads finish
- [ ] Topics → Rebuild topics (needed once after v0.5's text re-organise), then Write articles
- [ ] Read a few articles; report anything wrong (missing facts, wrong citations, bad sections)
- [ ] Setup → AI updates → Check for updates
- [ ] Add PDFs in Library and check: scanned pages show a count in the Scanned column (confirms OCR works on Windows)
- [ ] Open the app → confirm "Engine ready" and the Setup panel
- [ ] Setup step 1: Install AI engine · step 2: Download AI models · step 3: run the benchmark on a folder of 5–10 PDFs
- [x] Benchmark report sent (14 Nov) → qwen3.5:4b chosen

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
- [x] Final model choice — qwen3.5:4b (benchmark 14 Nov)

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
- [x] Enter a PDF password inside the app (v0.7)
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
- [x] Writing model chosen from the benchmark: qwen3.5:4b
- [x] "Rewrite all" button (v0.7)
- [ ] Deeper conflict detection between sources (beyond the article's "Where sources disagree")

## v0.7.0 — All remaining phases ✅ delivered
- [x] Answers, topic map, open PDF at page, Learn mode, Tools, incremental updates, backup, PDF passwords, Rewrite all
- [ ] Owner checks: real answer speed on the GPU, flashcard flow, backup to a USB drive and a test restore

## v0.6.3 — Whole sections + Phase 4 start ✅ delivered
- [x] Borderless numbered tables rebuilt; heading-aligned passages
- [x] One card per document section; Read the whole section
- [x] Overview flow map; count-up totals; Ctrl+K meaning search

## v0.6.2 — Reading polish ✅ delivered
- [x] PDF tables and scanned tables shown as real tables (+ saved for lessons)
- [x] OCR row rebuilding, IP/date repair
- [x] Distinct bullet markers; heading rule fixes
- [ ] Owner check on the 45 scanned pages after re-read

## v0.9.2 — Remove files completely ✅ delivered
- [x] Remove one or many files; their topics, articles, lessons, flashcards and saved answers go with them
- [x] Library tick boxes, "Select all shown", "Select the N set aside", one confirmation
- [ ] Owner check: tick the unusable PDFs, remove them, open Topics and confirm none of their text remains

## v0.9.1 — Repeated statements folded ✅ delivered
- [x] Sentence-level merge across a topic's points (rules for clear cases, AI judge for borderline pairs, answers saved)
- [x] Topic screen, article writer and lessons use the merged points; citations follow absorbed points
- [x] Articles with repeats rewritten once by "Write remaining"
- [ ] Owner check: open a topic that used to repeat, press "Write remaining", compare the new article, and report any statement wrongly merged or still repeated

## v0.9.0 — Eleven chosen improvements ✅ delivered
- [x] Weak articles rewritten automatically (one stricter retry, better version kept)
- [x] App updates itself (Downloads/Desktop installer or GitHub release; verified; silent install + reopen)
- [x] More file types: Word, PowerPoint, web pages, text, Markdown
- [x] Better search: filters, phrase/heading ranking, close matches, file/topic chips, rank fusion in Ctrl+K
- [x] Big libraries: 1,000-file test, float16 meaning cache (980 → 190 MB), SQLite tuning, Storage card + Clean up
- [x] Edit topics by hand: rename, merge, move points, split into a new topic
- [x] Replace old versions automatically
- [x] Clean junk pages and lines (one-time clean of existing banks without renumbering)
- [x] Real names for files
- [x] Garbled text re-read by OCR
- [x] Automatic categories + Library filters
- [ ] Owner: publish GitHub release v0.9.0 (attach KnowledgeBank-Setup-0.9.0.exe; notes line `sha256: d89909008acec35cc2a3401649975b940693e9d6695345521382d364eef5ccb6`) — Claude's session can't create releases
- [ ] Owner checks: Library titles/categories look right; one hand edit; an update via Setup → App updates
- [ ] Idea: store meaning-vectors as float16 on disk too (halves the bank size; needs a format marker)

## v0.8.3 — Same content never added twice ✅ delivered
- [x] Paragraphs already in another file are not added again (fingerprint match; short lines kept)
- [x] Files with (almost) nothing new set aside as "Already in the bank" + Keep anyway
- [x] Scans compared on their 3 sample pages before full OCR
- [x] One-time check of the existing bank; Library switch
- [ ] Idea: near-duplicate detection for scan vs. text versions of the same document (needs fuzzy matching)

## v0.8.2 — Relevance, removed files, graphics card ✅ delivered
- [x] Removed files remembered (schema v10 removed_files); watched folders and folder adds skip them
- [x] Relevance check (relevance.py) before slow work; set aside + reason + Keep anyway + Library switch
- [x] One-time relevance check of the existing bank (stale/empty topics handled)
- [x] gpu.py: Ollama memory savers, speed tuning (forced layers only if measured faster), Graphics card card
- [ ] Owner: real words/s on the RTX 3050 after tuning (target 30+)

## v0.8.1 — Faster import ✅ delivered
- [x] Two-pass import: files searchable first, pictures inside them read afterwards (schema v9)
- [x] OCR engine pool; scanned pages OCR'd in parallel (79 s → 30 s to searchable on 2 cores)
- [x] DirectML graphics-card OCR on Windows with automatic processor fallback
- [ ] Owner timing on the RTX 3050 (DirectML can't be tested in Claude's workspace)

## v0.8.0 — Diagrams, speed, spreadsheets ✅ delivered
- [x] Spreadsheet data topics at import (datapages.py, schema v8): charts, recalculated CIDR checks, bits explainer, Subnet Lab, quiz, code-written article; rebuilt at engine start
- [x] Diagrams rewritten: walk-through animation on every visual, moving packet on links, click to explain, Play lesson autoplay
- [x] Lesson prompt fix + verified fallback visuals (journey chain, source cards) so lessons are never text-only
- [x] Lesson diagrams shown as figures in articles
- [x] Writer: 3 model calls instead of 5, shorter tighter articles, live streaming (articles + answers), Write this topic now
- [x] Article line-by-line fact check with removed count; filler stripping
- [x] Crash guard instead of blank screen
- [ ] Next: polish the Overview flow map and Topic map to the new diagram style (owner feedback first)
- [ ] Next: more calculated data pages (port tables, dated logs → timelines)

## v0.6.1 — Fixes from owner's real test ✅ delivered
- [x] Topic grouping on centred embeddings (no more one giant topic)
- [x] Word bullet levels (o / §), ligatures, wrapped bullets; passage sections (schema v6)
- [x] Source points in reading order with document-part headers + Read in context
- [x] Version shown top-right and in the title bar
- [ ] Confirm topic count/sizes on the owner's library after rebuild

## v0.6 — Automatic visual lessons ✅ delivered
- [x] Excel/CSV import with exact grids (schema v5)
- [x] Lesson engine: profile, calculated steps (tables, patterns, CIDR calculator), AI plan from fixed visual menu, fact check
- [x] Lesson view: steps, ELK-laid-out diagrams, source chips, quiz, check note, regenerate
- [ ] Owner check on real topics (see top)
- [ ] More calculated visuals when new data types appear (e.g. port tables, timelines from dated logs)

## Phase 4 — Interface ✅ delivered (v0.6.3–v0.7.0)
- [x] Overview flow map: files → topics, hover to trace, click to open, animated
- [x] Ctrl+K quick search: meaning (vector) + words, jump to exact passage
- [x] Topic pages with lesson / article / source points (v0.5–v0.6)
- [x] Animated topic map (d3-force network)
- [x] Answer pages: cited, fact-checked answers from the best passages (saved)
- [x] Open the original PDF at the cited page (viewer window)

## Phase 5 — Learn mode ✅ delivered (v0.7.0)
- [x] Per-topic quiz (v0.6, inside the lesson) + answer verification (v0.7)
- [x] Flashcards with spaced repetition (SM-2), streak, activity, progress by topic
- [ ] Idea: scenario drills ("an alert fires — what do you do first?") built from use-case sections

## Phase 6 — Web assist + cyber tools ✅ delivered (v0.7.0)
- [x] Optional web look-ups in the browser (only the clicked value is sent)
- [x] ATT&CK coverage (offline names/tactics), IOC extraction (defang/refang), KQL/SPL query library

## Phase 7 — Updates + release ✅ delivered (v0.7.0)
- [x] Incremental updates: new files join existing topics automatically
- [x] Encrypted backup + restore (AES-256-GCM, scrypt)
- [x] Windows .exe installer (since v0.2)

## Ideas parking lot
_(Ideas tagged "KB idea:" from any chat land here until scheduled.)_
