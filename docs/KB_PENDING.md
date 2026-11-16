# KB — Pending Work Tracker

Living document. Updated after every change. Companion to [KB_REFERENCE.md](KB_REFERENCE.md).

**Current version:** v0.18.0 (finds gaps per category and fetches what is missing, scores learned pages, blocks junk sites; v0.17.0 learns from its mistakes; v0.16.0 the app learns by itself: web learning + learning from use; v0.15.0 chat-first app: opens on Chat with a ChatGPT-style sidebar; v0.14.0 memory about you; v0.13.0 web reading and pasted text; v0.12.0 Free Chat and personas; v0.11.0 Chat and model picker; v0.10.0 reasoning; v0.9.2 remove files completely; v0.9.1 repeats folded; v0.9.0 eleven improvements; v0.8.3 same content never added twice; v0.8.2 relevance filter, removed files stay removed, graphics-card tuning; v0.8.1 faster import; v0.8.0 diagrams, writing speed, spreadsheet topics — in owner testing)
**Last updated:** 16 November 2026

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

## v0.18.0 — Gaps, page usefulness, junk sites ✅ delivered
- [x] Coverage score per category, weak/gap flags, automatic web topics for thin categories, "Fill the gaps now"
- [x] Learned pages judged useful / not used yet / thin; thin pages removed automatically; "Remove unused pages (45+ days)"
- [x] Per-site score; junk sites skipped automatically; Block / Allow / Let the app decide
- [ ] Owner check: Learning → "What it knows and what is missing": categories you care about should show real bars; press "Fill the gaps now" and look for topics tagged "fills a gap" in Learn from the web
- [ ] Owner check: with Web learning on for a day or two, look at the Web sites list; block any site you do not trust
- [ ] Known: usefulness is based on answers citing a page, so it takes days of use to mean much
- [ ] Known: categories are the fixed cybersecurity list for now
- [ ] Next (agreed order): automatic categories/sub-categories (v0.19); pattern and visualisation screens with animations (v0.20)

## v0.17.0 — Learning from mistakes ✅ delivered
- [x] Mistake log (thumbs-down, Regenerate, Correct, facts removed), patterns by counting and by the AI, lessons added to replies automatically, effectiveness check
- [ ] Owner check: in Free chat use Correct on 3–4 answers where you shorten them or remove "Certainly!"; open Learning → "Learn from its mistakes" → "Find patterns now"; a lesson should appear
- [ ] Owner check: after about 10 more Free-chat answers, look at the lesson's tag: working / no clear effect / not helping (switched off)
- [ ] Owner check: turn a lesson off and on; delete one
- [ ] Known: judging a lesson needs real use (about 10 answers) — new lessons show "new" at first
- [ ] Next (agreed order): gap detection per category + automatic topics; usefulness scoring of learned pages and junk-site learning; automatic categories/sub-categories; pattern and visualisation screens

## v0.16.0 — The app learns by itself ✅ delivered
- [x] Learning screen (Knowledge section): web learning switch (OFF by default), topics, watch addresses, daily budget, recent activity, Remove everything it learned
- [x] Thumbs up/down and Correct under Free-chat answers; Copy / Regenerate / Edit counted as signals
- [x] Training examples built automatically; review (Reject / Restore); Export dataset + HOW_TO_FINE_TUNE.md
- [ ] Owner check: open Learning, add one topic you care about (e.g. "Microsoft Sentinel analytics rule tuning"), turn Web learning on, press "Learn now", watch "What it just did", then look in Library for the pages (they show the web address)
- [ ] Owner check: ask "My files" a question your files cannot answer — it should appear as a topic "from a question" (only while learning is on)
- [ ] Owner check: in Free chat press thumbs-up on 3 answers and Correct one; Learning should show 4 examples
- [ ] Owner check: leave learning on for a day and tell me if the pages it added are useful or junk; use "Remove everything it learned" if junk
- [ ] Known: the web search reads DuckDuckGo's public page; if it stops returning results the topics show "nothing found" and the loop rests
- [ ] Known: learned pages are not filtered to cybersecurity; the topic list decides what gets learned
- [ ] Not built yet: import the fine-tuned model from inside the app; automatic memory suggestions at the end of a chat

## v0.15.0 — Chat-first app ✅ delivered
- [x] App opens on a new chat; sidebar with chat history (Today / Yesterday / Previous 7 days / Older), rename, delete, search
- [x] Library screens moved under a collapsible "Knowledge" section; Setup and Search everything at the foot
- [x] Message box: attach files, add a web page, answer-mode picker, persona picker, round Send / Stop
- [x] Copy, Regenerate, Edit under messages; drop files onto the chat; Ctrl+Shift+O, Ctrl+B, Ctrl+K
- [ ] Owner check: open the app — it should land on a new chat. Ask something in each mode and confirm it feels like a chat app
- [ ] Owner check: press the paperclip, add one PDF, wait for Library to finish it, then ask about it in "My files"
- [ ] Owner check: press the globe, read one page of a site you own, ask about it in "My files"
- [ ] Owner check: Regenerate on an answer; Edit on your last message; both should replace the old exchange
- [ ] Owner check: Ctrl+B collapses the sidebar to icons and back; it stays that way after restarting
- [ ] Known: a very long chat list is capped at the newest 200 chats

