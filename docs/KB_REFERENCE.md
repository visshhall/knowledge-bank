# KB — Knowledge Bank App
## Reference Document (Living Document)

| Field | Value |
|---|---|
| Project code | **KB** |
| Sister project | **SKT** — Sanatan Sanskrit Learning App (separate chat, separate repo, never mixed) |
| Current version | KB v0.8.0 — spreadsheets become calculated topics (charts, checks, Subnet Lab), animated walk-through diagrams, 3× faster live article writing with fact checks |
| Document version | 2.5 |
| Last updated | 15 November 2026 |
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
| Writing model | **qwen3.5:4b for everything** (decided 14 Nov 2026 by the owner's benchmark — see 9e) | Fastest and most faithful to the sources on his RTX 3050 4 GB; the 8B models were 2× slower without better accuracy |
| Embedding model | Local embedding model (chosen in Phase 0) | Powers meaning-based search and clustering |
| Vision model | Small local vision model (chosen in Phase 0) | Describes diagrams |
| Storage | SQLite with full-text search + a vector index (sqlite-vec or LanceDB, decided in Phase 0) | Single-file, fast, offline |
| Packaging | Windows .exe installer (NSIS via electron-builder) with a bundled private Python 3.12 | Owner installs by double-click; never installs Python or runs commands. In place since v0.2 |

## 9. Roadmap

| Phase | Name | What gets done | Status |
|---|---|---|---|
| 0 | Foundation | Finalise models and storage for RTX 3050 4 GB / 16 GB; set up Electron shell, Python engine, database; create private GitHub repo; Windows installer | **Delivered (v0.2 installer)** — model choice pending owner benchmark |
| 1 | Import | PDFs + images (+ Excel/CSV since v0.6), OCR, page-by-page large-file handling, watched folder, exact-duplicate removal | **Delivered (v0.3)** — plus instant exact-word search |
| 2 | Distil | Clustering, topic list, topic connections, coverage check | **Delivered (v0.4)** — plus Topics screen |
| 3 | Write the knowledge bank | Merged Knowledge Topic articles with source links and conflict flags (the long one-time overnight job) | **Delivered (v0.5)** |
| 4 | Interface | Knowledge Map home, topic pages, animations, hotkey search, generated answer pages | **Delivered (v0.6.3–v0.7)** — flow map, topic map, Ctrl+K meaning search, cited answer pages, open PDF at page |
| 5 | Learn mode | Flashcards, quizzes, scenarios, spaced repetition, progress | **Delivered (v0.6–v0.7)** — lessons + quiz, flashcards with spaced repetition, streak, progress by topic |
| 6 | Web assist + cyber tools | Web fallback, MITRE ATT&CK tagging, IOC extraction, KQL library | **Delivered (v0.7)** — IOC extractor, ATT&CK coverage, query library, browser look-ups |
| 7 | Updates + release | Incremental updates, encrypted backup, Windows .exe installer | **Delivered (v0.7)** — new files join existing topics automatically, encrypted backup/restore |

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

## 9d. v0.5 — readable text, written articles (Phase 3), AI updates: what and why

**Why this release:** after the owner's first real test (6 PDFs, 14 Nov 2026) the source points showed as one giant paragraph ("it will again become boring"). Two causes: (1) import flattened every line into one paragraph, destroying bullets, MITRE lists and KQL pipelines; (2) topics showed raw passages because Phase 3 (written articles) didn't exist yet. He also asked how he'd know whether the AI engine and models are old or new.

| Part | File(s) | What it does | Why it's built this way |
|---|---|---|---|
| Structure-keeping text (chunker v2) | `engine/kb_engine/chunking.py` | Keeps bullets, numbered items, headings and query pipelines on their own lines; splits inline bullets ("… • T1055 – …") and inline pipes ("Sysmon \| where … \| project …") back onto separate lines; only wrapped prose is joined | Readability. A table name followed by words ("Sysmon Event IDs:") is prose, not code — rule fixed during testing |
| Automatic re-organise | `importer.rechunk_all()` | When `CHUNKER_VERSION` changes, rebuilds every passage from stored page/picture text — no PDF is read again — then the owner rebuilds topics | Existing banks upgrade themselves; nothing to re-import |
| Formatted display | `app/src/Formatted.jsx` | Shows passages as headings, lists, code boxes (Copy button, KQL/SPL keywords coloured) and paragraphs; MITRE IDs (violet) and event IDs (yellow) as tags; long passages collapse with "Show more" | Built by hand, React elements only — no raw HTML ever injected, so text from PDFs or AI can never run as code |
| Article writer (Phase 3) | `engine/kb_engine/writer.py` | "Write articles" job: for each topic (largest first) the writing model turns its points into a page with sections Overview, Key points, How it works, Detection, Queries, MITRE ATT&CK, Response, Where sources disagree — leaving out unsupported sections. Every statement carries [n] markers; unknown markers are deleted, never trusted | Owner's core request: one clean page per subject, nothing missed, every line traceable. Big topics are read in batches of 12 points (up to 96, most central first) condensed to cited notes, then written up — so large topics aren't judged from only their first few points. Each article is saved as soon as it's done; Cancel stops after the current one; the next run continues where it left off |
| Article model | `writer.write_model()` | Uses the owner's saved choice (setting `write_model`, set after the benchmark) or the fast 4B model | Fits the RTX 3050's 4 GB; ~30–90 s per topic, so a big library is an overnight job |
| Articles survive rebuilds | `distill._save()` | When topics are rebuilt, a new topic sharing ≥ 60% of its passages with an old written topic inherits its article | Adding a few files doesn't throw away hours of writing |
| Citations | `topics.citations` (schema v4), `distill.topic_detail()` | Each [n] maps to a passage; shown as a clickable chip that opens the exact source text, file and page in a side panel | Every line can be checked in one click |
| AI update checker | `engine/kb_engine/updates.py`, `app/src/Updates.jsx` | "Check for updates" (Setup): Ollama installed vs latest GitHub release; each model's local fingerprint vs the fingerprint published in Ollama's model library; Update buttons (models re-download only changed parts; Ollama via its official installer) | Exact, not date-based: Ollama's local model ID is the SHA-256 of the published manifest (verified: qwen3:8b → 500a1f067a9f, nomic-embed-text → 0a109f422b47). Online only when the button is pressed; sends only model names, never documents. "Couldn't check" when a comparison isn't possible — never a false "update available" |

**Tested (v0.5):** on Linux — chunker v2 on real-world use-case text (MITRE lists, Event IDs, KQL pipelines), automatic re-organise of an existing bank, schema v3 → v4, article writing end-to-end (mock model) incl. removal of invalid citations, articles carried over after a topics rebuild, update check against the real Ollama model library, Topics screens (cards with "Article ready", article tab with coloured sections and steps, citation side panel, structured source points) screenshotted. On the Windows build under Wine — engine starts, upgrades a v0.4 bank to schema v4 and re-organises its text (chunker_version 2), search/write/update endpoints answer. **Not verifiable here:** article quality from the real 4B model on the owner's PDFs.

## 9e. Benchmark result and decisions (14 Nov 2026, v0.5.1)

Run on the owner's laptop (RTX 3050 Laptop 4 GB) with 6 of his own PDFs (281 pages):

| Model | Speed | Per article | Verdict |
|---|---|---|---|
| **qwen3.5:4b** | 11.6 tok/s | 86 s | **Chosen.** Accurate, well structured, kept MITRE IDs, event IDs and commands exactly |
| qwen3:8b | 5.9 tok/s | 162 s | Good, but 2× slower; once listed tool names as "commands" |
| llama3.1:8b | 6.2 tok/s | 160 s | Rejected: added facts not in the sources (e.g. an invented 10th method) |
| qwen3:4b | 8.5 tok/s | 126 s | Rejected: printed its private reasoning instead of the article |

**Decisions:** `DEEP_MODEL` = `FAST_MODEL` = qwen3.5:4b; required models are now only qwen3.5:4b + nomic-embed-text; Setup offers "Remove comparison models" (frees ~13 GB; required models can't be removed). Writer sized to keep the model fully on the GPU: 4,096-token window, 8 points × ≤800 characters per request, up to 1,300 tokens out (the benchmark's 700 cut some answers short), and an unclosed query block is closed automatically.

**Problem found: embedding at 1.2 passages/s** (too slow — a large library would take most of a day). Likely cause: the embedding model was placed on the CPU because a large model still occupied the GPU. Fix: before embedding and before writing, the app now unloads every other model and waits until Ollama confirms the memory is free (`ollama_client.clear_gpu_except`), and the Topics screen shows live speed and time left. **To verify on the owner's laptop:** the speed shown while "Reading meaning" — it should be tens to hundreds per second.

Also from the report: one PDF is fully scanned (42/42 pages) — handled by OCR (since v0.3).

## 9f. v0.6 — automatic visual lessons and spreadsheet import: what and why

**Why (owner's request, 14 Nov 2026):** after importing a subnetting spreadsheet, the owner asked that anything imported be "seen" by the app and explained simply — with a diagram, text, or both, chosen automatically — "without any mistake" and with "proper diagrams, not random". Owner approved the design ("go ahead").

**What was built:**
- **Spreadsheet import** (`importer.py`): `.xlsx`, `.xlsm`, `.csv` (up to 5,000 rows × 60 columns per sheet). Each sheet is stored twice: as the exact grid (`doc_tables`, schema v5) and as searchable text rows (cells joined with " · ", kept as structure by the chunker).
- **Lesson engine** (`lessons.py`), run for every topic right after its article (`writer.py`):
  1. *Profile* — what the material is (steps, comparisons, queries, numbers, tables).
  2. *Calculate, don't guess* — tables are shown as the real grid; number patterns (doubling/halving/powers of two) are found by code; subnet data gets a live CIDR calculator. These steps are marked "Calculated from your data".
  3. *Plan* — the AI picks from a fixed menu of visuals (flow, chain, stack, tree, compare, cards, query walkthrough) and fills in words only.
  4. *Verify* — every number, technique ID, IP/CIDR, event ID and query line must appear in the topic's sources; anything that doesn't is removed and counted. Numbers match whole (98 ≠ 980); single digits are checked with the word after them ("7 controls" must be in the sources; "3 steps" is fine).
- **Lesson view** (`Lesson.jsx`, `Diagrams.jsx`): first tab on a topic; step dots, Back/Next and arrow keys; source chips that open the exact source text; a quiz at the end; "Checked against your sources: N removed" (expandable); "Regenerate lesson".
- **Proper diagrams:** flows and trees are laid out by ELK (Eclipse Layout Kernel), a professional layout engine running offline inside the app — boxes never overlap, arrows are routed at right angles, wide flows are scaled (≥ 75%) or re-laid top-to-bottom to fit. Parts build up one by one like a teacher drawing; "reduce animations" shows them at once. The diagram code loads only when a lesson is opened.
- Schema v5 (`lessons`, `doc_tables`, `sources.file_type` adds `table`); a v4 bank upgrades in place (tested under Wine on the packaged build).

**Tested in Claude's workspace (mock AI that deliberately invents facts):** invented items (T9999, port 4444, 98765, a fake query line, "7 controls") removed; real facts kept; subnet sheet shown as real grid + patterns + calculator; regenerate works; screenshots of every step type.

**To verify on the owner's laptop:** lesson quality from qwen3.5:4b on real topics; time per topic (expected ~1 extra minute).

## 9g. v0.6.1 — fixes from the owner's real test (14 Nov 2026): what and why

Owner imported 6 PDFs (281 pages, 304 passages; 45 pages read by OCR) with v0.5.1 and reported three problems.

**1. Only 3 topics, one holding 298 of 304 points.**
- *Cause (reproduced):* the embedding model gives all text a strong shared direction. Any two cybersecurity passages scored about 0.69 cosine similarity, and topic centres (averages) scored about 0.9. The rule "merge topics whose centres are ≥ 0.88 alike" therefore merged almost everything. The same collapse happened on a 317-passage labelled test set: 3 topics of 310/6/1.
- *Fix (`distill.cluster`):*
  - Grouping uses centred vectors: the collection's average direction is subtracted, so unrelated text scores about 0.
  - The thresholds were re-measured in that space: merge 0.60, related-topic link 0.20, loose fit 0.25.
  - Oversized topics (more than 4× the average and over 60 points) are split.
  - Topics with 1–2 points are folded into the nearest topic.
  - Repeat detection still uses the original vectors.
- *Result:* the test set gives 13 topics of 11–39 points. A 72-passage end-to-end run with the real nomic-embed-text gives 6 topics of 7–17 points; the old code made 68 + 4 from the same passages.
- *Not chosen:* nomic's "clustering:" prefix. It gave no gain in the test, and it would have meant re-embedding everything.

**2. Source points "make no sense": "Step 3" / "Step 5" with no context, numbering restarting at 1, bullets glued together.**
- *Cause:* Word documents use nested bullets • → o → §. These extract as the letters "o" and "§", sometimes on a line of their own. Points were also listed by match score, which mixes steps from different documents. Numbered items were renumbered from 1.
- *Fix (chunker v3, schema v6):*
  - "o" and "§" (and Wingdings private-use bullets) become levels ◦ and ▪.
  - Wrapped bullet lines are re-joined. Ligatures are expanded ("oﬃcial" → "official").
  - Each passage stores its section, the document part it belongs to (a heading such as "Use Case 7: …", "Scenario …", "Chapter …" or an ALL-CAPS heading; otherwise the document's first heading).
- *Display:*
  - Source points are listed in reading order (file → page → position) by default, grouped under "file › section".
  - "Best match first" is still available.
  - Lists keep their real numbers and show nested indentation.
  - Every point has "Read in context" (GET `/passage/context`), which shows the passages just before and after it.
- *AI:* the writer and lesson prompts now prefix each point with "(From: section)".
- *Upgrade:* existing banks are re-organised automatically on first start. Topics must then be rebuilt once.

**3. Version not visible.** The installed version is now shown top-right on every screen and in the window title (IPC `app:version`).

Also fixed: a stray "0" on topic cards without a lesson (v0.6.0 rendering bug).

## 9h. v0.6.2 — reading polish from the owner's screenshot (14 Nov 2026)

| Problem seen | Cause | Fix |
|---|---|---|
| Sub-points looked like the letter "o" | v0.6.1 drew level-2 bullets as a hollow ring | Three distinct markers: dot (level 1), dash (level 2), small square (level 3) |
| "Step / Action" table became "1 Lock… 2 Block… 3 Notify…" on one line | Plain PDF text extraction reads tables cell by cell | `importer._page_text` uses PyMuPDF's table finder: each row becomes one line with cells joined by " · ", in its place on the page; the exact grid is saved to `doc_tables`, which lessons draw as tables. The app draws 2+ such rows as a real table. |
| Scanned log table: every cell on its own line, "WINRDPO1"/"SUCCESS" shown as headings | OCR boxes were written one per line | `ocr.assemble_rows` rebuilds rows from box positions (wide gap = new cell). A lower-case word after a word continues a sentence. |
| "192.168.1. 88", "2025-0728", "2025-07-2818:21" | OCR spacing errors | `ocr.fix_ocr_text` repairs IP addresses, squashed dates and glued date+time |
| "Containment and Response" not a heading | Lower-case "and" counted against it | Small joining words are ignored. Single tokens containing digits and list items are never headings. |
| A bullet "▪ VPN?" became a document section | ALL-CAPS short bullet passed the part-heading test | Covered by the same rule (list items are never headings) |
| Heading repeated under the file › section bar | — | The repeated first line is hidden |

**Upgrade:** `EXTRACT_VERSION` = 2. On first start, every PDF or image whose original file is still in place is re-read once, with progress shown in the Library. Files that have moved keep their stored text and are only re-organised. Topics must then be rebuilt.

## 9i. v0.6.3 — whole sections, borderless tables, Phase 4 start (14 Nov 2026)

**Owner feedback on v0.6.1/0.6.2:**
1. A "Step / Action" table still ran together.
2. Parts of one solution appeared in different cards, and similar items repeated.
3. The Overview diagram looked unprofessional.
4. Start the pending work, with more animation and interaction.

**1. Borderless tables (chunker v5).** Word tables without ruled lines arrive as "Step", "Action", "1", "Terminate…", "2", "Delete…" on separate lines, and the table finder can't see them.
- `chunking._rebuild_numbered_rows` turns a run of consecutive row numbers (from 1, at least 2 rows) back into rows: "1 · Terminate…".
- The two short lines just above become the header.
- "1 Text" lines only count as a table when such a header is present, so ordinary numbered sentences aren't touched.

**2. Whole sections.**
- Passages now break at headings once they have at least 60 words, so sub-sections such as "Analyst Steps" stay together.
- In reading order, Source points shows one card per file + document part, with all of that part's points joined.
- "· · ·" marks text that belongs to another topic.
- "Read the whole section" (GET `/passage/section`) shows the complete part.
- Similar items that appear in several use cases are kept, because they belong to different use cases, but each now sits under its own use-case header. True repeats are still shown once ("Also said in …").

**3. Overview flow map (`FlowMap.jsx`).** It replaces `Schematic.jsx` (deleted).
- A flow diagram from files to topics: bar height = passages, ribbon width = passages from that file in that topic.
- Hover traces a file, topic or ribbon and fades the rest, with a plain-language note.
- Clicking a topic opens it. It is keyboard accessible.
- Ribbons sweep in once and a quiet stream of dots flows along them. The "reduce animations" setting is respected.
- Beyond 24 files or topics, the rest are folded into one bar.
- Totals count up once on first show.
- Data comes from GET `/overview/flow`.

**4. Ctrl+K quick search (`QuickSearch.jsx`, `meaning.py`).** This is the Phase 4 "hotkey search" and "vector index".
- The question is embedded with nomic-embed-text ("search_query:" prefix) and compared with every passage vector (cached in memory). The result is blended with FTS5 word search, so a hit found both ways ranks first.
- If the AI engine is off, word search alone is used and the box says so.
- Each result shows its topic, section, file and page, and how it matched.
- Enter opens the topic at that exact passage, highlighted (Source points tab).
- Tested with the real embedding model: "how to stop a hacked RDP account" finds the RDP use case although no word matches; "4625" finds the exact log row.

## 9j. v0.7.0 — every remaining planned phase (14 Nov 2026)

Owner: "Go ahead with all pending tasks now." Tested with the REAL models in Claude's workspace (qwen3.5:4b + nomic-embed-text running on CPU through a private Ollama), not only the mock.

**Phase 4 — Interface**
- *Answer pages* (`answers.py`, `Answers.jsx`; schema v7 `answers`).
  - Ctrl+K "Write an answer…" or the Answers screen. The best 8 passages (meaning + words) are numbered, and qwen3.5:4b answers using only those, citing each sentence.
  - Every sentence is fact-checked (lessons.Checker) and unsupported ones are removed. If the sources don't cover the question, it says so.
  - Answers are saved for instant reopening.
  - Real test: "How should I contain an RDP brute force that ended in a successful login?" got a correct, cited answer in 73 s on CPU (faster on the owner's GPU), with nothing needing removal.
- *Open the original at the cited page.* Every source chip (`SourceChip.jsx`) opens the PDF in a locked-down viewer window at that page (`main.cjs` "file:open"; the path comes from the engine's database, never from the page).
- *Topic map* (`TopicMap.jsx`, d3-force). Topics form a living network, sized by passages and joined to related topics. Hover traces, drag rearranges, click opens. Each topic always keeps its 2 nearest neighbours, so broad libraries aren't islands.

**Phase 5 — Learn mode** (`learn.py`, `Learn.jsx`; `cards`, `card_reviews`)
- Flashcards come from the fact-checked lessons: quiz questions become multiple-choice cards and lesson steps become concept cards.
- Simplified SM-2 scheduling: Again / Hard / Good / Easy, with the next interval shown on each button.
- Up to 15 new cards a day. Cards flip in 3D and keys 1–4 / Space work.
- The screen shows streak, 14-day activity, and mastery per topic (interval ≥ 21 days) with Practise.
- Card identity is a hash of its content, so progress survives rebuilds.

**Lesson quality fix found with the real model.** qwen3.5:4b once marked a distractor ("Wipe the disk") as a quiz's correct answer. `lessons._check_answer` now compares the marked answer with the question's own source passage: a well-supported answer is kept, a clearly better-supported option replaces it, otherwise the question is dropped. The real re-run produced 4/4 correct quiz answers.

**Phase 6 — Analyst tools** (`tools.py`, `Tools.jsx`)
- *IOC extractor:* IPs, domains, URLs, emails, hashes, CVEs and ATT&CK IDs. Defanged input is understood, output can be defanged or live, private IPs are marked, and "System.Management"-style code isn't mistaken for a domain. There is also a bank-wide view showing where each indicator appears.
- *MITRE ATT&CK coverage:* names and tactics come from MITRE's own data, bundled offline (867 IDs including retired ones, so older documents' IDs such as T1574.002 are named). There is a tactic strip, plus topics and pages per technique.
- *Query library:* every KQL/SPL query in the documents, de-duplicated, filterable, copyable.
- *Web assist:* opens the normal browser for DuckDuckGo / VirusTotal / NVD / attack.mitre.org with only the clicked value. URLs are built in `main.cjs` from a fixed list; nothing is automatic.

**Phase 7 — Updates + backup**
- *Incremental updates* (`distill.start_update`). New files' passages join the nearest existing topic in the same centred space, repeat groups included.
  - Changed topics are marked stale and their lesson is refreshed. Nothing else is rewritten, and names, articles and card progress stay.
  - This runs automatically after an import when topics exist; there is also an "Add new files to topics" button.
  - Test: a new PDF was added to the right topic in about 1 s.
- *Encrypted backup* (`backup.py`, `Backup.jsx` in Setup).
  - SQLite online snapshot → zlib → AES-256-GCM with a scrypt-derived key (N=2^15), streamed in 1 MB chunks. The password is never stored.
  - Restore decrypts, verifies, and checks integrity, then swaps the bank in at the next start, keeping the old bank aside.
  - Tested: wrong password and a tampered file are both rejected; a correct restore works.

**Also:** a "Rewrite all" button; password-protected PDFs open from the Library (the password is held in memory for that one file, never saved); lessons are carried over on rebuild even when the topic has no article yet.

**Not done (by design):** "deeper conflict detection" between sources stays a future idea. Comparing every claim pair needs a stronger model than fits a 4 GB GPU; articles already include "Where sources disagree".

## 9k. v0.8.0 — diagrams, writing speed, spreadsheets (15 Nov 2026)

Owner: diagrams, graphs and animations were "weak and ugly"; article writing was "very slow"; an uploaded subnet Excel file showed "no graph or map with any explanation at all".

**Spreadsheets become their own topics** (`datapages.py`; schema v8 `topics.kind`, `topics.checks_json`)
- *Why it was invisible:* spreadsheet passages relied on the AI grouping and writing, so a sheet of numbers either landed in an unrelated topic or waited for the writer.
- *Now:* every imported spreadsheet gets a **data topic** at import, calculated by code with no AI, so it appears in seconds. Its lesson contains:
  - a summary of the sheet;
  - charts of every numeric series (log scale when values span ≥1000×), with explained patterns (halving, doubling, powers of 2);
  - **"Checking your sheet"**: for subnet sheets, each CIDR's hosts (2^(32−n)) and mask are recalculated. On the test sheet, 32/32 and 8/8 matched;
  - **"Why /n means n network bits"**: a bits explainer;
  - **Subnet Lab**: type any IP, slide the prefix, and play the AND animation to get the network, broadcast, usable range and sibling subnets, with the owner's own sheet value shown alongside;
  - the original table;
  - a quiz built from the sheet.
- The article is written by code too (Overview / Key points / How it works).
- Spreadsheets are excluded from AI grouping and the writer. Data topics rebuild after "Rebuild topics", on removal of a file, and once at every engine start, so sheets imported before v0.8 appear automatically.

**Diagrams rewritten** (`Diagrams.jsx`)
- Flow diagrams use ELK layout with rounded orthogonal links, numbered cards with colour accents, and labelled edges.
- **Walk me through** works on every visual: it highlights each part in turn, dims the rest, and sends a moving "packet" along the active link, with an explanation line. Click any box to explain it.
- The timeline, layers, flip cards, comparison and query walk-through are all redesigned.
- A new interactive chart has hover values with ÷2/×2 ratios and a line-draw animation.
- The **Play lesson** button runs the whole lesson hands-free: each visual walks itself, then the lesson moves to the next step and stops at the quiz.
- *Lessons without pictures fixed.* The real model answered `"visual": null` for every step because the prompt's example showed null. The prompt now shows a filled visual and asks for most steps to have one; in the re-test, 3 of 4 steps had diagrams. `lessons._ensure_visuals` guarantees at least a "journey" chain (the lesson's own steps) and source-quote cards, built only from already-verified text.
- Articles now show the lesson's diagrams as figures under the best-matching section.

**Writing 3× faster** (`writer.py`, `ollama_client.py`)
- Up to 12 points go straight into the article prompt; note passes only run for bigger topics, with 12 points per pass and at most 3 passes. Articles are shorter (300–450 words) and capped at 950 tokens.
- The real CPU test went from 5 model calls to 3; the estimate is about 2–3 min per topic on the owner's GPU versus 8–10 before.
- **Live writing:** text streams from Ollama and appears in the article as it's written (Answers stream too).
- **Write this topic now** puts one topic at the front of the queue.

**Accuracy**
- Every article line is fact-checked against the topic's sources after writing (`_check_article`): unsupported IDs, numbers and query lines are removed, and the count is shown under the article.
- In the real test, 7 invented items were removed (4 ATT&CK IDs that are not in the sources, 3 query lines). Filler lines such as "N/A" and empty "Where sources disagree" sections are stripped.

**Also:** a crash guard shows "Reload the window" instead of a blank screen if a screen errors.

## 10. Known limits (stated upfront)

- **First distillation** of 100+ PDFs is a one-time background job taking several hours (likely overnight) on the RTX 3050. New files afterwards take minutes.
- **Merged articles are AI-written.** Every line links to its source so it can be checked in one click.
- **Poor scans or handwriting** reduce OCR accuracy. Letter/number look-alikes (O/0, l/1, as in "WINRDPO1") can't be corrected automatically.
- **Password-protected PDFs** show "Enter password" in the Library; the password is used once and never saved.
- If an original file is **moved or deleted** before it is imported, that file fails with a message; once imported, its text stays in the bank regardless.
- **New files join existing topics automatically** (v0.7). A brand-new subject that fits no topic is only flagged as loose; "Rebuild topics" regroups everything when lots of new material arrives.
- A local 4–8B model writes well but is less capable than large cloud models; the source-link design compensates for this.
- **Lesson fact check** compares facts (numbers, IDs, IPs, code) against the sources; it cannot judge whether a plain-language sentence without such facts is a fair summary — the source chips on every step let you check.

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
| 14 Nov 2026 | Doc 1.7 / KB v0.4.1 | Owner's first benchmark run (v0.2) appeared stuck on model 1 of 4. Cause: no progress shown inside a model, plus settings too heavy for a 4 GB GPU (1,800-word excerpts, 8,192-token window, no answer-length cap → work spilled onto the CPU). Fix: live per-summary progress and elapsed time, Cancel button (POST /setup/benchmark/cancel), 1,200-word excerpts, 4,096-token window, 700-token answer cap, 6 PDFs by default. Tested with a slow mock: progress per summary, cancel, full run to report. |
| 14 Nov 2026 | Doc 1.8 / KB v0.5 | Owner found raw passages unreadable and asked about AI updates. Chunker v2 keeps structure + automatic re-organise of existing banks; Formatted.jsx display; Phase 3 article writer with citations, batching for big topics, carry-over on rebuild; schema v4; AI update checker (Ollama + model fingerprints). Added section 9d. |
| 14 Nov 2026 | Doc 1.9 / KB v0.5.1 | Benchmark received: qwen3.5:4b chosen for everything; comparison-model removal; writer sized for 4 GB (no cut-off answers); GPU cleared before embedding/writing to fix 1.2 passages/s embedding; live embedding speed + time left. Added section 9e. |
| 14 Nov 2026 | Doc 2.0 / KB v0.6.0 | Automatic visual lessons for every topic (profile → calculated steps → AI plan from a fixed visual menu → fact check), ELK-laid-out diagrams, quiz, regenerate; Excel/CSV import with exact grids; schema v5; stricter number checks. Added section 9f. |
| 14 Nov 2026 | Doc 2.1 / KB v0.6.1 | Owner test: 3 topics / 298 points in one → grouping on centred embeddings with re-measured thresholds, split/fold safety net. Unreadable source points → chunker v3 (Word bullet levels, ligatures, wrapped bullets), schema v6 passages.section, reading order + document-part headers + Read in context. Version shown top-right. Added section 9g. |
| 14 Nov 2026 | Doc 2.2 / KB v0.6.2 | Owner screenshot polish: PDF and scanned tables kept as tables, OCR row rebuilding + IP/date repair, distinct bullet markers, heading rule fixes, one-time re-read of original files (EXTRACT_VERSION 2). Added section 9h. |
| 14 Nov 2026 | Doc 2.3 / KB v0.6.3 | Borderless numbered tables rebuilt (chunker v5), heading-aligned passages, one card per document section + Read the whole section; Overview flow map (files → topics, hover/click, animated) replaces the schematic; Ctrl+K meaning + word search with jump-to-passage. Phase 4 started. Added section 9i. |
| 14 Nov 2026 | Doc 2.4 / KB v0.7.0 | All remaining phases: answer pages, open PDF at page, topic map (Phase 4); flashcards + spaced repetition + progress (Phase 5); IOC/ATT&CK/query tools + browser look-ups (Phase 6); automatic incremental topic updates + AES-256 encrypted backup/restore (Phase 7); Rewrite all; PDF passwords; quiz answer verification found with the real model. Schema v7. Added section 9j. |
| 15 Nov 2026 | Doc 2.5 / KB v0.8.0 | Owner: weak diagrams, slow writing, invisible subnet spreadsheet. Spreadsheet data topics (datapages.py: charts, recalculated checks, bits explainer, Subnet Lab, quiz; schema v8); diagrams rewritten with walk-through animation + Play lesson; lesson prompt fixed so steps get pictures + verified fallback visuals; writer 3 calls instead of 5, live streaming, Write this topic now, line-by-line article fact check; crash guard. Added section 9k. |
