# KB — Knowledge Bank App
## Reference Document (Living Document)

| Field | Value |
|---|---|
| Project code | **KB** |
| Sister project | **SKT** — Sanatan Sanskrit Learning App (separate chat, separate repo, never mixed) |
| Current version | KB v0.4 — Phase 2 (Topics) + Sage Vivid design, Windows installer; benchmark report still pending |
| Document version | 1.6 |
| Last updated | 14 November 2026 |
| Owner | Vishal Singh |

> **How to use this document in a new chat:** Upload this file (and KB_PENDING.md) at the start and say: *"This is the KB reference document. Read it fully and continue from the current phase."*

---

## 1. Why this project exists (origin)

- The owner works in cybersecurity (Microsoft Sentinel / SIEM work) and has collected **100+ PDFs** related to his job, with more arriving over time.
- Many of these PDFs contain **the same knowledge written in different words**. Reading them all is repetitive and boring, so in practice they don't get read.
- He wanted something that works **the way an AI learns**: gather from many sources, merge it, and present **one proper summary of everything**, without duplicates and without missing anything.
- The idea started on 14 November 2026 as "an offline second brain for my PDFs" and grew, through discussion, into a full **interactive, animated knowledge bank**.

## 2. What the app is (one paragraph)

An offline Windows desktop app that reads every PDF and image once, distils them into its own organised encyclopedia of **Knowledge Topics**, and lets the owner learn from that encyclopedia instead of the PDFs. It opens on an animated **Knowledge Map** of everything it knows, answers searches with **freshly generated summary pages** (not lists of PDFs), turns the material into **interactive learning** (flashcards, quizzes, scenarios), and can optionally consult the **internet** when the PDFs don't cover something.

## 3. Key design decision: distillation, not "training"

**Decision:** the app does NOT train/fine-tune an AI model on the PDFs. It **distils** them.

**Why:**
- Training a model on a laptop GPU (4 GB) is impractical.
- A trained model blends facts together and **cannot show where an answer came from** — dangerous for security work, where accuracy matters.
- A trained model must be retrained every time new PDFs arrive.

**What distillation means here:** read every page → group everything said about the same subject → write one clean merged article per topic → link every line back to its source PDF and page. This gives the "trained" feel the owner wants, while staying accurate, verifiable and instantly updatable.

## 4. Guiding principles (non-negotiable)

1. **Originals are never deleted or modified.** The knowledge bank is a layer on top of them.
2. **No duplicates, nothing missed.** Duplicates are merged; a coverage check proves every passage is represented.
3. **Every claim is traceable.** Every line in a topic page links to its source PDF and page.
4. **Conflicts are shown, never hidden.** If sources disagree, both versions are displayed.
5. **Offline-first and private.** Document content never leaves the laptop. Web search (optional) sends only the search words.
6. **Never boring.** Interactive and animated, not a PDF reader.
7. **Large files must never cause problems.** Processing is page-by-page in the background.

## 5. Owner's hardware and data (confirmed 14 Nov 2026)

