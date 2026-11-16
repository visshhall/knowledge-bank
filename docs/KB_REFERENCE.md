# KB — Knowledge Bank App
## Reference Document (Living Document)

| Field | Value |
|---|---|
| Project code | **KB** |
| Sister project | **SKT** — Sanatan Sanskrit Learning App (separate chat, separate repo, never mixed) |
| Current version | KB v0.17.0 — learns from its mistakes: logs bad answers, finds patterns (counting + AI), turns them into lessons it follows, checks they helped and switches off those that did not; v0.16.0 — the app learns by itself: web learning (finds and reads pages on topics, adds them straight to the library, within a daily budget) and learning from use (thumbs, Copy, Regenerate, Correct → training examples → dataset export); v0.15.0 — the app is chat-first: it opens on a new chat, with a ChatGPT/Claude-style sidebar, attach files / add a web page from the message box, Regenerate and Edit; v0.14.0 — memory about you: short facts you control, used by Free chat; v0.13.0 — read a web address (page, section or whole site) and paste text into the bank; v0.12.0 — Free Chat and personas: a three-way switch (My files / Files + general / Free chat) and editable personas; v0.11.0 — Chat: saved, multi-turn conversations with your library (cited, fact-checked, general knowledge only on request), model picker with a compare-on-my-files test; v0.10.0 — the AI works out what each point is for; v0.9.2 — removing files removes everything built from them; v0.9.1 — repeated statements folded; v0.9.0 — cleaner imports, search, self-updating app |
| Document version | 3.6 |
| Last updated | 16 November 2026 |
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

## 9l. v0.8.1 — faster import (15 Nov 2026)

Owner: "the Library import is too slow."

**Measured first.** On an 85-page test PDF, text pages take about 20 ms each. Almost all of the time goes to OCR: scanned pages took about 3 s each, and pictures inside pages take 1–3 s each.

**1. Files are usable first, pictures come after** (schema v9 `images.xref`)
- Pictures inside text pages are no longer read during the file's pass. They are saved as "waiting" with their place in the PDF.
- After every file's text is in, a second pass reads them and adds their text to the same page (`importer._picture_step`).
- A newly added file always jumps ahead of waiting pictures. Waiting pictures survive closing the app.
- Library shows "Reading files" and then "Reading pictures", plus "N to read" per file.

**2. Several pictures at once** (`ocr.py` pool)
- One engine using all threads was replaced by 1–3 engines with about 2 cores each.
- Scanned pages of a PDF are OCR'd side by side while the next pages are read, and are still stored in page order.
- On a 2-core test machine: the same PDF went from 79 s to 30 s until searchable (44 s including pictures), with identical passages. More cores give more gain.

**3. Graphics card OCR on Windows**
- The Windows bundle uses `onnxruntime-directml`, so OCR can run on any graphics card.
- If DirectML is missing or fails, OCR switches to the processor for the session; importing never stops.
- Library says which one is in use. *Not testable in Claude's workspace (no Windows GPU); the owner's timing confirms it.*

**4. Smaller changes**
- The OCR engine loads in the background as soon as there is something to import.
- Text-only PDFs never start the OCR engines.

**Kept for accuracy:** the 180° text-line classifier. Turning it off was about 10% faster but changed the text read.

## 9m. v0.8.2 — relevance filter, removed files, graphics card (15 Nov 2026)

The owner raised three issues:
- "PDFs not related to cybersecurity should be removed automatically."
- "Make sure all of this runs on the GPU, not the CPU — it's very slow."
- "Files I remove keep coming back."

**Removed files stay removed** (schema v10 `removed_files`)
- *Cause:* the watched-folder scan runs every 3 minutes and re-imported anything not in the bank, including files the owner had just removed.
- *Fix:* removing a file now records it, along with its copies (by fingerprint, path and size).
  - Watched folders and folder adds skip removed files, including renamed copies.
  - Picking that exact file again with Add files brings it back.
  - Library says "N you removed before (skipped)".

**Non-cybersecurity files are set aside** (`relevance.py`; `sources.status` 'set_aside', `relevance_json`, `keep_anyway`)
- The check uses a fixed vocabulary (no AI, instant, the same answer every time).
  - About 150 "strong" terms that only security writing uses (malware, SIEM, KQL, lateral movement…).
  - Patterns: CVE, ATT&CK IDs, event IDs, IPs, hashes, query pipes.
  - About 165 "weak" terms that other writing also uses.
- Verdicts:
  - "cyber" = 3+ strong terms, or 2 strong + 5 weak.
  - "not" = no strong term (or one strong term in 500+ words) in 150+ words.
  - Anything else is "unsure", and is **kept**.
- The check runs on a sample **before** the slow work: the text layer of the first 25 pages, or OCR of at most 3 pages spread through a scan. An unrelated 200-page scan therefore costs 3 pages of OCR.
- Set-aside files keep only their row: they are never re-imported, Library shows the reason, and **Keep anyway** imports them in full. A Library switch, "Only keep cybersecurity files" (on by default), turns the check off for new files.
- Banks imported earlier are checked once from their stored text. Topics that lose passages are marked stale, and empty topics are removed.
- Tested:
  - All 9 cyber PDFs and the subnet sheet in the test bank were judged "cyber", and a 45-word file was "unsure" and kept.
  - 23 unrelated documents (font manuals, licences, technical tables) were judged "not", and 2 very short ones were "unsure".
  - A 12-page scanned manual was set aside after OCR of only 3 pages.

**AI kept on the graphics card** (`gpu.py`, `ollama_client.py`, `GpuCard.jsx`)
- *Evidence:* the owner's benchmark showed 11.6 tokens/s writing and 1.2 passages/s embedding. Those are processor-like speeds; a 4B model fully on an RTX 3050 runs at roughly 30–50 tokens/s.
- On a 4 GB card the writing model (≈3.5 GB loaded) only just fits, so Ollama often leaves part of it on the processor.
- Fixes:
  - **Memory savers:** Ollama's flash attention and 8-bit attention cache roughly halve attention memory. They are set once as Windows user variables (so Ollama's own tray app uses them too), Ollama is restarted when idle, and they are always passed when the app starts Ollama.
  - **Speed tuning:** the first time a model writes, and from Setup → "Test and tune speed", the app measures Ollama's own split against all layers forced onto the card, and keeps forcing only if it is ≥15% faster. On Windows the driver can spill a forced model into shared memory, which is slower, so it is never forced blindly. If a forced request fails, the next try uses Ollama's own split.
  - **Setup → Graphics card card:** the card and the memory in use; each loaded model's share on the card ("72% on graphics card" in orange when partial); measured words/s and passages/s; and advice (driver missing, close video/games).
- Topic grouping and fact checks are plain arithmetic taking seconds, so they stay on the processor. Picture reading uses the card through DirectML (v0.8.1).
- *Not measurable in Claude's workspace (no NVIDIA card); the mechanics were tested against the real Ollama.*

## 9n. v0.8.3 — content already in the bank is not added again (15 Nov 2026)

The owner asked whether two different PDFs with the same content can be skipped. He wants content added "only if not present, otherwise nothing".

**What already existed:**
- Exact copies (same bytes, by SHA-256) were skipped at import.
- Repeated paragraphs were merged when topics were built.

**What was missing:** a different file with the same content (a re-export, a second download, a new cover page) was read and listed in full.

