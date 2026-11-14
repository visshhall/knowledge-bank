"""
benchmark.py — picks the best AI models for the owner's laptop, using his own PDFs.

WHAT:  A one-off test (Phase 0). It:
         1. Measures how fast PyMuPDF reads the sample PDFs (pages/second)
            → lets us estimate how long importing all 5–6 GB will take.
         2. Flags pages with almost no text (likely scanned → need OCR).
         3. Runs every candidate model in config.BENCHMARK_MODELS on the same
            excerpts with the same "write a knowledge-bank summary" task, and
            records load time, writing speed (tokens/second), total time and
            video memory used.
         4. Tests the embedding model's speed (passages per second).
         5. Writes a report (Markdown for reading + JSON for exact numbers)
            including every model's actual output, so quality can be judged
            side by side — speed alone doesn't decide.

WHY:   Model choice is the biggest single factor in both speed and quality.
       Published benchmarks use other hardware and other text; this uses the
       owner's RTX 3060 (6 GB) and his real cybersecurity documents.

WHEN:  Run once by the owner after setup:
           setup\\run-benchmark.ps1 "C:\\path\\to\\folder-with-5-10-pdfs"
       (or directly: python -m kb_engine.benchmark --pdfs <folder>)
       The owner then sends the generated report to Claude.

CONNECTED TO: config.py (models, report folder), ollama_client.py (AI calls),
       system_check.py (GPU memory readings). Does NOT write to the knowledge
       bank database — it's a standalone measurement tool.

PRIVACY: Everything runs locally. The report contains short excerpts of the
       PDFs and model summaries — the owner can review it before sharing.
"""

import argparse
import json
import statistics
import time
from datetime import datetime
from pathlib import Path

import pymupdf  # PyMuPDF (fast PDF reader)

from . import __version__, config, ollama_client, system_check

# A page with fewer characters than this is treated as "probably scanned"
# (an image of text with no text layer), which will need OCR in Phase 1.
SCANNED_PAGE_CHAR_THRESHOLD = 40

# Each excerpt sent to the models is capped at roughly this many words, so
# every model gets an identical, realistic-sized task (≈ one topic's worth).
EXCERPT_WORD_LIMIT = 1800

# The same instructions the real topic-writer will use (simplified), so the
# benchmark measures the job we actually need done.
SYSTEM_PROMPT = (
    "You are the writer for a cybersecurity knowledge bank. You turn raw "
    "document text into a clear, accurate study article. Use only facts "
    "present in the text. Never invent event IDs, commands, product names or "
    "numbers. If the text is unclear, say so."
)

TASK_TEMPLATE = """Write a knowledge-bank article from the SOURCE TEXT below.

Format (Markdown):
# <short topic title>
**Summary:** 2-3 sentences.
## Key concepts
- 4-8 bullet points
## How it works / steps
- numbered steps if the text describes a process, otherwise "Not described in source."
## Queries / commands / IDs mentioned
- list any KQL, commands, event IDs exactly as written, otherwise "None in source."

SOURCE TEXT:
\"\"\"
{text}
\"\"\"
"""


# --------------------------------------------------------------------------- #
# Step 1–2: read the PDFs
# --------------------------------------------------------------------------- #

def read_pdfs(folder: Path, max_files: int) -> tuple[list[dict], dict]:
    """
    Read up to `max_files` PDFs from `folder` with PyMuPDF.

    RETURNS:
      samples — one dict per PDF: file name, page count, scanned-page count,
                and an excerpt (first ~1800 words of real text) for the models
      extraction_stats — total pages read, seconds taken, pages/second

    HOW:   Reads EVERY page (not just the excerpt) so the pages/second figure
           reflects real import speed. Pages are processed one at a time and
           released, the same memory-safe approach Phase 1 will use for huge
           PDFs.
    """
    pdf_paths = sorted(p for p in folder.iterdir() if p.suffix.lower() == ".pdf")[:max_files]
    if not pdf_paths:
        raise SystemExit(f"No PDF files found in {folder}")

    samples: list[dict] = []
    total_pages = 0
    started = time.perf_counter()

    for path in pdf_paths:
        words: list[str] = []
        scanned = 0
        try:
            with pymupdf.open(path) as doc:
                if doc.needs_pass:
                    samples.append({"file": path.name, "error": "password-protected (skipped)"})
                    continue
                for page in doc:
                    text = page.get_text("text")
                    if len(text.strip()) < SCANNED_PAGE_CHAR_THRESHOLD:
                        scanned += 1
                    elif len(words) < EXCERPT_WORD_LIMIT:
                        words.extend(text.split())
                page_count = doc.page_count
        except Exception as exc:  # corrupt/unreadable file: record and continue
            samples.append({"file": path.name, "error": f"could not read: {exc}"})
            continue

        total_pages += page_count
        samples.append({
            "file": path.name,
            "size_mb": round(path.stat().st_size / 1024**2, 2),
            "pages": page_count,
            "probably_scanned_pages": scanned,
            "excerpt": " ".join(words[:EXCERPT_WORD_LIMIT]),
        })

    seconds = time.perf_counter() - started
    stats = {
        "files": len(pdf_paths),
        "pages": total_pages,
        "seconds": round(seconds, 2),
        "pages_per_second": round(total_pages / seconds, 1) if seconds else None,
    }
    return samples, stats


