"""
kb_engine — the Python "brain" of the Knowledge Bank app.

WHAT:  This package holds all the heavy lifting that the desktop window
       (the Electron app in /app) cannot do well by itself: reading PDFs,
       OCR, talking to the local AI models through Ollama, and storing the
       knowledge bank in SQLite.

WHY:   Python has the best tools for PDFs (PyMuPDF), OCR and local AI.
       Keeping this logic out of the window means the window stays smooth
       and responsive even while hours-long processing runs in the background.

HOW IT CONNECTS:
       - app/electron/main.js starts this package as a separate process
         (`python -m kb_engine.server`) when the app opens.
       - The window then talks to it over a private local web address
         (http://127.0.0.1:8765). Nothing is exposed to the network.

MODULES:
       config.py        — every path, port and model name in one place
       db.py            — creates/opens the SQLite knowledge-bank database
       system_check.py  — reports GPU, RAM, disk and Ollama status
       ollama_client.py — small helper for calling the local AI models
       server.py        — the local web server the window talks to
       setup_manager.py — in-app setup wizard jobs (AI engine, model
                          downloads, benchmark) with live progress
       benchmark.py     — one-off tool that picks the best models for
                          the owner's laptop
       importer.py      — Phase 1: imports PDFs/images (text, OCR,
                          duplicates, watched folders)
       chunking.py      — cuts page text into citable passages
       ocr.py           — reads text from scans, screenshots, diagrams
       search.py        — instant exact-word search
       distill.py       — Phase 2: embeddings, topics, repeat groups,
                          topic links, topic names
       writer.py        — Phase 3: one structured, cited article per topic
       lessons.py       — automatic visual lessons: profile, AI plan from a
                          fixed diagram menu, calculated blocks, fact check
       updates.py       — checks/updates Ollama and the AI models
       meaning.py       — Ctrl+K search: meaning (vectors) blended with words
       answers.py       — Phase 4 answer pages: cited, fact-checked answers
       learn.py         — Phase 5 flashcards, spaced repetition, progress
       tools.py         — Phase 6 IOC extraction, ATT&CK coverage, query library
       backup.py        — Phase 7 password-encrypted backup and restore
       data/mitre_techniques.json — ATT&CK technique names/tactics (offline)
"""

# Single version string for the engine. Shown in the app's status screen
# and in benchmark reports so we always know which build produced what.
__version__ = "0.15.0"