## How to train this app going forward (explained to the owner on 16 Nov 2026)
"Training" means three different things; the first two already work, the third is planned (v0.16) and will be agreed before it is built.
1. **Teach it by giving it data (works now, no training).** Add files, whole folders, web addresses and pasted text (Library, or the paperclip / globe in Chat). Everything is read, searched and cited in "My files". This is the biggest lever and costs nothing.
2. **Teach it about you and how to behave (works now).** Memory = short facts about you; Personas = instructions for tone and role (Ākāra copywriter etc.). Both are applied in Free chat on every message.
3. **Change the model itself (fine-tuning, planned v0.16).** A small model (about 3–4 billion parameters) is adjusted on examples of questions and the answers you approved (LoRA). The 4 GB laptop graphics card cannot do this, so the plan is: the app exports a dataset file (thumbs-up answers, your own corrected answers, product copy you wrote), you run a ready-made notebook on a free cloud GPU for about an hour, then import the result back into Ollama and pick it in the model list. Good for a fixed writing style or format; not good for adding facts (that is what the library is for). Needs about 200–1000 good examples to be worth doing.
*Order of effort:* add data first, then memory/personas, then rate answers for a few weeks, then fine-tune once enough approved examples exist.

## v0.14.0 — Memory about you ✅ delivered
- [x] Chat → Memory: add, edit, pin, delete, forget everything, on/off switch
- [x] "Remember" under your messages; "Suggest from this chat" (you approve each fact)
- [x] Free chat uses the facts; library answers never do
- [ ] Owner check: add 4–5 facts about Ākāra and how you like things written, then in Free chat ask for a planter page without repeating them and tell me if it used them
- [ ] Owner check: press "Suggest from this chat" after a long Free chat and tell me if the suggestions are useful or noisy
- [ ] Known: a small model uses a fact only some of the time; for important writing, also say it in the message

## v0.13.0 — Add from the web and paste text ✅ delivered
- [x] Library → "From the web": a page, a section or a whole site, with a page limit; Stop; progress and reasons for skipped pages
- [x] Pages and linked documents saved as local copies, searchable, usable in Chat/Topics; opening a source opens its web address
- [x] "Paste text" box
- [ ] Owner check: read ONE real page of your own Ākāra site (scope "This page only"), then Chat → My files and ask something only that page says; tell me if the answer cites it
- [ ] Owner check: read a small section of a documentation site (limit 20 pages) and tell me what was skipped and why
- [ ] Owner check: if a page you care about comes back "almost no readable text", tell me which — it needs JavaScript and I'll look at a browser-based reader
- [ ] Known: JavaScript-only sites and pages behind a login can't be read; a 500-page site needs several reads

## v0.12.0 — Free Chat and personas ✅ delivered
- [x] Three modes per chat: My files / Files + general / Free chat (saved with the chat)
- [x] Personas: Assistant, Ākāra copywriter, Coding helper, Tutor, Security analyst; make, edit, delete your own
- [x] Free replies are labelled "not from your files"; nothing in them is cited or fact-checked
- [ ] Owner check: switch to Free chat, pick "Ākāra copywriter", ask for a product page for one real planter (give it the size, material and colour) and tell me how the tone reads
- [ ] Owner check: write one persona of your own in "Edit personas" and try it
- [ ] Owner check: open an old library chat and a Free chat and confirm each opens in its own mode
- [ ] Known: Free chat uses the same graphics card as article writing; do not run both at once

### Agreed roadmap after v0.12 (not started)
- v0.13 ✅ delivered: web reading and pasted text (other file types already worked)
- v0.14 ✅ delivered: memory about you
- v0.15 ✅ delivered: chat-first app shell
- v0.16 ✅ delivered (signals, examples, export, web learning). Remaining of the old training kit: in-app import of the fine-tuned model
- (old plan) Training kit: thumbs up/down on answers, dataset export from chats and files, a cloud-notebook recipe to fine-tune a small model (about an hour on a free GPU), import the result back
- Later ideas: voice in/out, optional web search when online, phone access (needs a security decision)

## v0.11.0 — Chat and model picker ✅ delivered
- [x] Chat screen: saved chats (new, rename, delete, search), cited and fact-checked answers, follow-ups, streaming + Stop
- [x] "Also use general knowledge" switch (off by default; that part is labelled and not checked)
- [x] Model picker (Setup → Models for Chat; model box in Chat), download buttons, compare-on-my-files test
- [x] Fixed: removing a file now really deletes saved Answers that cited it (v0.9.2 bug), and clears chat answers that cited it
- [ ] Owner check: ask 5–10 real questions in Chat, including a follow-up ("and how do I detect it?") and one your files can't answer; tell me if an answer cites the wrong source or forgets the earlier question
- [ ] Owner check: turn on "Also use general knowledge" for one question and confirm the general part sits in its own labelled box
- [ ] Owner check: Setup → Models for Chat → download Phi-4-mini (about 3 GB), tick it and qwen3.5:4b, press Compare; send me the table and tell me which answers you preferred
- [ ] Owner check: remove a PDF that you used in a chat and confirm the chat answer that quoted it is cleared
- [ ] Known: Chat and writing articles share the graphics card; do not run both at once

## v0.10.0 — Reasoning: roles, subjects, outline ✅ delivered
- [x] AI labels each point's role and subject; saved per point (schema v13)
- [x] Topics "By meaning" view, contradiction and gap notes
- [x] Articles written from the outline with a share for every section
- [ ] Owner check: run "Write remaining" (rewrites every article once), open a few topics under "By meaning", and tell me where a point sits in the wrong section or a subject name is odd

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