| Item | Value | Implication |
|---|---|---|
| GPU | **NVIDIA GeForce RTX 3050 Laptop, 4 GB VRAM** (confirmed by the app's own system check on 14 Nov 2026; originally believed to be an RTX 3060 6 GB) | ~4B models (≈3.4 GB) just fit on the GPU. 8B models (~5–6 GB) do NOT fit and will run largely from system RAM — much slower, usable only for the overnight writing job if the benchmark shows the quality gain is worth it |
| RAM | 16 GB (15.7 GB usable) | Sufficient; carries the part of an 8B model that doesn't fit in video memory |
| Free disk | ~184 GB free (after install) | Ample (models + knowledge bank need ~20–30 GB) |
| Data volume | ~5–6 GB of PDFs (individual files mostly KB-sized), 100+ files and growing | Very manageable |
| Scanned PDFs | Only 2–3 | OCR needed for these, plus images |
| Processing time tolerance | Owner is fine with a few hours for the first build | First full distillation can run overnight |
| GitHub | Account `visshhall`, private repo `knowledge-bank` | Single home for all code and documents |

## 6. Features

### 6.1 Home — Knowledge Map
- Animated, interactive map of all topics and how they connect (e.g. Threat Detection → KQL → Sign-in Logs → Event 4625)
- Bigger topics glow brighter; click to zoom in
- Dashboard: number of sources, topics and concepts, coverage %, recently added
- With no search typed, this screen explains what the bank knows and manages

### 6.2 Topic pages (replace reading PDFs)
- One merged article per topic: overview, key concepts, step-by-step workflows, KQL/query examples, common mistakes
- Animated diagrams (e.g. an attack chain playing step by step, log flow through Sentinel)
- "Sources" drawer: which PDFs contributed; original page opens only on request
- Conflict flags where sources disagree

### 6.3 Search → generated answer page
- Global hotkey (e.g. Ctrl+Space) opens search from anywhere, even when the app is minimised
- Exact-word search + meaning-based search + natural-language questions
- Result is a freshly generated summary page built from all relevant material, not a list of PDFs

### 6.4 Learn mode
- Flashcards, quizzes, scenario questions ("You see 50 failed logins — what next?")
- Spaced repetition (review timed so knowledge sticks)
- Progress and streaks

### 6.5 Web assist (optional, toggle)
- When the PDFs don't cover something, the app searches the internet
- Web content is clearly labelled as web-sourced, kept separate from PDF knowledge
- Only search words are sent; PDF content never leaves the laptop

### 6.6 Cybersecurity tools
- MITRE ATT&CK technique tagging
- IOC extraction (IPs, hashes, domains)
- KQL / Sentinel query library
- Interview flashcards generated from the owner's own documents

### 6.7 Images
- Standalone images and images inside PDFs are processed
- OCR reads text from screenshots and scans
- A local vision model describes diagrams so they are searchable

## 7. How the engine works (pipeline)

1. **Import** — PDFs/images added manually or via a watched folder; exact duplicate files detected by content hash.
2. **Extract** — text read page by page (never loading a whole file); OCR for scans and images; diagrams described by a vision model.
3. **Chunk** — text split into passages, each remembering its source file and page.
4. **Index** — exact-word index + meaning (vector) index, for instant search.
5. **Cluster** — passages saying the same thing in different words are grouped.
6. **Synthesise** — the local AI writes one merged Knowledge Topic per group, with source links on every line and conflict flags.
7. **Verify coverage** — every passage must belong to a topic; leftovers are flagged for review.
8. **Incremental update** — new files only update the topics they affect.

## 8. Technical architecture (provisional — finalised in Phase 0)

| Layer | Choice | Why |
|---|---|---|
| App shell | Electron + React | Windows desktop app; same approach the owner chose for LumenSutra; supports global hotkey and rich animation |
| Engine | Python (runs alongside the app) | Best ecosystem for PDF processing, OCR and local AI |
| PDF reading | PyMuPDF (candidate) | Fast, page-by-page, handles large files |
| OCR | **RapidOCR** (onnxruntime, CPU) — decided in v0.3 | Installs as a normal Python package inside the app (Tesseract would need a separate Windows install); models ship inside it, so fully offline; runs on the CPU so it never competes with the AI models for the 4 GB graphics card |
| Local AI runtime | Ollama | Runs AI models on the RTX 3050 |
| Writing model | Two-model strategy, decided by benchmark in Phase 0: a ~4B model (e.g. Qwen 3.5 4B) for fast interactive answers, and possibly an ~8B model (e.g. Qwen3 8B) for the overnight topic-writing job only if its quality gain justifies running mostly from RAM | The RTX 3050's 4 GB fits ~4B models only; 8B would be slow and is used only where speed doesn't matter |
| Embedding model | Local embedding model (chosen in Phase 0) | Powers meaning-based search and clustering |
| Vision model | Small local vision model (chosen in Phase 0) | Describes diagrams |
| Storage | SQLite with full-text search + a vector index (sqlite-vec or LanceDB, decided in Phase 0) | Single-file, fast, offline |
| Packaging | Windows .exe installer (NSIS via electron-builder) with a bundled private Python 3.12 | Owner installs by double-click; never installs Python or runs commands. In place since v0.2 |

## 9. Roadmap

| Phase | Name | What gets done | Status |
|---|---|---|---|
| 0 | Foundation | Finalise models and storage for RTX 3050 4 GB / 16 GB; set up Electron shell, Python engine, database; create private GitHub repo; Windows installer | **Delivered (v0.2 installer)** — model choice pending owner benchmark |
| 1 | Import | PDFs + images, OCR, page-by-page large-file handling, watched folder, exact-duplicate removal | **Delivered (v0.3)** — plus instant exact-word search |
| 2 | Distil | Clustering, topic list, topic connections, coverage check | **Delivered (v0.4)** — plus Topics screen |
| 3 | Write the knowledge bank | Merged Knowledge Topic articles with source links and conflict flags (the long one-time overnight job) | Not started |
| 4 | Interface | Knowledge Map home, topic pages, animations, hotkey search, generated answer pages | Not started |
| 5 | Learn mode | Flashcards, quizzes, scenarios, spaced repetition, progress | Not started |
| 6 | Web assist + cyber tools | Web fallback, MITRE ATT&CK tagging, IOC extraction, KQL library | Not started |
| 7 | Updates + release | Incremental updates, encrypted backup, Windows .exe installer | Not started |

## 9a. What was built in Phase 0 (v0.1) and why

| Part | File(s) | What it does | Why it's built this way |
|---|---|---|---|
| Engine config | `engine/kb_engine/config.py` | All paths, port and model names in one place | Swapping a model after the benchmark is a one-line change; every value can be overridden by an environment variable without touching code |
| Database | `engine/kb_engine/db.py` | Creates/upgrades the SQLite file: sources → pages → passages → topics, plus full-text index, map links, conflicts, jobs | One file, no server, instant word search (FTS5). Triggers keep the search index in sync automatically. Numbered migrations let future versions upgrade the database without losing data |
| Coverage design | `topic_passages` table | Records which passages fed which topic | Makes "nothing missed" provable: any passage without a row is uncovered |
| System check | `engine/kb_engine/system_check.py` | Checks Python, FTS5, GPU, RAM, disk, Ollama, models, with exact fixes | Most local-AI problems are setup problems; this makes them visible |
| AI client | `engine/kb_engine/ollama_client.py` | Generate text, embeddings, list/unload models | Single point of contact with the AI runtime — easy to change later |
| Engine server | `engine/kb_engine/server.py` | Private server on 127.0.0.1:8765 (`/health`, `/system`, `/stats`) | Keeps heavy work out of the window; per-launch secret token blocks other programs/web pages from querying it |
| Benchmark | `engine/kb_engine/benchmark.py` | Tests each candidate model on the owner's own PDFs: speed, video memory, output quality; also PDF read speed, scanned pages, embedding speed | Model choice is the biggest factor in speed and quality; published benchmarks don't use this laptop or these documents |
| App shell | `app/electron/main.cjs`, `preload.cjs` | Starts/stops the engine, creates a locked-down window, relays only allow-listed requests | Security: the page can't reach Node, the engine token, or the network; one app instance only |
| Interface | `app/src/App.jsx`, `Constellation.jsx`, `styles.css` | Status + readiness dashboard over an animated constellation | Proves every layer connects. (Replaced in v0.3 by the blueprint design and Schematic — see 9b.) |
| Build security | `app/vite.config.js` | Adds a Content-Security-Policy to built pages | Page may not load outside scripts or contact any address |
| Setup wizard | `engine/kb_engine/setup_manager.py`, `app/src/SetupWizard.jsx` | In-app buttons with live progress: install/start Ollama, download models, run benchmark on a chosen folder, open the report folder | Owner requirement (v0.2): a normal Windows app — no PowerShell or commands, ever |
| Installer | `tools/build-windows.sh`, `app/package.json` ("build"), `app/build/after-pack.cjs`, `app/build/icon.*` | Bundles the app, the engine and a private Windows Python 3.12 (with all libraries) into `KnowledgeBank-Setup-<ver>.exe`; per-user install (no admin), Desktop + Start-menu shortcuts, custom icon and version details | The owner double-clicks one file. Built on Linux: Python libraries are fetched as ready-made Windows builds, icon/version are set with the pure-JS "resedit" library, Wine is used only by electron-builder to generate the uninstaller |

**Where data lives:** `%LOCALAPPDATA%\KnowledgeBank` (database + reports) — outside the code folder, so updates never touch data, and it is excluded from Git.

**v0.2 change — why:** v0.1 asked the owner to run PowerShell scripts. The owner rejected that: the deliverable must be a normal Windows `.exe` with everything inside the app. v0.2 removed the scripts, added the in-app setup wizard and the installer.

**Known installer behaviour:** the installer is not code-signed (a certificate is a paid annual service), so Windows SmartScreen shows "Windows protected your PC" on first run → *More info → Run anyway*. Ollama itself is installed by its own official installer, opened by the app, because it is a separate program that other apps can also use and that updates itself.

**Tested before delivery (in Claude's Linux workspace):** database create/upgrade/cascade-delete and full-text sync; server rejects requests without the token (HTTP 401); benchmark end-to-end against a mock AI service with generated PDFs (including scanned-page detection); the Electron app launched, showed "Engine ready" with live readiness data, and stopped the engine cleanly on close; v0.2 additionally: the installer was built, then installed silently under Wine (Windows compatibility layer) — files, Desktop and Start-menu shortcuts created; the installed app started its bundled Windows Python engine (answered on its port and rejected untokened requests); the bundled engine, run on its own under Wine, passed health/stats/system checks, the model-download job (with progress) and a full benchmark run against a mock AI service; the setup wizard was rendered and screenshotted in the Linux build. **Not testable there:** the real GPU, real Ollama and models, the app window on real Windows — verified by the owner's run.

## 9b. Phase 1 — Import (v0.3) and the new design: what and why

| Part | File(s) | What it does | Why it's built this way |
|---|---|---|---|
| Importer | `engine/kb_engine/importer.py` | Adds files/folders (recursive), fingerprints each file (SHA-256), skips exact copies, extracts every pending file in the background, watches folders, removes files, retries failures | Fingerprinting the bytes catches renamed copies. One page per database transaction means closing the app mid-import loses at most one page; half-done files restart cleanly on next launch. Originals are only read — never moved, changed or copied |
| Page handling | `importer.py` | Text layer first; pages with almost no text (scans) are rendered at 200 dpi and OCR'd; meaningful pictures inside pages (≥160 px) are OCR'd too and their text becomes a labelled passage ("[Image on page N] …") | Diagrams and screenshots carry real knowledge (queries, labels). Tiny pictures (logos, bullets) are skipped. A picture already read anywhere is never OCR'd twice |
| OCR | `engine/kb_engine/ocr.py` | Reads text from images, line by line in reading order; drops low-confidence noise | See OCR row in section 8. If OCR ever fails, the rest of the file still imports and the Library shows a clear message |
| Passages | `engine/kb_engine/chunking.py` | Cleans page text and cuts it into ~120–260-word passages that never cross a page; fingerprints each passage | Passages are what get searched, merged and cited — one page each, so every citation points to an exact page. Passage fingerprints catch the same paragraph copied into several PDFs (Phase 2 catches same meaning in different words) |
| Search | `engine/kb_engine/search.py` | Instant exact-word search across every passage, best matches first, matched words highlighted, file + page shown | Useful from day one, before AI topic pages exist. Each typed word is quoted so IDs like 4625, T1110.001 or SigninLogs never break the search |
| Database v2 | `db.py` | Adds `settings` (watched folders) and `duplicate_files` (what was skipped and why) | Owner sees what was skipped; watched-folder scans don't re-fingerprint known files |
| Library screen | `app/src/Library.jsx` | Drag-and-drop or buttons to add; live progress (file, page x of y, files left); search; watched folders; file table with status, pages, passages, scanned pages, pictures, copies skipped; remove; retry | Everything about import visible in one place |
| Navigation | `app/src/App.jsx` | Side rail: Overview, Library, Setup | Screens grow per phase (Map, Learn later) |
| Overview | `app/src/Overview.jsx`, `Schematic.jsx` | A blueprint-style drawing of files → passages → topics built from live totals (unbuilt parts drawn dashed), key numbers, and the one most useful next step | Owner requirement: with nothing searched, the bank explains what it holds and where it stands |

**New design (v0.3) — why it changed:** the owner asked for a look distinct from his LumenSutra intelligence dashboard (dark navy, glowing cyan dots). The app is now an *engineer's blueprint*: ultramarine paper with a faint drafting grid, white line-work, frames with corner tick marks instead of cards and shadows, amber as the single action colour, Bricolage Grotesque for headings (personality) and Atkinson Hyperlegible for text (built for legibility — clear 0/O and 1/l/I, important for IDs and queries). One deliberate animation: the Overview schematic draws itself once on opening. Fonts are bundled, so everything works offline.

**Tested (v0.3):** on Linux — full import of text PDFs, a scanned PDF, standalone image, embedded diagram (OCR'd into a labelled passage), exact-copy skipping, password-protected PDF message, resume after an interrupted import, search incl. prefix and odd characters, all three screens screenshotted. On the Windows build under Wine — import of a 40-page PDF, duplicate skip, password message, search. **Not verifiable under Wine:** OCR at runtime (Wine lacks a maths function the OCR libraries use; real Windows has it) — the OCR libraries do load on the Windows Python, and an OCR failure can no longer stop a file importing.

## 9c. Phase 2 — Topics (v0.4) and the Sage Vivid design: what and why

| Part | File(s) | What it does | Why it's built this way |
|---|---|---|---|
| Distil job | `engine/kb_engine/distill.py` | "Build topics": (1) embeds passages without a meaning-vector (only new ones on later runs), (2) groups passages by meaning into topics, (3) joins repeating passages into one "point", (4) links related topics, (5) names each topic | The core of "no duplicates, nothing missed". Results replace old draft topics in one transaction at the end, so the screen never shows a half-built state; any error leaves existing topics untouched |
| Grouping | `distill.py` (`_kmeans`, `_best_kmeans`, `_merge_similar`) | Spherical k-means on unit vectors (cosine similarity), k ≈ √(passages ÷ 2) (max 400), k-means++ seeding, 4 restarts keeping the tightest result, then topics whose centres are ≥ 0.88 similar are merged | Fast with numpy alone (≈10 s per run for 60,000 passages on a laptop CPU), no extra libraries, repeatable (fixed seeds). Restarts were added after testing showed a single unlucky start can mix subjects |
| Repeats | `_repeat_groups` | Inside each topic: same fingerprint, or ≥ 0.95 similarity → one point. Stored as `passages.cluster_id` = the first passage of the group | Shows each piece of knowledge once while keeping every file + page that said it. Comparing only inside a topic keeps it fast |
| Coverage | `topic_passages.fit` (schema v3) | Every passage is assigned to exactly one topic (coverage 100%). Its similarity to the topic centre is stored; below 0.45 it's a "loose fit" shown for review | "Nothing missed" is provable: no passage is ever dropped; doubtful placements are flagged, not hidden |
| Names | `_ai_name`, `_keyword_title` | The fast model (qwen3.5:4b) reads the 6 most central points and returns a 2–6 word title + one-sentence summary. Without the model, a keyword title (TF-IDF) is used | The job never stalls if the AI isn't ready; names improve automatically once it is |
| Topics screen | `app/src/Topics.jsx` | Build/rebuild button with five live stages, run results (topics, repeats merged, loose fits, coverage), colourful topic cards, topic detail with each point once, its sources as chips, loose fits flagged, related topics as jump buttons | Lets the owner check the grouping before Phase 3 writes the merged articles |
| Resilience | `distill.py` `_load_numpy()` | numpy loads only when topics are built | If it ever failed on a machine, only "Build topics" would report it — import and search keep working |

**Sage Vivid design (v0.4) — why:** the owner found the v0.3 blue blueprint look ugly and asked to see options first. Six directions were shown on a design canvas; he chose "Sage Study", asked for more colour, and picked the bold variant. Result: soft sage page (#E2E8DF), white-ish cards, forest green (#2C5A43) as the main action colour, and four bold accents — teal #23705F, coral #F08A68, violet #6A4BA8, mustard #E8B840 — each screen owning one (Overview forest, Library coral, Topics violet, Setup mustard) and topic cards cycling through them. DM Sans for the interface, Literata (a book typeface) for reading points and snippets. Inline SVG icons (`app/src/icons.jsx`), no icon fonts — offline and crisp. All text/background pairs chosen for WCAG AA contrast; keyboard focus visible; reduced-motion respected.

**Tested (v0.4):** on Linux — topics built end-to-end from 6 PDFs (24 passages): embedding, grouping, 16 repeats merged, loose fit flagged, AI naming via a mock model, topic list and detail; grouping verified to separate three subjects perfectly with restarts; 60,000-passage scale test (~10 s per k-means run); all four screens screenshotted in the new design; database upgrade v2 → v3 on an existing bank. On the Windows build under Wine — engine starts, upgrades a v0.3 database to v3, serves stats/topics/status. **Not verifiable under Wine:** building topics and OCR (both need numpy maths that Wine lacks; real Windows has it). Real embedding quality is checked on the owner's laptop.

## 10. Known limits (stated upfront)

- **First distillation** of 100+ PDFs is a one-time background job taking several hours (likely overnight) on the RTX 3050. New files afterwards take minutes.
- **Merged articles are AI-written.** Every line links to its source so it can be checked in one click.
- **Poor scans or handwriting** reduce OCR accuracy.
- **Password-protected PDFs** are listed as failed with a clear message; remove the password and add them again (entering a password inside the app is a planned improvement).
- If an original file is **moved or deleted** before it is imported, that file fails with a message; once imported, its text stays in the bank regardless.
- **Topics are rebuilt as a whole** each time "Build topics" runs (embeddings are reused, so it's quick). Automatic per-file topic updates come with Phase 7.
- A local 4–8B model writes well but is less capable than large cloud models; the source-link design compensates for this.

## 11. How we work on this project

- **This chat is the KB chat.** Code name in messages: **KB**.
- **Private GitHub repo** `visshhall/knowledge-bank`. Every version saved there.
- **Delivery format (owner requirement):** every release is a Windows installer `.exe`. The owner never runs PowerShell, scripts or commands; any setup step must be a button inside the app.
- Two living documents in the repo: **KB_REFERENCE.md** (this file) and **KB_PENDING.md** (task tracker). Both updated after every change.
- If an idea for the Sanskrit app comes up here, prefix it **"SKT idea:"** — it is logged for SKT, and no SKT code is touched from the KB chat.
- Untagged, ambiguous requests → Claude asks which project before changing anything.
- When a chat gets long, Claude updates this document and the work continues in a fresh chat.

### Session routine
1. Read KB_REFERENCE.md and KB_PENDING.md
2. Confirm what this session will do
3. Build and test (real execution tests, not just syntax checks)
4. Update both documents, bump the version
5. Save to the KB repo

## 12. Code commenting standard (mandatory, every file)

- **File header** — what this file is, why it exists, what it connects to (which files call it / which it calls), and when it runs.
- **Every function / component** — what it does, how it does it, why it is needed, when it is called, who calls it, what it calls, inputs, outputs, and side effects.
- **Inline comments** — on any line whose purpose or reasoning is not obvious.
- **Standalone code** is explicitly marked as "not connected to other modules."
- Comments are updated whenever the code changes; outdated comments count as bugs.
- Every code file is delivered complete — nothing missing, no "rest unchanged" placeholders.

## 13. Future goals

- A single place where all of the owner's cybersecurity knowledge lives, merged, current and enjoyable to learn from
- Grows automatically as new PDFs arrive
- Supports interview preparation and day-to-day job work
- Further goals to be added as they are decided

## 14. Change log

| Date | Version | Change |
|---|---|---|
| 14 Nov 2026 | Doc 1.0 | Initial reference document created from the planning discussion. Hardware confirmed. No code yet. |
| 14 Nov 2026 | Doc 1.1 | Corrected model sizing: 8B models are tight on 6 GB VRAM (not "comfortable"). Adopted two-model strategy (~4B interactive, ~8B overnight), final choice by Phase 0 benchmark. |
| 14 Nov 2026 | Doc 1.2 / KB v0.1 | Phase 0 foundation built and tested: engine (config, database schema v1, system check, Ollama client, secure local server, benchmark), Electron + React shell with status screen, Windows setup scripts. Added section 9a. |
| 14 Nov 2026 | Doc 1.3 / KB v0.2 | Owner rejected PowerShell setup. Replaced it with an in-app setup wizard (Ollama install/start, model downloads with progress, benchmark with folder picker) and a Windows installer bundling a private Python. Removed setup/*.ps1. Added tools/build-windows.sh. Fixed model-name matching (`name` vs `name:latest`). |
| 14 Nov 2026 | Doc 1.4 | Owner's first real run: app installed and works on Windows. System check revealed the GPU is an RTX 3050 Laptop 4 GB (not RTX 3060 6 GB) — hardware table and model strategy corrected. Fixed: readiness list now refreshes automatically when Ollama starts (fix ships in next installer). |
| 14 Nov 2026 | Doc 1.5 / KB v0.3 | Phase 1 Import delivered (importer, OCR via RapidOCR, passages, watched folders, duplicate tracking, instant search, Library screen); new blueprint design replacing the LumenSutra-like look; side-rail navigation; Overview schematic; database schema v2; OCR made non-fatal. Added section 9b. |
| 14 Nov 2026 | Doc 1.6 / KB v0.4 | Phase 2 Topics delivered (distill.py: embeddings, spherical k-means with restarts, repeat groups, coverage + loose fits, topic links, AI/keyword naming; Topics screen). Owner-chosen Sage Vivid design replaces the blueprint look (DM Sans + Literata, four bold accents, icons). Schema v3 (topic_passages.fit). numpy loaded lazily. Added section 9c. |
