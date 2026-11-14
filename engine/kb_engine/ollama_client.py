"""
ollama_client.py — the one place that talks to the local AI models.

WHAT:  Small wrapper around Ollama's local HTTP API: list installed models,
       generate text, and create embeddings (meaning-vectors).

WHY:   Every feature that uses AI (benchmark now; topic writing, search
       answers and Learn mode later) goes through here. If Ollama's API
       changes, or we swap Ollama for another runtime, only this file changes.

WHEN:  Called on demand — by system_check.py (is Ollama running? which models
       are installed?), benchmark.py (timing tests), and later phases.

CONNECTED TO: config.py (OLLAMA_URL, timeout). Talks only to 127.0.0.1 —
       no document text ever leaves the laptop.
"""

from dataclasses import dataclass

import httpx

from . import config


class OllamaError(RuntimeError):
    """Raised with a plain-English message when Ollama can't do what we asked."""


@dataclass
class GenerationResult:
    """
    Everything we learn from one AI response.

    text               — what the model wrote
    prompt_tokens      — size of the input, in tokens (≈ ¾ of a word each)
    output_tokens      — size of the answer, in tokens
    load_seconds       — time spent loading the model into memory (high on
                         the first call, near zero once it's loaded)
    prompt_seconds     — time spent reading the input
    generate_seconds   — time spent writing the answer
    total_seconds      — wall-clock total reported by Ollama
    """

    text: str
    prompt_tokens: int
    output_tokens: int
    load_seconds: float
    prompt_seconds: float
    generate_seconds: float
    total_seconds: float

    @property
    def tokens_per_second(self) -> float:
        """Writing speed — the key number for comparing models."""
        return self.output_tokens / self.generate_seconds if self.generate_seconds else 0.0


def _ns_to_s(value: int | None) -> float:
    """Ollama reports durations in nanoseconds; convert to seconds."""
    return (value or 0) / 1_000_000_000


def is_running() -> bool:
    """
    True if the Ollama service is answering on this computer.
    CALLED BY: system_check.py and benchmark.py before doing any AI work.
    """
    try:
        httpx.get(f"{config.OLLAMA_URL}/api/version", timeout=3).raise_for_status()
        return True
    except httpx.HTTPError:
        return False


def version() -> str | None:
    """Ollama's version string, or None if it isn't running."""
    try:
        r = httpx.get(f"{config.OLLAMA_URL}/api/version", timeout=3)
        r.raise_for_status()
        return r.json().get("version")
    except httpx.HTTPError:
        return None


def installed_models() -> list[str]:
    """
    Names of models already downloaded (e.g. ['qwen3:8b', 'nomic-embed-text:latest']).
    CALLED BY: system_check.py (status screen) and benchmark.py (skip models
               that aren't downloaded instead of failing).
    """
    try:
        r = httpx.get(f"{config.OLLAMA_URL}/api/tags", timeout=10)
        r.raise_for_status()
        return [m["name"] for m in r.json().get("models", [])]
    except httpx.HTTPError as exc:
        raise OllamaError(f"Could not list models — is Ollama running? ({exc})") from exc


def has_model(name: str, installed: list[str] | None = None) -> bool:
    """
    True if `name` is downloaded. Accepts 'nomic-embed-text' for
    'nomic-embed-text:latest' because Ollama adds ':latest' automatically.
    """
    installed = installed if installed is not None else installed_models()
    if name in installed:
        return True
    return ":" not in name and f"{name}:latest" in installed


def generate(
    model: str,
    prompt: str,
    system: str | None = None,
    temperature: float = 0.2,
    num_ctx: int = 8192,
    think: bool = False,
    num_predict: int | None = None,
) -> GenerationResult:
    """
    Ask a model to write a response (non-streaming: waits for the full answer).

    PARAMETERS:
      model        — Ollama model name, e.g. config.FAST_MODEL
      prompt       — the request plus any source text
      system       — standing instructions (role, rules, output format)
      temperature  — low (0.2) = factual and consistent, which is what a
                     knowledge bank needs; high = more creative
      num_ctx      — how many tokens of input+output the model can see at
                     once. 8192 ≈ 6,000 words. Larger uses more video memory,
                     which is the scarce resource on a 4 GB card.
      think        — some models (Qwen 3.x) can "reason" privately before
                     answering. Off by default: much faster, and summaries
                     rarely need it. The benchmark measures both if useful.
      num_predict  — maximum length of the answer in tokens. A hard stop so a
                     model that rambles (or "thinks" despite think=False)
                     can never run for many minutes on one request.

    RETURNS: GenerationResult with the text and timing figures.
    RAISES:  OllamaError with a readable message on any failure.
    """
    payload: dict = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "think": think,
        "options": {"temperature": temperature, "num_ctx": num_ctx},
    }
    if num_predict:
        payload["options"]["num_predict"] = num_predict
    if system:
        payload["system"] = system
    try:
        r = httpx.post(
            f"{config.OLLAMA_URL}/api/generate",
            json=payload,
            timeout=config.OLLAMA_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as exc:
        raise OllamaError(f"Ollama did not respond for model {model}: {exc}") from exc

    # Models without a thinking mode reject the `think` field on some Ollama
    # versions. Retry once without it rather than failing the whole run.
    if r.status_code == 400 and "think" in r.text.lower():
        payload.pop("think", None)
        r = httpx.post(
            f"{config.OLLAMA_URL}/api/generate",
            json=payload,
            timeout=config.OLLAMA_TIMEOUT_SECONDS,
        )
    if r.status_code != 200:
        raise OllamaError(f"Ollama error for model {model}: HTTP {r.status_code} {r.text[:300]}")

    data = r.json()
    return GenerationResult(
        text=data.get("response", "").strip(),
        prompt_tokens=int(data.get("prompt_eval_count") or 0),
        output_tokens=int(data.get("eval_count") or 0),
        load_seconds=_ns_to_s(data.get("load_duration")),
        prompt_seconds=_ns_to_s(data.get("prompt_eval_duration")),
        generate_seconds=_ns_to_s(data.get("eval_duration")),
        total_seconds=_ns_to_s(data.get("total_duration")),
    )


def embed(model: str, texts: list[str]) -> list[list[float]]:
    """
    Turn texts into meaning-vectors (lists of numbers).

    WHY:   Two passages that say the same thing in different words get
           vectors that are close together — the basis of meaning-search and
           of merging duplicates in Phase 2.
    CALLED BY: benchmark.py now (speed test); Phase 2 clustering later.
    """
    try:
        r = httpx.post(
            f"{config.OLLAMA_URL}/api/embed",
            json={"model": model, "input": texts},
            timeout=config.OLLAMA_TIMEOUT_SECONDS,
        )
        r.raise_for_status()
        return r.json()["embeddings"]
    except (httpx.HTTPError, KeyError) as exc:
        raise OllamaError(f"Embedding failed for model {model}: {exc}") from exc


def unload(model: str) -> None:
    """
    Remove a model from video memory immediately.

    WHY:   Video memory is scarce (4 GB on the owner's RTX 3050). Between benchmark runs we
           unload the previous model so each test starts from the same clean
           state and timings are fair. Errors are ignored (nothing to unload).
    """
    try:
        httpx.post(
            f"{config.OLLAMA_URL}/api/generate",
            json={"model": model, "keep_alive": 0},
            timeout=30,
        )
    except httpx.HTTPError:
        pass