**Now** (`importer.py`; Library switch "Skip content already in the bank", on by default):
- *Paragraph level:* a passage whose fingerprint (same words, ignoring case, spacing and punctuation) is already in another file is not added. The page text is still stored, so Read in context shows the whole page. Short lines (under 8 words: headings, cover titles) are kept and don't count as new content.
- *File level:* a file whose paragraphs are almost all already in the bank (under 5% new) is set aside as **"Already in the bank — same content as X"**, with Keep anyway.
- A file that adds new sections, such as an updated version, is imported with only its new paragraphs. Library shows "N paragraphs already in the bank, not added again".
- *Scans:* the 3 sample pages read for the relevance check are compared with the bank, using identical page text or ≥80% known paragraphs. If they all match one file of the same length, the scan is set aside before the rest is OCR'd.
- *Pictures:* diagram text already in another file is not added again.
- *Existing banks* are checked once. Files whose paragraphs are almost all in an older file are set aside (the oldest copy stays), stale topics are marked, and empty topics are removed. Partial overlaps in existing files are left alone, because removing single paragraphs would break citations in written articles; topic building already merges them.

**Tested:**

| Case | Result |
|---|---|
| Re-exported copy with a new cover page | Set aside (17 of 17 paragraphs present) |
| Updated version (doc1 + doc2) | Imported with only its 14 new paragraphs |
| Same scan saved again | Set aside after OCR of 3 sample pages (15.8 s instead of ~40 s) |
| One-time check of an existing bank | Set aside 2 files: the re-export, and a file contained entirely in another |

**Limit:** "same content" means the same words. A scan and the original text PDF of the same document usually differ slightly in OCR'd words, so both are kept.

## 9o. v0.9.0 — eleven owner-chosen improvements (15 Nov 2026)

The owner picked these from three rounds of suggestions and said "go ahead".

**1. Clean junk pages and lines** (`cleaning.py`)
- Lines repeated at the top or bottom of most pages are found from the PDF's text layer before reading and removed from every page. These are headers, footers, watermarks and the author's name on every slide.
- Also removed: page labels ("Page 3 of 9", "3/9"; a bare number only at a page edge), and promo lines (follow / like / repost, linkedin.com/in/…).
- Whole pages that are blank, promotion, contents/index, or a title-only cover give no passages. Their text is still stored, so Read in context works.
- Banks imported earlier are cleaned once without renumbering passages, so citations stay valid:
  - pure-junk and gibberish passages are deleted;
  - junk lines inside passages are removed in place.
- Test, a LinkedIn-style carousel: header, footer and page numbers were gone from all 6 content slides; the cover and promo slide were skipped.

**2. Garbled text detection** (`cleaning.is_garbled`)
- A text layer counts as gibberish when it has many control or private-use characters, Latin-Extended look-alikes ("ĂŵĞƌŝĐĂ"), is mostly symbols, or has few word-like tokens. Such pages are OCR'd instead; the OCR text is kept only if it is better.
- No false positives on 143 real test pages (the only pages flagged were glyph tables in a font manual).
- Test: a page with an invisible gibberish layer was read correctly by OCR.

**3. Real names for files** (`titles.py`, schema v11 `sources.title`)
- Names like "1733744110377.pdf", "document (3).pdf" or "IMG_2041.png" get a title, taken from the first of these that works: the PDF's title field, the document's first heading, or a title-like first line.
- All-caps titles are turned readable ("Use Case 3: RDP Brute Force…").
- Titles show in Library, citations, search results and the flow map. The file on disk is untouched.

**4. Automatic categories** (`titles.categorise`, `sources.categories`)
- Up to 2 of 11 categories per file (SIEM & Detection, Endpoint, Identity & Access, Cloud, Network, Email & Phishing, Malware, Incident Response, Threat Intel & Hunting, Vulnerabilities & AppSec, Governance & Compliance), from vocabulary hits.
- Library shows chips and filters by category, status and name. Search filters by category too.

**5. More file types** (`officefiles.py`, file type 'doc'; schema rebuild via `_migrate_v10`)
- Supported: .docx, .pptx, .html/.htm, .txt, .md.
- Word: headings, bullets and tables kept; ~3,000-character pages.
- PowerPoint: one page per slide, with title, text, tables, speaker notes and pictures.
- Web pages: readable text only.
- Only the Python standard library is used (zipfile + ElementTree + html.parser), so nothing new is bundled.
- All the PDF steps apply: relevance check, junk cleaning, duplicate skipping, OCR of pictures.
- Test: the same content as .docx, .pptx, .html and .md was all read, and the copies were recognised as the same content.

**6. Replace old versions automatically** (`importer._replace_older`, `sources.replaced_by`)
- A file already in the bank counts as an older version of a new file when at least 60% of its paragraphs are in the new file (names alike, e.g. "Guide v1" / "Guide v2") or at least 85% (any names).
- The old file is set aside as "Older version — replaced by X". The new file is then read again in full, so it holds the content it skipped as duplicates.
- Keep anyway restores the old file.
- Test: doc1 followed by "doc1-updated" (doc1 + doc2): doc1 was replaced and the new file held all 31 paragraphs.

**7. Better search** (`search.py`, `meaning.py`, Library search panel)
- Filters: file, topic, kind of text (typed / scanned / picture), category.
- Ranking: BM25, with the exact phrase ×1.6 and a match in the section heading or file title ×1.25.
- If no passage has every word, close matches with some of the words are shown and labelled.
- File and topic chips show hit counts and filter with a click; results show the section and the topic.
- Ctrl+K blends meaning and word results by Reciprocal Rank Fusion.

**8. Edit topics by hand** (`topicedit.py`, Topics.jsx)
- Rename; merge another topic into this one; "Move or split points" (tick points, then move them to another topic or make a new topic).
- Only topic membership changes, so passages, citations and cards stay valid. Changed topics are marked for "Write remaining", and empty topics are removed.
- Spreadsheet topics can only be renamed. "Rebuild topics" replaces hand edits, and the screen says so.

**9. Weak articles rewritten automatically** (`writer.py` WEAK_*)
- When the fact check removes 4 or more items, 25% or more of the lines, or leaves under 500 characters, the article is written once more. The second request lists the unsupported items and must use only facts found in the sources.
- The better version is kept (the smaller share of removed lines, then the longer one). The article note says so.
- "Write remaining" also redoes earlier gutted articles that were never retried.

**10. Big libraries** (`storage.py`, `meaning._vectors`, db pragmas, Library)
- Measured on a synthetic 1,000-file / 100,000-passage bank:
  - Library 0.01 s, stats 0.01 s, word search 0.16 s.
  - Meaning-search memory went from ~980 MB to ~190 MB (float16 matrix filled straight from the cursor; similarities computed in blocks of 20,000 rows).
- SQLite: 64 MB cache, memory temp store, 256 MB memory-mapped reads.
- The Library list refreshes every 20 s when idle (4 s while importing) and draws 150 rows at a time.
- Setup → **Storage** card shows the bank size, what is inside, where the space goes, and how much a clean-up would free. **Clean up** removes leftovers, optimises the search index, VACUUMs, and deletes restore copies and reports older than 30 days (the newest restore copy is kept). It refuses while a job is running.

**11. App updates itself** (`electron/updater.cjs`, `AppUpdate.jsx`)
- Two sources:
  - a newer KnowledgeBank-Setup-x.y.z.exe in Downloads or on the Desktop (e.g. sent in chat);
  - the latest GitHub release of visshhall/knowledge-bank (the repository is public).
- The download is checked for size, the "MZ" header, and the SHA-256 published in the release notes.
- It installs silently (/S --force-run), and the app reopens by itself. Only an installer the updater found or downloaded can be run.
- A banner appears under the version badge. Setup → App updates has "Check for updates" and an automatic daily check (on by default; it sends nothing but the request).
- *Publishing:* Claude's sessions are not allowed to create GitHub releases, so a release is published by the owner: GitHub → Releases → "Draft a new release", tag `v<version>`, attach the installer, and paste the `sha256: …` line Claude gives into the notes. Until a release exists, the Downloads route works: download the installer Claude sends, and the app offers Install.