# --------------------------------------------------------------------------- #
# Step 3: models
# --------------------------------------------------------------------------- #

def _vram_used_mb() -> int | None:
    """Current video memory in use (MB), or None if no NVIDIA GPU."""
    gpu = system_check.gpu_info()
    return gpu.get("vram_used_mb") if gpu.get("available") else None


def bench_model(model: str, samples: list[dict], think: bool) -> dict:
    """
    Run one model over every usable excerpt and collect timings + outputs.

    HOW:   1. Unload the model (clean start), record idle video memory.
           2. Tiny warm-up call → measures pure load time.
           3. Record video memory with the model loaded → shows whether it
              fits the 6 GB card (if not, Ollama spills into RAM = slower).
           4. Run the real task on each excerpt.
           5. Unload again so the next model starts clean.
    """
    ollama_client.unload(model)
    time.sleep(2)
    vram_idle = _vram_used_mb()

    warm = ollama_client.generate(model, "Reply with the single word: ready", think=False)
    vram_loaded = _vram_used_mb()

    runs: list[dict] = []
    for s in samples:
        if not s.get("excerpt"):
            continue
        try:
            r = ollama_client.generate(
                model,
                TASK_TEMPLATE.format(text=s["excerpt"]),
                system=SYSTEM_PROMPT,
                think=think,
            )
            runs.append({
                "file": s["file"],
                "prompt_tokens": r.prompt_tokens,
                "output_tokens": r.output_tokens,
                "tokens_per_second": round(r.tokens_per_second, 1),
                "seconds": round(r.total_seconds, 1),
                "output": r.text,
            })
        except ollama_client.OllamaError as exc:
            runs.append({"file": s["file"], "error": str(exc)})

    ollama_client.unload(model)

    ok = [r for r in runs if "error" not in r]
    return {
        "model": model,
        "load_seconds": round(warm.load_seconds, 1),
        "vram_model_mb": (vram_loaded - vram_idle) if (vram_loaded and vram_idle is not None) else None,
        "avg_tokens_per_second": round(statistics.mean(r["tokens_per_second"] for r in ok), 1) if ok else None,
        "avg_seconds_per_article": round(statistics.mean(r["seconds"] for r in ok), 1) if ok else None,
        "runs": runs,
    }


def bench_embeddings(samples: list[dict]) -> dict:
    """
    Measure embedding speed on ~300-word chunks of the excerpts.

    WHY:   Phase 2 will embed every passage of every PDF. Passages/second
           tells us how long that step takes for the full 5–6 GB collection.
    """
    chunks: list[str] = []
    for s in samples:
        words = (s.get("excerpt") or "").split()
        chunks.extend(" ".join(words[i:i + 300]) for i in range(0, len(words), 300))
    if not chunks:
        return {"model": config.EMBED_MODEL, "error": "no text to embed"}
    try:
        ollama_client.embed(config.EMBED_MODEL, chunks[:1])  # warm-up / load
        started = time.perf_counter()
        vectors = ollama_client.embed(config.EMBED_MODEL, chunks)
        seconds = time.perf_counter() - started
    except ollama_client.OllamaError as exc:
        return {"model": config.EMBED_MODEL, "error": str(exc)}
    finally:
        ollama_client.unload(config.EMBED_MODEL)
    return {
        "model": config.EMBED_MODEL,
        "passages": len(chunks),
        "dimensions": len(vectors[0]) if vectors else None,
        "seconds": round(seconds, 2),
        "passages_per_second": round(len(chunks) / seconds, 1) if seconds else None,
    }


# --------------------------------------------------------------------------- #
# Step 5: report
# --------------------------------------------------------------------------- #

