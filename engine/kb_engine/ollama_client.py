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


def installed_details() -> list[dict]:
    """
    Installed models with their download size in MB: [{"name", "size_mb"}].
    CALLED BY: modelpick.py (the model picker lists what is on this laptop).
    """
    try:
        r = httpx.get(f"{config.OLLAMA_URL}/api/tags", timeout=10)
        r.raise_for_status()
        return [{"name": m["name"], "size_mb": int(m.get("size") or 0) // 2**20}
                for m in r.json().get("models", [])]
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


# ---------------------------------------------------------------------------
# Graphics-card placement and measured speeds (v0.8.2, see gpu.py)
# ---------------------------------------------------------------------------
_layers: dict[str, int] | None = None   # model → num_gpu chosen by gpu.tune()
_speeds: dict[str, dict] = {}           # model → last measured speed


def set_layer_choices(layers: dict) -> None:
    """gpu.tune() saves which models run faster with every layer forced on."""
    global _layers
    _layers = dict(layers or {})


def _layer_choice(model: str) -> int | None:
    global _layers
    if _layers is None:
        try:
            from . import db
            _layers = dict(db.get_setting("ollama_num_gpu", {}) or {})
        except Exception:
            _layers = {}
    return _layers.get(model)


def _record_speed(model: str, kind: str, value: float) -> None:
    import time as _time
    if value > 0:
        _speeds[model] = {"kind": kind, "value": round(value, 1), "at": _time.strftime("%H:%M")}


def speeds() -> dict:
    """Last measured speed per model ({"kind": "tokens/s"|"passages/s", "value"})."""
    return dict(_speeds)


def gpu_share(model: str) -> float | None:
    """Fraction (0–1) of a LOADED model held in video memory, from /api/ps."""
    for m in loaded_split():
        if m["name"] in (model, f"{model}:latest") or m["name"].split(":")[0] == model:
            return m["gpu_share"]
    return None


def loaded_split() -> list[dict]:
    """Each loaded model with its size and share on the graphics card."""
    try:
        r = httpx.get(f"{config.OLLAMA_URL}/api/ps", timeout=5)
        r.raise_for_status()
        out = []
        for m in r.json().get("models", []):
            size, vram = int(m.get("size") or 0), int(m.get("size_vram") or 0)
            out.append({"name": m.get("name"), "size_mb": size // 2**20, "vram_mb": vram // 2**20,
                        "gpu_share": round(vram / size, 3) if size else None})
        return out
    except (httpx.HTTPError, ValueError):
        return []


def generate(
    model: str,
    prompt: str,
    system: str | None = None,
    temperature: float = 0.2,
    num_ctx: int = 8192,
    think: bool = False,
    num_predict: int | None = None,
    on_text=None,
    num_gpu: int | None = None,
    fallback: bool = True,
    should_stop=None,
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

      on_text      — optional callback(text_so_far). When given, the answer is
                     STREAMED and the callback receives the growing text about
                     4× a second, so the app can show it being written live
                     (v0.8). The final result is the same as without it.

      num_gpu      — layers to put on the graphics card (v0.8.2). None = the
                     value gpu.tune() measured as fastest for this model, or
                     Ollama's own choice. If a forced value fails (e.g. out
                     of video memory) the request is retried once with
                     Ollama's choice and the forced value is forgotten
                     (fallback=False turns that off — used while tuning).

      should_stop  — optional callable returning True when the owner pressed
                     Stop (v0.11, Chat). Only used with on_text (streaming):
                     writing ends at once and the text written so far is
                     returned as a normal result.

    RETURNS: GenerationResult with the text and timing figures.
    RAISES:  OllamaError with a readable message on any failure.
    """
    forced = num_gpu if num_gpu is not None else _layer_choice(model)
    try:
        result = _generate_once(model, prompt, system, temperature, num_ctx, think,
                                num_predict, on_text, forced, should_stop)
    except OllamaError:
        if forced is None or not fallback:
            raise
        if _layers is not None:
            _layers.pop(model, None)  # forced placement failed: stop forcing
        result = _generate_once(model, prompt, system, temperature, num_ctx, think,
                                num_predict, on_text, None, should_stop)
    _record_speed(model, "tokens/s", result.tokens_per_second)
    return result


def _generate_once(model, prompt, system, temperature, num_ctx, think, num_predict,
                   on_text, num_gpu, should_stop=None) -> GenerationResult:
    """One request to Ollama (see generate() for the parameters)."""
    payload: dict = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "think": think,
        "options": {"temperature": temperature, "num_ctx": num_ctx},
    }
    if num_predict:
        payload["options"]["num_predict"] = num_predict
    if num_gpu is not None:
        payload["options"]["num_gpu"] = num_gpu
    if system:
        payload["system"] = system
    if on_text is not None:
        return _generate_stream(model, payload, on_text, should_stop)
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


def _generate_stream(model: str, payload: dict, on_text, should_stop=None) -> GenerationResult:
    """Streamed version of generate(): same result, with live progress callbacks."""
    import json as _json
    import time as _time

    payload = {**payload, "stream": True}
    text, last, final = "", 0.0, {}
    try:
        with httpx.stream("POST", f"{config.OLLAMA_URL}/api/generate", json=payload,
                          timeout=config.OLLAMA_TIMEOUT_SECONDS) as r:
            if r.status_code == 400:
                r.read()
                if "think" in r.text.lower() and "think" in payload:
                    return _generate_stream(model, {k: v for k, v in payload.items() if k != "think"},
                                            on_text, should_stop)
            if r.status_code != 200:
                r.read()
                raise OllamaError(f"Ollama error for model {model}: HTTP {r.status_code} {r.text[:300]}")
            for line in r.iter_lines():
                if not line:
                    continue
                chunk = _json.loads(line)
                text += chunk.get("response", "")
                if chunk.get("done"):
                    final = chunk
                    break
                if should_stop is not None and should_stop():
                    break  # the owner pressed Stop: keep what was written so far
                if _time.monotonic() - last > 0.25:
                    last = _time.monotonic()
                    try:
                        on_text(text)
                    except Exception:
                        pass  # a display problem must never stop the writing
    except httpx.HTTPError as exc:
        raise OllamaError(f"Ollama did not respond for model {model}: {exc}") from exc
    on_text(text)
    return GenerationResult(
        text=text.strip(),
        prompt_tokens=int(final.get("prompt_eval_count") or 0),
        output_tokens=int(final.get("eval_count") or 0),
        load_seconds=_ns_to_s(final.get("load_duration")),
        prompt_seconds=_ns_to_s(final.get("prompt_eval_duration")),
        generate_seconds=_ns_to_s(final.get("eval_duration")),
        total_seconds=_ns_to_s(final.get("total_duration")),
    )


def embed(model: str, texts: list[str]) -> list[list[float]]:
    """
    Turn texts into meaning-vectors (lists of numbers).

    WHY:   Two passages that say the same thing in different words get
           vectors that are close together — the basis of meaning-search and
           of merging duplicates in Phase 2.
    CALLED BY: benchmark.py now (speed test); Phase 2 clustering later.
    """
    import time as _time
    started = _time.monotonic()
    try:
        r = httpx.post(
            f"{config.OLLAMA_URL}/api/embed",
            json={"model": model, "input": texts},
            timeout=config.OLLAMA_TIMEOUT_SECONDS,
        )
        r.raise_for_status()
        out = r.json()["embeddings"]
        if len(texts) >= 4:  # tiny batches say little about speed
            _record_speed(model, "passages/s", len(texts) / max(_time.monotonic() - started, 1e-3))
        return out
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


def running_models() -> list[str]:
    """Models currently loaded in memory (Ollama's /api/ps). [] if unreachable."""
    try:
        r = httpx.get(f"{config.OLLAMA_URL}/api/ps", timeout=5)
        r.raise_for_status()
        return [m["name"] for m in r.json().get("models", [])]
    except httpx.HTTPError:
        return []


def clear_gpu_except(keep: str | None = None, wait_seconds: float = 20) -> None:
    """
    Unload every loaded model except `keep`, and WAIT until they're gone.

    WHY:   The owner's benchmark measured embedding at 1.2 passages/second —
           far too slow for a GPU. The likely cause: a big model was still
           occupying the 4 GB card, so the embedding model was placed on the
           CPU. unload() only *asks* Ollama to unload; this waits until
           /api/ps confirms the memory is free before the next model loads.
    CALLED BY: distill.py before embedding; writer.py before writing.
    """
    import time as _time

    def others() -> list[str]:
        k = keep if keep is None or ":" in keep else f"{keep}:latest"
        return [m for m in running_models() if m not in (keep, k)]

    for name in others():
        unload(name)
    deadline = _time.time() + wait_seconds
    while others() and _time.time() < deadline:
        _time.sleep(0.5)


def delete_model(name: str) -> bool:
    """Delete a downloaded model from disk (frees its space). True if deleted."""
    try:
        r = httpx.request("DELETE", f"{config.OLLAMA_URL}/api/delete", json={"model": name}, timeout=60)
        return r.status_code == 200
    except httpx.HTTPError:
        return False