## 9p. v0.9.1 — repeated statements folded in topics (15 Nov 2026)

*Why:* the owner still saw the same data twice in a topic, even from one file, and asked for "logical reasoning" to catch it. Inspection of a built topic set showed the cause: repeat detection worked on whole passages (identical text, or ≥ 95 % similar meaning). The same sentences sit inside differently-cut passages and across files, so they were never grouped and the article repeated them.

*What (`engine/kb_engine/facts.py`):*
- Every point of a topic is split into statements (sentences, bullets, table lines; a fenced query block is one statement; headings and labels such as "USE CASE 13: …" are never compared).
- Automatic merges only for clear cases: identical text, the same words in another order, or one statement whose words are all inside the other with nothing negating. Statements naming different numbers/IDs (T1059.001 vs T1059.003, event 4624 vs 4625), queries that are not identical, and a single swapped word ("symmetrically"/"asymmetrically", "link"/"attachment") are never merged by rules.
- Any other overlap of 50 % or more is borderline: the local AI answers SAME / SUBSET / DIFFERENT / CONFLICT once; the answer is stored (table `fact_verdicts`, schema v12) and never asked again. A SAME/SUBSET answer is only trusted when the dropped statement adds at most a few words of its own (a 4B model can be too generous). With no answer yet, the pair stays unmerged — the safe side.
- The longer statement stays; the shorter one's file and page are added to the keeper's sources. A point left with no statements of its own is folded into the point that kept them, and article/lesson citations follow it.
- Nothing is deleted: passages are untouched; the merge is a view computed whenever a topic is opened or written (Topics screen, article writer, lessons all use the same function `facts.topic_points`).
- When the AI is asked: after "Build topics" / "Update topics", and at the start of "Write remaining" (up to 80 pairs per topic, 600 per run; the rest next time). Skipped silently if the AI isn't running.
- Existing articles: "Write remaining" rewrites once every written article whose topic really has repeats (marker `facts_v` in the article's checks); articles with nothing to fold are left alone.
- The topic header says how many repeated statements were folded in.

*Measured (7 test topics, 96 passages):* about 60 repeated statements folded, 11 % less text; every sample merge was checked by eye after two fixes (a one-word swap and a "local vs remote" case the model had accepted).

*Limits:* the check is wording-based plus a 4B model, so a repeat phrased very differently may remain; a rare wrong "same" is limited by the guard above. `python engine/tests/test_facts.py` covers the rules.

## 9q. v0.9.2 — removing a file removes everything built from it (15 Nov 2026)

*Why:* the owner saw unusable PDFs and their content still present. Remove already deleted a file's pages and passages, but topics, written articles, lessons, flashcards and saved answers made from it stayed behind, and there was no way to remove many files at once.

*What:*
- **Library → tick files → "Remove N selected"** (checkbox on every row, "Select all shown", "Select the N set aside"); one confirmation, then done. The single "Remove" on a row does the same for one file.
- On removal (`importer.remove_sources` → `_clean_up_after_removal`): topics left with no content are deleted; topics that lost part of their content have their article, summary, citations and lesson cleared and are marked stale (they no longer show the removed text; "Write remaining" writes them again from what is left); flashcards made from the removed text and saved answers that cited the file are deleted; a removed spreadsheet takes its data topic with it.
- Removed files are remembered (as before): watched folders and folder adds never bring them back; "Add files" on that exact file does.
- The same clean-up now applies when a file is set aside automatically (not cybersecurity, already in the bank, older version).
- Original files on disk are never touched. A file still being imported is skipped and reported.

*Measured (test library):* removing 2 of 9 files cleared 6 topics' articles, deleted 5 flashcards and 1 saved answer, left 0 dangling references.

## 9r. v0.10.0 — the AI works out what each point is for (15 Nov 2026)

*Why:* after v0.9.1 the owner said the reasoning was still weak: the AI should understand how things work and show data accordingly, not just merge statements. The article writer got a flat list of the most central points and a fixed template, so related facts landed in the wrong place and nothing explained how things connect.

*What (`engine/kb_engine/understand.py`):*
- For every point (after repeats are folded) the local AI decides its **role** — definition, how it works, step, detection, response, example, note (queries are recognised by rules) — and **what it is about** (1–4 words). Answers are stored by a hash of the point's text (table `point_roles`, schema v13), so each point is analysed once and the answer survives topic rebuilds and hand edits.
- The AI's labels are grouped into at most 6 subjects by rules (a word shared by several labels names the subject: "Proxy-based C2 communication" + "DNS-based C2 communication" → "C2"). A first attempt to let the 4B model do this grouping produced nonsense, so the model only labels and the grouping is deterministic.
- **Outline** (`structure()`): sections in teaching order — What it is → How it works → Steps, in order → How to detect it → Queries and commands → What to do about it → Examples → Other notes — points grouped by subject, steps kept in document order.
- **What the reasoning found:** statements the AI judge marked as CONTRADICTING each other (both shown), and sections the files never cover ("Your files don't say how to detect this"), and how many points are not analysed yet.
- **Topics screen:** a new default view "By meaning" shows the outline; "In reading order" and "Best match first" remain.
- **Articles** are written from the outline: every section gets a share of the points read directly (a big "how it works" group can no longer push out detection or response points), points are laid out under their section and subject headings, the prompt asks the writer to explain how things connect (what leads to what, how variants differ), and listed contradictions feed "Where sources disagree".
- When: roles are tagged after "Build/Update topics" and at the start of "Write remaining" (up to 600 points per run, the rest next time; skipped silently if the AI isn't running). Every article written before v0.10 is written once more by "Write remaining" (marker `logic_v` in its checks).

*Measured (test topic, 17 points, CPU only):* tagging took about 2.5 minutes (a graphics card is much faster); 17 subject labels were grouped into Exfiltration (7), C2 (4), Encryption (2) and Other (4). On that sample every point was a mechanism description, so only one section appeared; the "no detection / no response in your files" notes were correct for those documents.

*Limits:* a 4B model's role labels are a judgement, not proof — a point can sit in a neighbouring section; subjects are grouped by shared words, so unrelated labels using different words stay separate; the first run is slower because every point is analysed once. `python engine/tests/test_understand.py` covers the rules.

## 9s. v0.11.0 — Chat and the model picker (16 Nov 2026)

*Why:* the owner asked whether the Knowledge Bank itself could become the "ChatGPT-style" private app, because it already holds the enriched data of about 200 PDFs. It can: the bank already has the library, search, citations, the local engine and the installer, so only a conversation layer was missing. Choices made with the owner: answers come from the library first and from general knowledge only when asked; chats are saved and searchable; a model picker comes now.

*What — Chat (`engine/kb_engine/chat.py`, window `app/src/Chat.jsx`):*
- **Saved chats** (tables `chats`, `chat_messages`, schema v14): new, rename, delete (with a second click), search by title or by any message text. A new chat is named after its first question. Chats are inside the one database file, so backups include them.
- **Each question** is answered from the best passages of the bank (the same retrieval as Answers: meaning plus exact words, 6 passages), numbered [1]…[n] and cited. The same fact check as Answers (`answers.finalize`, now shared) removes any sentence whose number, technique ID, IP, event ID or command is not in the cited sources; the count and the removed sentences are shown.
- **Follow-ups work**: the last four messages travel with the question, and a short follow-up ("and on Linux?") borrows the words of the previous question when searching.
- **General knowledge is a switch under the message box, off by default, per message.** Off: if the files don't cover the question the reply says so (the model is not called). On: the model may add what it knows, but only in a separate box that begins "From general knowledge (not from your files):" — no source markers, not fact-checked, and the message is flagged `general` so the window labels it. If nothing in the files matches and the switch is on, the whole reply is marked that way.
- **Streaming and Stop**: the answer appears as it is written (the window polls `GET /chat/status` every 0.7 s); Stop ends it at once and keeps and checks what was written (`should_stop` in `ollama_client`).
- **Sources** under each answer open like in Answers: passage text, "Open page" (the original PDF at that page), "Open topic". Clicking a [n] chip opens and highlights that source.
- **Removing a file** now also clears every chat answer that quoted it (the conversation stays; the answer is replaced by a short note). While doing this I found and fixed a v0.9.2 bug: the clean-up read a saved answer's sources as a list, but they are stored as a numbered dictionary, so no saved *answer* was ever deleted when its file was removed. Fixed in `importer._cited_source_ids`; `test_chat.py` covers it.

*What — model picker (`engine/kb_engine/modelpick.py`, window `app/src/ModelCard.jsx` on Setup, model box in Chat):*
- Lists the installed models (size, last measured speed), marks the one Chat uses, and saves the owner's pick (setting `chat_model`; default is the article model). Articles and Answers keep their own model, so trying a model cannot disturb the library.
- Suggests other small models for a 4 GB card (Phi-4-mini, Gemma 3 4B, Llama 3.2 3B, Qwen 3.5 2B) with a **Download** button; nothing is downloaded unless it is pressed (this is the one step that needs the internet, through the Setup wizard's download job).
- **Compare on my files**: tick 2 or 3 installed models; the same questions (three made from the owner's biggest topics, or up to five typed by him) are asked of each with the same passages and exactly the prompt Chat uses. The table shows speed, seconds per answer, sources cited and sentences removed by the fact check; the answers are shown side by side. One model at a time is loaded and unloaded, as the 4 GB card requires.

*Privacy and security (unchanged):* everything runs on this laptop; the new engine routes sit behind the same per-launch token and the window's allowlist; no chat text is sent anywhere. Chat text is stored only in the local database.

*Tested:* `engine/tests/test_chat.py` (chats, search, citations, fact check, the general-knowledge switch, follow-up history, Stop, one reply at a time, removal clean-up) and `test_modelpick.py` (what can be selected, identical prompts in a comparison, cancel) with the AI replaced by stand-ins; both Chat and the model card were rendered in a headless browser with a stand-in engine; the real model was run once on a small test bank (see KB_PENDING).

*Limits:* a 4B model can still misread a follow-up; only the last four messages are remembered, so a long chat forgets its start; the general-knowledge part is not checked and can be wrong; fact checking only catches numbers, IDs and commands, not a wrong explanation; the model sizes shown for suggestions are approximate; a comparison on three questions says little about quality, so the answers must be read, not just the numbers.

## 9t. v0.12.0 — Free Chat and personas (16 Nov 2026)

*Why:* the owner wants the Knowledge Bank to become his own private AI app — not only a search over his job PDFs but a model he can talk to about anything (business copy, code, learning, planning), with no company filter on it. He chose to build this inside the Knowledge Bank rather than as a separate app, so the same installer, database, model picker and later training features serve both. Choices made with him: Free Chat first; a mode switch at the top of Chat rather than a separate screen; only mainstream models in the picker (no "uncensored" community models).

*What — three modes, saved per chat (`chats.mode`, schema v15):*
- **My files** — exactly v0.11: only his files, every sentence cited and fact-checked.
- **Files + general** — v0.11's "Also use general knowledge": files first, then a labelled, unchecked general part.
- **Free chat** — no files, no search, no fact check, no source markers. The model answers like any general AI chat. Each Free reply is labelled in the window "Free chat — written by the model, not from your files, not fact-checked", so it can never be mistaken for a sourced answer. More of the conversation is sent along than in the library modes (up to 12 earlier messages / 6,000 characters, newest first) because no passages compete for the 4,096-token window; replies may be up to 1,200 tokens; temperature 0.6 (0.2 in the library modes).
- The old `general` flag still works and means "Files + general", so nothing written for v0.11 breaks.

*What — personas (`engine/kb_engine/personas.py`, table `personas`):* a persona is a name plus the instructions the model follows in Free chat. Five are built in and read-only: **Assistant**, **Ākāra copywriter** (luxury tone, meta title ≤ 60, meta description ≤ 155, slug, headline, description, benefit bullets; uses only facts he gives it and asks for missing ones), **Coding helper**, **Tutor**, **Security analyst**. He can create, edit and delete his own (name up to 60 characters, instructions up to 4,000), or press "Copy and edit" on a built-in. Every persona also receives a short base rule: answer directly and completely without unrequested warnings or lectures, say plainly when unsure, never invent facts, numbers, quotes, links or sources. Built-ins are refreshed from the app on every start (so improved wording ships), his own are never touched. Deleting a persona makes the chats that used it fall back to the Assistant.

*What the app does and does not do about "no restrictions":* the app adds no filter of its own — everything stays on his laptop and nothing is logged anywhere. Any refusal or caution comes from the model itself. The model picker lists mainstream models only (Qwen, Phi, Gemma, Llama); it still accepts any Ollama model name typed by hand.

*Window (`app/src/Chat.jsx`):* the switch sits beside the Send button; in Free chat a Persona picker and "Edit personas" appear in the top bar. Opening a saved chat restores its mode and persona. A found-in-testing bug is recorded in Known limits below.

*Tested:* `engine/tests/test_free_chat.py` (built-in protection, persona rules, all three modes, no search and no passages in Free, persona text reaches the model, source markers stripped, longer Free history with a cap, library history unchanged, mode and persona remembered, deleted-persona fallback, empty reply explained, schema v15 on a v14 database run twice); existing `test_chat.py` and `test_modelpick.py` still pass. Rendered in a headless browser with a stand-in engine. One real-model run (qwen3.5:4b, CPU): the Ākāra copywriter persona produced a meta title, description and slug, and a follow-up ("make the description warmer and shorter") used the first answer.

*Limits:* a 4B model writes passable first drafts, not finished luxury copy — read and edit what it gives. In the real test it put a leading "/" in the URL slug and cannot know materials or sizes (it asked for them, as instructed). Free chat answers are the model's own words and can be wrong. Only recent messages are remembered. Free chat and article writing share the graphics card; do not run both at once. A UI bug found while testing: the "Copy and edit" button and the "Save persona" button were the same screen element, so one click copied *and* saved; they now have separate keys.

*Planned next (agreed order):* v0.13 add any kind of file or text to the bank (Word, text, web pages, images, spreadsheets, pasted text); v0.14 memory about the owner (durable facts he can see and edit); v0.15 training kit (rate answers, export a dataset from chats and files, a cloud-notebook recipe to fine-tune a small model, import it back).

## 9u. v0.13.0 — Add from the web and paste text (16 Nov 2026)

*Why:* the owner wants the bank to learn from anything, not only his PDFs, and asked for URLs: type an address and the app reads the page and "figures out all the data" from it, crawling the site. Most file types already worked (PDF, Word, PowerPoint, Excel/CSV, saved web pages, text, Markdown, images by OCR — see sections 4 and 9k), so the new parts are the web reader and pasted text.

*What — `engine/kb_engine/crawler.py`, window `app/src/WebAdd.jsx` (a card on Library):*
- **Three scopes:** this page only; this page and the pages under the same folder of the site ("section"); the whole site (also uses the site's sitemap.xml to find pages no link leads to). A page limit (default 1 / 30 / 100; at most 500) and a link depth (0 / 2 / 3; at most 5) bound every read.
- **What is saved:** each page, and each PDF / Word / Excel / PowerPoint / text file it links to, is copied into the data folder (`web/<site>/…`) and registered as a source with its address (`sources.url`, schema v16). It then goes through the same import as any file: cleaning, passages, search, topics, Chat. Text that repeats across pages (menus, footers, shared paragraphs) is stored once, by the existing "already in the bank" rule. The relevance check ("is it cybersecurity?") is skipped for these (as for pasted text): he asked for them himself; that check is for files dropped in bulk.
- **Citations:** opening a web source opens its address in his own browser, not the saved copy.
- **A page read twice** adds nothing; **a page that changed** becomes a new copy and the older version is replaced by the v0.9 "older version" rule. Removing a web source (or a pasted note) also deletes the app's own copy of it from the data folder; a file from his own disk is never deleted.
- **Paste text:** a box with an optional title; saved as a Markdown copy in `notes/` and imported. The same text twice is recognised.

*The rules the crawler always follows (fixed in code):* only http(s); addresses on this computer or a private network (127.x, 10.x, 172.16–31.x, 192.168.x, 169.254.x, localhost …) are refused, also after a redirect, so a read can never reach the app's own engine or his router; only the same site (www. and non-www. are one site); robots.txt respected for every page the crawler finds (a page he types himself is fetched, as a browser would; Crawl-delay honoured up to 10 s); one request at a time with at least a second between them; 20 s timeout; pages up to 5 MB, documents up to 40 MB; pages marked noindex skipped; tracking parameters and #fragments ignored; at most 5 variants (filters, sorting) of one path; login, cart, checkout and admin paths skipped; images, media, archives, scripts skipped; pages with under 200 characters of readable text skipped and counted. Stop keeps what was already read.

*Privacy:* this is the one place the app fetches content from the internet, and only when he presses Read; nothing about his files or chats is sent (only the page requests, with a plain user-agent "KnowledgeBank/version"). Reading a site means keeping a copy of its text: the window reminds him to read only sites he may copy for his own use.

*Tested:* `engine/tests/test_crawler.py` — a small test site served from this computer: single page, section, site with sitemap, depth and page limits, other site ignored, robots.txt, noindex, tracking parameters, query-variant cap, login/cart, empty page, linked text document, redirect, unchanged and changed page, Stop, one read at a time, unreachable site, private addresses refused, malformed addresses (javascript:, file://, bad port), pasted text, removal of own copies. Also an end-to-end run through the real import worker (two pages read, imported and found by search) and a headless-browser look at the card with a stand-in engine. No real website was read from this sandbox (no open internet here), so behaviour on real sites is checked only against the test site.

*Limits:* the crawler cannot run JavaScript, so a site that builds its pages in the browser (many single-page apps) comes back empty — it says so. Pages behind a login are not reachable. A site can block unknown readers; then the page is reported as not read. A big site needs several reads (500-page cap) and then the normal topic building, which takes time. Prices, stock and similar live data are a snapshot of the day it was read; read the page again to refresh it. HTML text extraction drops menus, headers, footers and side bars, so a site that puts its real content inside those tags loses it.

*Planned next:* v0.14 memory about the owner; v0.15 training kit (see section 9t).

## 9ae. v0.22.1 — Screens no longer freeze or go blank (16 Nov 2026)

**What / why:** Owner reported the screen "stopped loading after a few minutes".
- **Cause found:** v0.22.0 used the shared category colours in Live learning (Brain.jsx) without importing them, so that screen crashed as soon as it drew a dot, and the single app-wide crash guard replaced the whole window. Fixed (import added).
- **Crash guard per screen:** `CrashGuard.jsx` now wraps each screen separately (keyed by screen). A crash shows a short message with "Try again" in that screen only; the sidebar keeps working and moving to another screen clears it. The app-wide guard stays as a last resort.
- **Polling hardened (bridge.js usePoll):** no new request while the previous one for the same panel is still waiting (a slow engine can no longer build a queue); nothing is polled while the window is minimised/hidden, with an immediate refresh when shown again.
- **Timeout (main.cjs):** engine reads (GET) give up after 60 s instead of waiting forever; the screen keeps its last data and asks again next refresh.
**Checked:** 200-file synthetic library (6,000 pages, 768-d vectors): engine polled like the app for 4.5 min, every reply under 0.11 s; every screen left open in a browser with no errors and flat memory. Slowest call is Tools → bank IOCs (≈9 s on 200 files, only when opened).

## 9ad. v0.22.0 — Pictures on every main screen (16 Nov 2026)

**What:** The same picture-first treatment as Insights/Live learning, now on the screens used every day, each with a one-line text caption beside it.
- **Overview → "Your library at a glance":** donut of file kinds (and yours vs web pages), treemap of subjects, bars for the last 30 days (files added / web pages read), three rings (linked to related files, in topics, subjects well covered).
- **Library:** clickable treemap by subject and donut by status above the file list; clicking sets the existing filters, clicking again clears.
- **Topics:** "Biggest topics" bars (top 10 by passages).
- **Learning:** "Learning at a glance": today's pages vs the daily limit (ring), web pages per day (bars), topic queue (stacked bar), lessons working (donut), sites trusted/skipped/blocked (donut).
- Brain now uses the same stable category colours as every other screen (built-in categories have fixed colours).

**Why:** Owner wants pictures first because they are quicker to understand than text; text stays for anyone who prefers reading.
**How:** `engine/kb_engine/glance.py` (GET /glance/all: file kinds, categories, 30-day series, health percentages; no new tables, schema stays v22). UI: `app/src/viz.jsx` (Donut, Ring, Bars, StackBar, Treemap, Legend, catColor; plain SVG, no chart library, animates once, off with reduced motion) and `Glance.jsx` (LibraryGlance, LearningGlance, LibraryStrip, TopicSizes).
**When:** refreshes every 15 s on Overview/Learning; Library and Topics use the data already on screen.
**Connected to:** insights.py (daily series; replaced files are no longer counted), coverage.py, learner.py, mistakes.py, taxonomy.py.

## 9ac. v0.21.0 — Live learning: watch the app learn (16 Nov 2026)

*Why:* the owner asked for a real visual of the AI being trained: a new dot appearing when it finds something new, related to the data already there, correlated with incoming data, and "more and more visual presentation" with text kept only as a companion. Agreed choices: every file and web page is a dot; relations by the embedding model; this live view first, then a visual pass on the other screens.

*How (`brain.py`, schema v22: `source_vectors`, `source_links`, `brain_events`; `Brain.jsx`):*
1. **A meaning-vector per file or page:** the average of up to 4 passages spread through it, made by the same embedding model as "Build topics" (nomic-embed-text; the passage vectors are stored on the passages, so Build topics reuses them). If the model is not available (AI engine off, not downloaded, or an answer is being written) a shared-key-words vector is used so the screen still works, and it is upgraded to a meaning-vector later without being announced as new again.
2. **Links:** a new file is compared with all others after the direction every cybersecurity text shares is removed (otherwise everything looks about 0.7 alike) and joined to its closest matches, up to 4, if alike enough. Only files made by the same method are compared.
3. **Events:** each first appearance is logged with who it linked to and written in plain words ("Read a web page: ‘X’ relates closely to ‘Y’, ‘Z’").
4. **The screen** (Knowledge → Live learning): a canvas map. Dot = a file or page (colour = category, size = amount of text, dashed ring = read from the web). Lines = same subject (brighter and thicker = closer). A new dot pops in next to its closest relatives, a ripple spreads, and a bright pulse runs along each new line. Controls: All / My files / Read from the web, Pause live updates, **Replay growth** (the newest 40 dots disappear and come back one by one in the order they were learned), Link new files now. Click a dot to see, as text, which files it relates to and how closely; click a category to highlight it; drag to pan, scroll to zoom (the view keeps everything in sight until you do). The side panel has status, a text feed "What just happened", and the legend, so it reads without the picture too.
5. **Rhythm:** the engine links up to 8 new files every 15 s while no answer is being written; the screen refreshes every 4 s. No new picture appears for something that has no text yet.

*Limits:* shows up to 300 dots (newest first). Links are made when a file first appears and are not reworked when later files change the average direction. While old key-word dots are being upgraded, links between upgraded and not-yet-upgraded files are missing for a while. Reduced-motion settings turn off the ripples and pulses.

*Next (agreed):* the same visual treatment for Overview, Library, Topics and Learning.

*Tests:* `test_brain.py`.

## 9ab. v0.20.0 — Insights: the patterns, drawn and animated (16 Nov 2026)

*Why:* the owner asked for "visualization animations everything" so that the patterns the app finds can be seen, not only listed. This completes the agreed list from the v0.17 request.

*How (`insights.py`, no schema change; `Insights.jsx`):* a new **Insights** screen in the Knowledge section, fed by one read-only call (`GET /insights/all`, refreshed every 15 s). No chart library; plain SVG, so it works offline.
1. **Knowledge map.** One circle per category (size = files; green = well covered, amber = thin from the v0.18 score; dashed ring = added by the app). Lines join categories that share files. A small spring layout places them once; circles glide from the middle on opening. Click a circle for files, passages, learned pages, score and sub-categories.
2. **Coverage heatmap.** Categories down, the last 12 weeks across (rolling 7-day blocks, latest on the right). Switch: files *Added* or *Used in answers* (how often saved answers cited the category). Cells fade in row by row.
3. **Mistake trends.** Stacked bars per week by kind (thumbs-down, Regenerate, corrected by you, facts removed), a line for the share of that week's answers that went wrong, and diamonds on the weeks a lesson was added (grey when the lesson was switched off), so you can see whether lessons help.
4. **Timeline.** A 30-day strip (files added, web pages learned, mistakes) and a newest-first list of what the app did itself: pages read per topic, categories and sub-categories added, lessons learned, topics queued for gaps or unanswered questions, sites it stopped reading.

*Limits:* "Used" counts only answers saved with sources, so it fills in with use. The map is clearest with up to about 25 categories. Animations play once when data appears and are switched off when the computer asks for reduced motion. Nothing here changes any data.

*Tests:* `test_insights.py`.

## 9aa. v0.19.0 — Categories that grow from the data (16 Nov 2026)

*Why:* the owner: "categories need to be expanded automatically as per new data, not anything fixed". Until now a file got one of 11 built-in cybersecurity categories or none.

*How (`taxonomy.py`, schema v21: table `taxonomy`, column `sources.subcats`):*
1. **Tagging at import.** `importer._name_and_tag` calls `taxonomy.classify`: built-in list first (judged on the text as before); when none fits, the grown categories (2 of their words, or 1 in the title); then sub-categories of the chosen categories.
2. **New categories.** A background loop (every 5 min, idle when nothing to do) or "Find new categories now" takes files that fit nothing. First it tries the grown categories (so older files join categories created later). The rest go to the AI: it sees the existing category names plus up to 15 unplaced files (title and first lines) and proposes up to 3 new categories with their marker words; a category needs at least 2 files, a 3–40 character name, at least 3 marker words, and a name that is not the same as an existing one (then it extends that one instead). Without the AI (not running or busy) words shared by at least 3 files form a group named after the word, never a word that is in more than 60% of the files. At most 3 new per run, 40 grown categories in all.
3. **Sub-categories.** A category with 12 or more files is split into 2–6 sub-categories (AI names, or shared words as above); files are tagged "Parent / Child" and the Library shows them as small chips.
4. **Tidying.** Near-duplicate grown categories are merged; a grown category left with no files is removed.
5. **Control.** Learning → "Categories that grow": the tree with file counts, switch "Grows by itself", "Find new categories now"; for grown categories Rename / Merge into… / Delete. Built-in categories cannot be renamed or deleted but can be merged into. Coverage (v0.18) and the Library filter include grown categories automatically.

*Limits:* only files that fit no category are placed into grown ones, so a file already tagged with a built-in category keeps it. The AI's names can be odd; rename or merge them. Plain-mode names are single words or word pairs from the titles. Sub-categories are decided once per category (when it first reaches 12 files).

*Not built yet (agreed next):* v0.20 pattern and visualisation screens with animations (knowledge map, coverage heatmap, mistake trends, learning timeline).

*Tests:* `test_taxonomy.py`.

## 9z. v0.18.0 — Gaps, page usefulness and junk sites (16 Nov 2026)

*Why:* the owner wanted the app to find what it is missing and fetch it on its own, and to cope with junk data instead of only adding more. After "Go ahead" on the proposal, v0.18 adds measured quality per category and per web site.

*How (`coverage.py`, schema v20: `site_stats`):*
1. **Coverage per category.** For each category from `titles.py` it counts files, passages, learned pages, newest addition and how often answers cited it (60 days). Score 0–100 = files (50, full at 8) + depth (30, full at 300 passages) + freshness (20, fades after 30 days, gone by 150). Weak = score under 50, or cited 3+ times and under 70.
2. **Gaps become topics.** `plan_topics()` takes the weakest categories (max 2 per run, none again within 14 days), asks the AI for 2 specific search phrases from the titles already there (plain phrases if the AI is busy), and adds them as topics marked "fills a gap". The learner does this by itself when web learning is on, the "fills gaps itself" switch is on, and nothing else is waiting (checked at most every 12 hours). "Fill the gaps now" does it on demand and ignores the 14-day wait.
3. **Learned pages.** Each is *useful* (cited in an answer), *thin* (fewer than 3 passages or failed import) or *unused*. Thin uncited pages are removed automatically at the start of each web-learning round. "Remove unused pages (45+ days)" removes old pages no answer ever cited.
4. **Sites.** Per host: pages kept, useful, thin, removed by him. A site is **blocked** when it has given at least 4 pages, 60% or more thin or removed, and was never cited. Search results from blocked sites are skipped; the rest are ordered by site score (cited pages count 3, thin −2, removed by him −3). Removing a learned page by hand counts against its site; "Remove everything it learned" and the app's own clean-ups do not.
5. **His word wins.** Learning → "What it knows and what is missing" → Web sites: Block, Allow, "Let the app decide".

*Limits:* categories are still the fixed cybersecurity list in `titles.py`; pages outside it are not planned for. Usefulness needs real use (citations take days to appear), so early on most pages read "not used yet". A blocked site can be allowed again but its earlier thin pages stay counted.

*Connected to:* `db.py` (`_migrate_v20`), `learner.py` (maintain, plan_topics, rank_urls), `importer.py` (`remove_sources(feedback=)`), `server.py` (`/coverage/*`), `Learning.jsx`.

*Not built yet (agreed next):* v0.19 automatic categories and sub-categories; v0.20 pattern and visualisation screens with animations.

*Tests:* `test_coverage.py`.

## 9y. v0.17.0 — Learning from mistakes (16 Nov 2026)

*Why:* the owner asked for pattern recognition that identifies problems, learns from them, corrects its mistakes and does not repeat them. He chose to build "mistake memory + lessons" first and to let lessons **apply automatically with an undo**. A local model cannot rewrite itself, so the app improves the *standing instructions* it gives the model, and measures whether that worked.

*How (`mistakes.py`, schema v19: `mistake_log`, `lesson_rules`):*
1. **Log.** A mistake is recorded when he gives a thumbs-down, presses Regenerate, uses Correct (his version is kept beside the model's), or the fact-checker removes claims from a library answer. Edit is neutral. Each message+kind is logged once.
2. **Find patterns.** (a) *By counting, no AI:* from his corrections — answers he makes shorter or longer, bullet lists he turns into prose (or the reverse), opening pleasantries and closing offers he deletes. A habit in at least 3 corrections and 60% of them becomes a lesson. (b) *With the AI:* once 5 new mistakes are waiting (or any correction), and not while a reply is being written, the model reads them together and proposes up to 3 general lessons; a lesson needs 2 supporting mistakes or 1 correction, must be 8–170 characters and not about one fact. 10-minute cooldown.
3. **Apply.** Active lessons (max 12; at most 900 characters) are added to the instructions of every reply in their scope (Free chat / My files / Files + general / everywhere). Very similar lessons are merged, not duplicated.
4. **Check.** After 10 new answers in its scope each lesson is judged against the share of bad answers before it: ≤70% of that = *working*; not lower = *not helping* and the **app switches it off**. Turning a lesson back on starts a fresh check.
5. **Control.** Learning → "Learn from its mistakes": on/off switch for the whole feature, "Find patterns now", each lesson with evidence, scope and verdict, Turn off / Delete, and the latest mistakes noted.

*Limits:* lessons change how the model is told to write, not what it knows; they cannot fix a missing fact (the library and web learning do that). The AI's lessons are only as good as the small model's reading of the mistakes — that is why each is measured and can be switched off. The judgement needs real use (about 10 answers per lesson) before it says anything.

*Not built yet (agreed next):* gap detection per category with automatic topics for thin areas, usefulness scoring of learned pages / learning which sites are junk, automatic categories and sub-categories, and the pattern/visualisation screens (knowledge map, coverage heatmap, mistake trends, learning timeline).

*Tests:* `test_mistakes.py`.

## 9x. v0.16.0 — The app learns by itself (16 Nov 2026)

*Why:* the owner asked how the app can improve apart from files he adds, and then asked for it to crawl the web to learn. He chose **fully automatic** and **add immediately**. A local model on a 4 GB laptop cannot rewrite its own weights safely, so "learning" here means two things the app can do alone: grow its library from the web, and collect/prepare training data from how he uses it. The real fine-tune stays a short cloud run he starts.

**A. Learning from use (`training.py`, schema v18)**
- Signals the window reports: thumbs-up and Copy = good; thumbs-down and Regenerate = not good; Edit = neutral; "Correct" = he rewrites a Free-chat answer.
- A good Free-chat answer becomes a *training example* (his question → the answer, with the persona's instructions as system text). A correction replaces the plain example and keeps the model's original.
- Never an example: shorter than 40 characters, over ~6,000, "Your files don't cover this…", answers the fact-checker trimmed, anything marked down, and **any library-mode answer** (those depend on passages attached to the question, so teaching them would teach inventing).
- Learning screen: counts, a bar to ~300 examples (the point where a fine-tune is worth trying), a review list with Reject/Restore, and **Export dataset** → `<data folder>/training/dataset-<date>.jsonl` (one chat per line, "messages" format, duplicates removed) plus `HOW_TO_FINE_TUNE.md` (cloud notebook steps, GGUF export, `ollama create akara-mine -f Modelfile`, pick it in the model list). Needs at least 20 examples.
- Not built: importing the fine-tuned model from inside the app (the recipe uses one `ollama create` command instead).

**B. Learning from the web (`learner.py`, `websearch.py`)**
- A background loop, **OFF until he turns it on** in Learning. While on, each round it takes one topic (his own first, then topics noticed from questions "My files" could not answer — `chat.note_gap`), searches the web, reads up to 4 pages (one per site) with the normal crawler (robots.txt, polite delay, never local addresses) and **adds them straight to the library**, marked `sources.origin = 'learned'` with the topic.
- Watch addresses (his list) are re-read about every 24 h; the existing duplicate check means only changed content is added.
- Hard limits: daily page budget (default 60, 5–300), at most one topic per round, 20 minutes between rounds (5–240), only when online and not while he is running a web read himself, nothing from social/video/shopping sites, and a 3-hour rest after 4 empty rounds in a row.
- Everything is visible and reversible: topic list with results, recent activity, "Learn now", "Remove everything it learned" (asks twice; his own files are never touched).
- `websearch.py` reads DuckDuckGo's public "lite" results page (no key, only the search words leave the laptop). It can change layout or refuse bursts; then it returns nothing and the loop waits. Swapping the provider only touches that file.
- Learned pages are not cybersecurity-filtered (kept anyway), so a topic far from his field adds pages on that topic; the cap and Remove-all are the safety net.

*Connected to:* `db.py` (`_migrate_v18`: message_feedback, training_examples, learn_topics, learn_watch, sources.origin/learn_topic), `chat.py` (`undo_last(chat_id, reason)`, `note_gap`), `crawler.py` (`start(..., origin, topic)`), `server.py` (`/training/*`, `/learn/*`), `main.cjs` allowlist, `Learning.jsx`, `Chat.jsx`, `Sidebar.jsx`.

*Tests:* `test_training.py`, `test_learner.py` (local test site + fake search; budget, offline, pause, watch, removal, parser).

*Planned next:* import a fine-tuned model from the window; run "suggest memory" automatically at the end of a chat; rate library answers separately.

## 9w. v0.15.0 — Chat-first app (16 Nov 2026)

*Why:* the owner asked to turn the whole Knowledge Bank into a chat app "with all the UI/UX like that, not just models". Before, Chat was one of eight screens in a side rail. Now the app opens on Chat and the library is what the chat draws on.

*What changed (all in the window; one small engine addition):*
- **Opens on a new, empty chat** with a greeting and three suggestion cards that depend on the chosen mode.
- **Sidebar** (`Sidebar.jsx`): New chat (Ctrl+Shift+O), search your chats, chats grouped Today / Yesterday / Previous 7 days / Older, rename (pencil) and delete (bin, asks "Delete?" first). A collapsible **Knowledge** section (closed by default, remembered) holds Overview, Library, Topics, Answers, Learn, Tools; Setup, "Search everything" (Ctrl+K) and the engine status sit at the foot. Ctrl+B collapses the sidebar to an icon strip (remembered).
- **Chat screen** (`Chat.jsx`): full-window stage with a slim top bar (chat title, model picker, More models, Memory, Personas in Free chat), a centred conversation, and a rounded message box: paperclip (add files to the library; or drop files anywhere on the chat), globe (read a web page, section or site into the library, with progress and Stop), answer-mode picker (My files / Files + general / Free chat), persona picker in Free chat, round Send / Stop. The box grows as you type.
- **Under messages:** Copy; **Regenerate** on the last answer; **Edit** on your last message (puts it back in the box); Remember (memory). Regenerate and Edit take back the last exchange through the new engine call `POST /chat/undo` (`chat.undo_last`), refused while a reply is being written.
- **Engine:** `chat.undo_last(chat_id)` deletes the newest answer (if the chat ends with one) and the message of the owner's that it answered, returns his text. No schema change (still v17).
- Library, Topics, Answers, Learn, Tools and Setup are unchanged; they open from the Knowledge section.

*Connected to:* `App.jsx` (owns the open chat, list refresh counter, sidebar state, shortcuts), `Sidebar.jsx`, `Chat.jsx`, `styles.css` (`.side-*`, `.cx-*`), `server.py` (`/chat/undo`), `main.cjs` (allowlist).

*Limits:* files added from the message box are read in the background like any import; ask about them in "My files" once they are done (Library shows progress). Pages that need JavaScript cannot be read. A reply that is being written blocks Regenerate / Edit and mode changes.

*Training (answer given to the owner, build agreed separately):* see KB_PENDING "How to train this app".

*Planned next:* v0.16 training kit (rate answers, export a dataset, cloud-notebook recipe, import the result).

## 9v. v0.14.0 — Memory about you (16 Nov 2026)

*Why:* the owner wants an assistant that knows him (his business, preferences, projects) without repeating himself in every chat, and wants to be able to see and control everything it knows. For a small local model this is the cheapest and safest form of "training": no training at all, only context. Agreed roadmap step after Free chat and web reading.

*What — `engine/kb_engine/memory.py`, panel `app/src/MemoryPanel.jsx` (button "Memory" in the Chat bar; table `user_memory`, schema v17):*
- **A plain list of short facts** (each up to 300 characters, at most 200). He can add, edit, pin (pinned facts are always used first), delete, or "Forget everything" (asks twice). A switch "Use my memory in Free chat" turns it off without erasing it.
- **Nothing is saved unless he presses a button.** Two ways to add besides typing: "Remember" under any of his messages (pre-fills the box with that message to shorten), and "Suggest from this chat" — the model reads only what HE wrote in that chat and proposes up to 5 lasting facts (already-saved ones are shown to it so it doesn't repeat them; temporary things are to be skipped); each proposal has Remember / Skip.
- **Where it is used:** only in Free chat. The facts are added to the model's instructions (after the persona) under "what the owner has told you about himself — use it only when it helps, never list it back". "My files" and "Files + general" answers are not shaped by it, so a cited answer can never be influenced by something he once said. About 1,400 characters (roughly 350 tokens) go into one reply — pinned first, then newest — because the model's window is small; the panel shows how much fits.
- Memory lives in the one database file, so encrypted backups include it, and it never leaves the laptop.

*Tested:* `engine/tests/test_memory.py` (add/limits/duplicates, edit/pin/delete/clear, on/off, prompt budget and order, Free chat gets the facts and library prompts do not, parsing of model suggestions in several shapes, nothing saved without approval, only his words are read, failure explained, schema v17); older tests still pass; panel rendered in a headless browser. Real model (qwen3.5:4b, CPU): Free chat answered with the memory loaded in 16 s; suggestions from a sample chat first proposed a duplicate and a temporary fact, so the prompt now includes the saved list and says to skip "this month / right now" — the second run proposed nothing, i.e. it is cautious.

*Limits:* a 4B model uses a remembered fact only some of the time (a one-line tagline did not visibly use the brand fact), so for important writing also say it in the message or choose the persona. Suggestions are a convenience, not a judge: read each one. Memory holds facts, not conversations — to find an old conversation use the chat search. Do not store passwords or card numbers; the app does not stop him, so don't.

*Planned next:* v0.15 training kit (see 9t).

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
| 15 Nov 2026 | Doc 2.6 / KB v0.8.1 | Owner: import too slow. Two-pass import (text first, pictures after; schema v9 images.xref), OCR engine pool + parallel scanned pages (79 s → 30 s to searchable on 2 cores, identical passages), DirectML graphics-card OCR on Windows with automatic processor fallback, background OCR load. Added section 9l. |
| 15 Nov 2026 | Doc 2.7 / KB v0.8.2 | Owner: unrelated PDFs, slow CPU-bound AI, removed files returning. Relevance check before slow work + set aside + Keep anyway + one-time check of existing bank (relevance.py, schema v10); removed_files so watched folders never re-add; gpu.py memory savers, speed tuning with safe fallback, Graphics card card in Setup. Added section 9m. |
| 15 Nov 2026 | Doc 2.8 / KB v0.8.3 | Owner: skip PDFs whose content is already present; add only content not present. Paragraph-level skip by fingerprint, file-level "Already in the bank" set-aside with Keep anyway, early detection for scans, picture text, one-time check of existing bank, Library switch. Added section 9n. |
| 15 Nov 2026 | Doc 2.9 / KB v0.9.0 | Eleven owner-chosen improvements: junk cleaning + garbled-text OCR (cleaning.py), real file titles + categories (titles.py), Word/PowerPoint/web/text/Markdown (officefiles.py), automatic replacement of older versions, better search (filters, ranking, close matches, facets, RRF), hand-edited topics (topicedit.py), automatic rewrite of weak articles, big-library tuning + Storage card (storage.py), self-updating app (updater.cjs). Schema v11. Added section 9o. |
| 15 Nov 2026 | Doc 3.0 / KB v0.9.1 | Repeated statements folded inside topics (facts.py, schema v12, AI judge for borderline pairs, articles rewritten once). Added section 9p. |
| 15 Nov 2026 | Doc 3.1 / KB v0.9.2 | Removing files (one or many) now removes everything built from them: topics, articles, lessons, flashcards, saved answers. Library multi-select. Added section 9q. |
| 15 Nov 2026 | Doc 3.2 / KB v0.10.0 | AI understands each point (role + subject); topics shown and articles written by logical outline; contradictions and gaps surfaced. Schema v13. Added section 9r. |
| 16 Nov 2026 | Doc 3.3 / KB v0.11.0 | Chat: saved multi-turn conversations with the library (cited, fact-checked, general knowledge only on request, streaming + Stop), model picker with downloads and a compare-on-my-files test. Schema v14. Fixed v0.9.2 bug: removing a file never deleted saved answers. Added section 9s. |
| 16 Nov 2026 | Doc 3.4 / KB v0.12.0 | Free Chat: three modes per chat (My files / Files + general / Free chat), personas (5 built in, owner's own editable), schema v15. Fixed a Copy-and-edit button bug found in testing. Added section 9t. |
| 16 Nov 2026 | Doc 3.5 / KB v0.13.0 | Read a web address (page, section, whole site; sitemap, robots.txt, polite, local addresses refused) and paste text into the bank. Schema v16 (sources.url). Added section 9u. |
| 16 Nov 2026 | Doc 3.6 / KB v0.14.0 | Memory about the owner: editable facts, pin, suggestions from a chat approved one by one, used in Free chat only. Schema v17. Added section 9v. |
| 16 Nov 2026 | Doc 3.7 / KB v0.15.0 | Chat-first app: opens on Chat, ChatGPT-style sidebar (chat history by day, Knowledge section), message box with attach / web page / mode, Copy, Regenerate, Edit; engine /chat/undo. Added section 9w. |
| 16 Nov 2026 | Doc 3.8 / KB v0.16.0 | The app learns by itself: web learning loop (daily budget, switch, learned pages removable) and learning from use (signals, corrections, training examples, dataset export). Schema v18. Added section 9x. |
| 16 Nov 2026 | Doc 4.5 / KB v0.22.1 | Fix: Live learning crash (missing import) blanked the window; crash guard per screen; polling skips while busy/hidden; 60 s read timeout. Added section 9ae. |
| 16 Nov 2026 | Doc 4.4 / KB v0.22.0 | Pictures on Overview, Library, Topics and Learning (donuts, treemaps, rings, bars) with captions; shared viz.jsx; glance.py. Added section 9ad. |
| 16 Nov 2026 | Doc 4.3 / KB v0.21.0 | Live learning screen: dot per file/page, embedding-based relations, arrival animation, replay, text feed. brain.py, schema v22. Added section 9ac. |
| 16 Nov 2026 | Doc 4.2 / KB v0.20.0 | Insights screen: knowledge map, coverage heatmap, mistake trends, timeline with animations; /insights/all. No schema change (v21). Added section 9ab. |
| 16 Nov 2026 | Doc 4.1 / KB v0.19.0 | Categories and sub-categories grow from the data (AI or plain word groups), owner Rename/Merge/Delete, Library sub-category chips, coverage includes grown categories. Schema v21. Added section 9aa. |
| 16 Nov 2026 | Doc 4.0 / KB v0.18.0 | Coverage per category, automatic topics for thin areas, usefulness of learned pages, junk-site blocking and owner Block/Allow. Schema v20. Added section 9z. |
| 16 Nov 2026 | Doc 3.9 / KB v0.17.0 | Learning from mistakes: mistake log, counted and AI-found patterns, automatic lessons added to replies, effectiveness check with auto switch-off. Schema v19. Added section 9y. |