def write_report(result: dict) -> tuple[Path, Path]:
    """
    Save the results as JSON (exact numbers) and Markdown (easy reading).
    RETURNS: (markdown_path, json_path) inside config.REPORTS_DIR.
    """
    config.ensure_dirs()
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    json_path = config.REPORTS_DIR / f"benchmark-{stamp}.json"
    md_path = config.REPORTS_DIR / f"benchmark-{stamp}.md"
    json_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")

    lines = [
        f"# Knowledge Bank — model benchmark ({stamp})",
        f"Engine {result['engine_version']} · GPU: {result['gpu'].get('name', 'none')} "
        f"({result['gpu'].get('vram_total_mb', '?')} MB)",
        "",
        "## PDF reading",
        f"- {result['extraction']['files']} files, {result['extraction']['pages']} pages "
        f"in {result['extraction']['seconds']} s → **{result['extraction']['pages_per_second']} pages/s**",
    ]
    for s in result["samples"]:
        if "error" in s:
            lines.append(f"- {s['file']}: {s['error']}")
        elif s["probably_scanned_pages"]:
            lines.append(f"- {s['file']}: {s['probably_scanned_pages']} of {s['pages']} "
                         "pages look scanned (need OCR)")

    lines += ["", "## Models", "",
              "| Model | Load (s) | Video memory (MB) | Speed (tokens/s) | Avg s / article |",
              "|---|---|---|---|---|"]
    for m in result["models"]:
        if "error" in m:
            lines.append(f"| {m['model']} | — | — | — | {m['error']} |")
        else:
            lines.append(f"| {m['model']} | {m['load_seconds']} | {m['vram_model_mb'] or '?'} | "
                         f"{m['avg_tokens_per_second'] or '—'} | {m['avg_seconds_per_article'] or '—'} |")

    e = result["embedding"]
    lines += ["", "## Embedding",
              f"- {e['model']}: " + (e["error"] if "error" in e else
                                      f"{e['passages_per_second']} passages/s "
                                      f"({e['dimensions']} dimensions)")]

    lines += ["", "## Outputs (judge quality here)"]
    for m in result["models"]:
        for r in m.get("runs", []):
            lines += ["", f"### {m['model']} — {r['file']}", "",
                      r.get("output") or f"ERROR: {r.get('error')}"]

    md_path.write_text("\n".join(lines), encoding="utf-8")
    return md_path, json_path


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #

def main() -> None:
    """
    Parse arguments, run all steps, print where the report was saved.

    ARGUMENTS:
      --pdfs FOLDER     folder with 5–10 representative PDFs (required)
      --max-files N     cap on PDFs read (default 10)
      --models a,b,c    override the candidate list from config.py
      --think           also enable the models' reasoning mode (slower)
    """
    parser = argparse.ArgumentParser(description="Knowledge Bank model benchmark")
    parser.add_argument("--pdfs", required=True, type=Path)
    parser.add_argument("--max-files", type=int, default=10)
    parser.add_argument("--models", type=str, default="")
    parser.add_argument("--think", action="store_true")
    args = parser.parse_args()

    if not args.pdfs.is_dir():
        raise SystemExit(f"Not a folder: {args.pdfs}")
    if not ollama_client.is_running():
        raise SystemExit("Ollama is not running. Start it from the Start menu and retry.")

    candidates = [m.strip() for m in args.models.split(",") if m.strip()] or config.BENCHMARK_MODELS
    installed = ollama_client.installed_models()

    print(f"Reading PDFs from {args.pdfs} ...")
    samples, extraction = read_pdfs(args.pdfs, args.max_files)
    print(f"  {extraction['pages']} pages at {extraction['pages_per_second']} pages/s")

    models: list[dict] = []
    for model in candidates:
        if not ollama_client.has_model(model, installed):
            print(f"Skipping {model} (not downloaded — run: ollama pull {model})")
            models.append({"model": model, "error": "not downloaded"})
            continue
        print(f"Benchmarking {model} ... (this can take several minutes)")
        try:
            models.append(bench_model(model, samples, args.think))
        except ollama_client.OllamaError as exc:
            models.append({"model": model, "error": str(exc)})

    print("Benchmarking embeddings ...")
    embedding = bench_embeddings(samples)

    result = {
        "engine_version": __version__,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "gpu": system_check.gpu_info(),
        "think_mode": args.think,
        "extraction": extraction,
        "samples": [{k: v for k, v in s.items() if k != "excerpt"} for s in samples],
        "models": models,
        "embedding": embedding,
    }
    md_path, json_path = write_report(result)
    print(f"\nDone. Report saved to:\n  {md_path}\n  {json_path}")
    print("Send the .md file to Claude in the KB chat.")


if __name__ == "__main__":
    main()
