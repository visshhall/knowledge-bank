"""
distill.py — Phase 2: turns imported passages into topics.

WHAT:  One background job ("Build topics") with five stages:
         1. Embed     — every passage without a meaning-vector gets one from
                        the local embedding model (Ollama). Only new passages
                        are embedded on later runs.
         2. Topics    — passages are grouped by meaning with spherical
                        k-means (cosine similarity) on centred vectors, so text
                        that talks about the same subject lands in the same
                        topic even when worded differently. Same-subject
                        topics are merged; oversized ones are split; 1–2
                        passage "topics" are folded into their nearest one.
         3. Repeats   — inside each topic, passages that say practically the
                        same thing (same fingerprint, or ≥ 0.95 similarity)
                        are joined into one "repeat group": shown once, with
                        every file + page that said it.
         4. Links     — topics whose centres are close are linked; these are
                        the lines on the future Knowledge Map.
         5. Names     — each topic is named from its most central passages by
                        the fast local AI model; if the model isn't available
                        a keyword name is used instead, so the job never stalls.
       Results replace the previous draft topics in one transaction at the
       end, so the Topics screen never shows a half-built state.

WHY:   This is the "no duplicates, nothing missed" core the owner asked for:
         - Nothing missed: every passage is assigned to exactly one topic
           (coverage 100%). Passages that fit their topic only loosely are
           counted and shown for review, never silently dropped.
         - No duplicates: repeats are grouped, not deleted — the bank shows
           the content once and keeps every source.
       It also prepares Phase 3 (writing one merged article per topic).
       Why k-means on embeddings: it's fast with numpy (seconds for tens of
       thousands of passages), needs no extra libraries, and works on the
       owner's 16 GB laptop. Only the embedding step uses the GPU.

WHEN:  When the owner presses "Build topics" on the Topics screen
       (server.py → POST /distill/start). Takes minutes; progress is polled
       via GET /distill/status. Re-running is safe: embeddings are reused and
       draft topics are rebuilt.

CONNECTED TO: db.py (passages.embedding, passages.cluster_id, topics,
       topic_passages, topic_links, settings), ollama_client.py (embed,
       generate), config.py (EMBED_MODEL, FAST_MODEL), server.py,
       app/src/Topics.jsx.
"""

from __future__ import annotations  # type hints stay text, so numpy can load lazily

import json
import math
import re
import threading
import time
from collections import Counter

from . import config, datapages, db, ollama_client

# numpy is loaded only when topics are actually built (_load_numpy), not when
# the engine starts. If it ever failed to load on a machine, only "Build
# topics" would report an error — import, search and everything else would
# keep working.
np = None


def _load_numpy() -> None:
    """Import numpy once, on first use, into this module's `np`."""
    global np
    if np is None:
        import numpy

        np = numpy

# --- Tunable thresholds (cosine similarity, -1..1; 1 = identical meaning) ---
#
# WHY TWO KINDS OF SIMILARITY (fixed in v0.6.1 after the owner's 6 PDFs /
# 304 passages produced only 3 topics, one holding 298 points):
# the embedding model gives ALL text a strong shared direction, so any two
# cybersecurity passages — even on different subjects — score ~0.69, and
# topic centres (averages) score ~0.9. The old merge rule (centres ≥ 0.88 →
# same topic) therefore merged almost everything into one topic.
# Fix: grouping, merging, loose-fit and links now use CENTRED vectors (the
# collection's average direction is subtracted, then each vector is
# re-normalised). In that space unrelated passages score ~0, so the
# thresholds below mean what they say. Measured on a 317-passage labelled
# cybersecurity test set (MITRE ATT&CK, real nomic-embed-text): a passage's
# fit to its own topic has median 0.46, 5th percentile 0.25; topic centres
# score −0.10 median, 0.19 at the 90th percentile, 0.44 at most.
# Old result on that set: 3 topics (310/6/1). New: 13 topics, 11–39 each.
# Repeat detection still uses the ORIGINAL vectors (0.95 there really does
# mean "says the same thing").
NEAR_DUPLICATE = 0.95     # (original vectors) two passages this similar are "the same thing"
MERGE_TOPICS = 0.60       # (centred) two topic centres this similar become one topic
LINK_TOPICS = 0.20        # (centred) topics at least this similar get a map link (~top 10%)
LOOSE_FIT = 0.25          # (centred) a passage below this fits its topic only loosely (~5%)
MIN_TOPIC_POINTS = 3      # smaller topics are folded into their nearest topic
MAX_TOPIC_SHARE = 4       # a topic over 4× the average size (and > 60) is split
MAX_TOPICS = 400          # upper bound on the number of topics
EMBED_BATCH = 64          # passages sent to the embedding model per call
EMBED_MAX_CHARS = 2000    # long passages are cut to this before embedding
NAMING_SAMPLES = 6        # central passages shown to the AI to name a topic

# nomic-embed-text expects a task prefix; other models ignore it harmlessly.
DOC_PREFIX = "search_document: "

_STOPWORDS = set("""
a about above after again against all also am an and any are as at be because been
before being below between both but by can could did do does doing down during each
few for from further had has have having he her here hers him his how i if in into
is it its itself just may me might more most must my no nor not now of off on once
only or other our ours out over own same she should so some such than that the their
them then there these they this those through to too under until up upon us use used
using very was we were what when where which while who whom why will with would you
your page figure table see example following shown e g i e etc one two three new
""".split())

_lock = threading.Lock()
_running = False
_state = {
    "state": "idle",       # idle | running | done | error
    "stage": None,         # embed | topics | repeats | links | names | saving
    "done": 0,
    "total": 0,
    "message": "",
    "finished_at": None,
    "naming_with": None,   # model name, or "keywords" if the AI wasn't available
}


def _set(**kw) -> None:
    with _lock:
        _state.update(kw)


def status() -> dict:
    """Snapshot of the job, polled by the Topics screen."""
    with _lock:
        snap = dict(_state)
    snap["last_run"] = db.get_setting("distill_last_run")
    return snap


def start() -> dict:
    """Begin the job in the background (ignored if it's already running)."""
    global _running
    with _lock:
        if _running:
            return {"ok": True, "message": "Already building topics."}
        _running = True
        _state.update(state="running", stage="embed", done=0, total=0,
                      message="Starting…", naming_with=None)
    threading.Thread(target=_run, name="kb-distill", daemon=True).start()
    return {"ok": True, "message": "Building topics."}


def start_update() -> dict:
    """
    Phase 7: add NEW passages to the EXISTING topics (no full rebuild).
    Falls back to a full build when there are no topics yet.
    """
    global _running
    with db.connect() as conn:
        has_topics = conn.execute("SELECT 1 FROM topics LIMIT 1").fetchone()
    if not has_topics:
        return start()
    with _lock:
        if _running:
            return {"ok": True, "message": "Already building topics."}
        _running = True
        _state.update(state="running", stage="embed", done=0, total=0,
                      message="Starting…", naming_with=None)
    threading.Thread(target=_run_update, name="kb-distill-update", daemon=True).start()
    return {"ok": True, "message": "Adding new passages to your topics."}


def pending_count() -> int:
    """Passages that belong to no topic yet (new files since the last build)."""
    with db.connect() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM passages p JOIN sources s ON s.id = p.source_id WHERE s.file_type != 'table' "
            "AND p.id NOT IN (SELECT passage_id FROM topic_passages)").fetchone()[0]


def _run_update() -> None:
    """
    Incremental update (KB v0.7, Phase 7).

    HOW:  1. Embed the new passages (only those without a vector).
          2. In the same centred space the full build uses, compute each
             existing topic's centre from its current members and put every
             new passage in the nearest topic (coverage stays 100%; a poor
             fit is flagged "loose" like any other).
          3. Repeats: a new passage that says the same thing as a passage
             already in that topic (same fingerprint or ≥ NEAR_DUPLICATE
             similar) joins its repeat group, so it's shown once.
          4. Topics that received new material and already had an article
             are marked 'stale' and their lesson cleared, so "Write
             remaining" refreshes exactly those — nothing else is rewritten.
    WHY:  The owner's library keeps growing; a full rebuild re-groups
          everything and can rename topics. This keeps topics, articles,
          lessons and flashcard progress stable and costs seconds.
    WHEN: "Update topics" on the Topics screen, and automatically after an
          import finishes when topics already exist (importer.py).
    LIMIT: new subjects that fit no existing topic are only flagged as
          loose; when much new material arrives (> 30% of the bank) the
          screen suggests a full rebuild.
    """
    global _running
    started = time.time()
    try:
        _load_numpy()
        _embed_missing()
        _set(stage="topics", done=0, total=1, message="Placing new passages in your topics…")
        ids, mat, _texts, hashes = _load_vectors()
        with db.connect() as conn:
            member = {r["passage_id"]: r["topic_id"] for r in conn.execute(
                "SELECT passage_id, topic_id FROM topic_passages")}
            clusters = {r["id"]: r["cluster_id"] for r in conn.execute("SELECT id, cluster_id FROM passages")}
        topic_ids = sorted(set(member.values()))
        new_rows = [i for i, pid in enumerate(ids) if int(pid) not in member]
        if not new_rows:
            _set(state="done", stage=None, message="Nothing new to add — every passage is already in a topic.",
                 finished_at=time.strftime("%H:%M"))
            return
        z = _centre(mat)
        index = {t: k for k, t in enumerate(topic_ids)}
        cents = np.zeros((len(topic_ids), z.shape[1]), dtype=np.float32)
        old_rows = [i for i, pid in enumerate(ids) if int(pid) in member]
        for i in old_rows:
            cents[index[member[int(ids[i])]]] += z[i]
        cents /= np.maximum(np.linalg.norm(cents, axis=1, keepdims=True), 1e-9)

        sims = z[new_rows] @ cents.T
        best = sims.argmax(axis=1)
        fit = sims.max(axis=1)
        rows_by_topic: dict[int, list[int]] = {}
        for i in old_rows:
            rows_by_topic.setdefault(member[int(ids[i])], []).append(i)

        inserts, cluster_updates, touched = [], [], set()
        for n, i in enumerate(new_rows):
            t = topic_ids[int(best[n])]
            touched.add(t)
            inserts.append((t, int(ids[i]), float(fit[n])))
            # Repeat group: same fingerprint or near-identical meaning.
            group = int(ids[i])
            for j in rows_by_topic.get(t, []):
                if hashes[j] == hashes[i] or float(mat[i] @ mat[j]) >= NEAR_DUPLICATE:
                    group = clusters.get(int(ids[j])) or int(ids[j])
                    break
            cluster_updates.append((group, int(ids[i])))
            rows_by_topic.setdefault(t, []).append(i)
        with db.connect() as conn:
            conn.executemany("INSERT INTO topic_passages(topic_id, passage_id, fit) VALUES (?, ?, ?)", inserts)
            conn.executemany("UPDATE passages SET cluster_id = ? WHERE id = ?", cluster_updates)
            for t in touched:
                conn.execute("UPDATE topics SET status = 'stale', updated_at = datetime('now') "
                             "WHERE id = ? AND status = 'written'", (t,))
                conn.execute("DELETE FROM lessons WHERE topic_id = ?", (t,))
        _judge_repeats()
        share = len(new_rows) / max(1, len(ids))
        hint = " Much new material arrived — consider Rebuild topics for the best grouping." if share > 0.3 else ""
        _set(state="done", stage=None, done=1, total=1,
             message=f"Added {len(new_rows):,} new passage{'' if len(new_rows) == 1 else 's'} to {len(touched)} topic{'' if len(touched) == 1 else 's'}.{hint}",
             finished_at=time.strftime("%H:%M"), updated_topics=len(touched), added=len(new_rows),
             seconds=round(time.time() - started))
    except Exception as exc:
        _set(state="error", stage=None, message=str(exc))
    finally:
        with _lock:
            _running = False


# ---------------------------------------------------------------------------
# Stage 1: embeddings
# ---------------------------------------------------------------------------

def _to_blob(vec: np.ndarray) -> bytes:
    """Store a vector as raw float32 bytes (compact: 768 dims ≈ 3 KB)."""
    return np.asarray(vec, dtype=np.float32).tobytes()


def _embed_missing() -> None:
    """
    Embed every passage that has no vector yet. If the embedding model was
    changed since the last run, all old vectors are cleared first (vectors
    from different models can't be compared).
    """
    model = config.EMBED_MODEL
    if db.get_setting("embed_model") not in (None, model):
        with db.connect() as conn:
            conn.execute("UPDATE passages SET embedding = NULL")
    db.set_setting("embed_model", model)

    if not ollama_client.is_running():
        raise RuntimeError("The AI engine (Ollama) isn't running. Start it from Setup.")
    if not ollama_client.has_model(model):
        raise RuntimeError(f"The embedding model {model} isn't downloaded yet. Download it from Setup.")

    with db.connect() as conn:
        total = conn.execute("SELECT COUNT(*) FROM passages WHERE embedding IS NULL").fetchone()[0]
    _set(stage="embed", done=0, total=total, message="Freeing the graphics card…")
    ollama_client.clear_gpu_except(model)   # so the embedding model gets the GPU
    _set(message="Reading the meaning of each passage…")
    done = 0
    t0 = time.time()
    while True:
        with db.connect() as conn:
            rows = conn.execute(
                "SELECT id, text FROM passages WHERE embedding IS NULL ORDER BY id LIMIT ?",
                (EMBED_BATCH,),
            ).fetchall()
        if not rows:
            break
        texts = [DOC_PREFIX + r["text"][:EMBED_MAX_CHARS] for r in rows]
        vectors = np.asarray(ollama_client.embed(model, texts), dtype=np.float32)
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        vectors = vectors / np.maximum(norms, 1e-9)          # unit length → dot = cosine
        with db.connect() as conn:
            conn.executemany(
                "UPDATE passages SET embedding = ? WHERE id = ?",
                [(_to_blob(v), r["id"]) for v, r in zip(vectors, rows)],
            )
        done += len(rows)
        rate = done / max(time.time() - t0, 0.001)
        left = (total - done) / rate if rate else 0
        eta = f"{left / 60:.0f} min left" if left >= 90 else f"{left:.0f} s left"
        _set(done=done, message=f"Reading meaning: {rate:.0f} passages/s, about {eta}")


def _load_vectors() -> tuple[np.ndarray, np.ndarray, list[str], list[str]]:
    """
    Load every embedded passage. RETURNS (ids, matrix N×D, texts, fingerprints).
    Memory: 100,000 passages × 768 dims × 4 bytes ≈ 300 MB — fine on 16 GB.
    """
    with db.connect() as conn:
        # Spreadsheet rows are not grouped by meaning: each spreadsheet is
        # its own calculated "data" topic (datapages.py, v0.8).
        rows = conn.execute(
            "SELECT p.id, p.text, p.content_hash, p.embedding FROM passages p "
            "JOIN sources s ON s.id = p.source_id "
            "WHERE p.embedding IS NOT NULL AND s.file_type != 'table' ORDER BY p.id"
        ).fetchall()
    if not rows:
        return np.zeros(0, dtype=np.int64), np.zeros((0, 1), dtype=np.float32), [], []
    ids = np.array([r["id"] for r in rows], dtype=np.int64)
    mat = np.vstack([np.frombuffer(r["embedding"], dtype=np.float32) for r in rows])
    return ids, mat, [r["text"] for r in rows], [r["content_hash"] for r in rows]


# ---------------------------------------------------------------------------
# Stage 2: topics (spherical k-means)
# ---------------------------------------------------------------------------

def _choose_k(n: int) -> int:
    """How many topics to aim for: ~√(n/2), between 1 and MAX_TOPICS."""
    return max(1, min(MAX_TOPICS, round(math.sqrt(n / 2))))


def _assign(mat: np.ndarray, centroids: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """
    Nearest centroid for every row, in chunks so memory stays small.
    RETURNS (labels, best_similarity).
    """
    labels = np.empty(len(mat), dtype=np.int64)
    best = np.empty(len(mat), dtype=np.float32)
    for start in range(0, len(mat), 8192):
        sims = mat[start:start + 8192] @ centroids.T
        labels[start:start + 8192] = sims.argmax(axis=1)
        best[start:start + 8192] = sims.max(axis=1)
    return labels, best


def _kmeans(mat: np.ndarray, k: int, iterations: int = 20, seed: int = 7) -> tuple[np.ndarray, np.ndarray]:
    """
    Spherical k-means: like ordinary k-means, but on unit vectors with cosine
    similarity, which is the right measure for text embeddings.
    Seeding is k-means++ (spreads the starting centres out) on a sample of
    up to 20,000 passages for speed. A fixed seed makes results repeatable.
    RETURNS (centroids k×D, labels N).
    """
    rng = np.random.default_rng(seed)
    n = len(mat)
    sample = mat[rng.choice(n, size=min(n, 20000), replace=False)]
    centroids = [sample[rng.integers(len(sample))]]
    closest = 1 - sample @ centroids[0]
    for _ in range(1, k):
        weights = np.clip(closest, 0, None) ** 2
        if weights.sum() <= 0:
            break
        pick = sample[rng.choice(len(sample), p=weights / weights.sum())]
        centroids.append(pick)
        closest = np.minimum(closest, 1 - sample @ pick)
    centroids = np.vstack(centroids)

    labels = np.zeros(n, dtype=np.int64)
    for it in range(iterations):
        new_labels, _ = _assign(mat, centroids)
        if it and np.array_equal(new_labels, labels):
            break  # converged
        labels = new_labels
        sums = np.zeros_like(centroids)
        np.add.at(sums, labels, mat)
        norms = np.linalg.norm(sums, axis=1, keepdims=True)
        filled = norms[:, 0] > 0
        centroids[filled] = sums[filled] / norms[filled]
    return centroids, labels


def _best_kmeans(mat: np.ndarray, k: int, restarts: int = 4) -> tuple[np.ndarray, np.ndarray]:
    """
    Run k-means from several different starting points and keep the result
    whose passages sit closest to their topic centres (highest total
    similarity). One unlucky start can split one subject and merge two
    others; restarts make the grouping stable. Cost: a few seconds.
    """
    best = None
    for seed in range(restarts):
        centroids, labels = _kmeans(mat, k, seed=seed)
        score = float(np.einsum("ij,ij->", mat, centroids[labels]))
        if best is None or score > best[0]:
            best = (score, centroids, labels)
    return best[1], best[2]


def _centre(mat: np.ndarray) -> np.ndarray:
    """
    Subtract the collection's average direction and re-normalise (see the
    threshold notes at the top). RETURNS a new N×D matrix of unit vectors.
    """
    z = mat - mat.mean(axis=0, keepdims=True)
    return z / np.maximum(np.linalg.norm(z, axis=1, keepdims=True), 1e-9)


def _recentre(z: np.ndarray, labels: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Renumber labels 0..k-1 (dropping empty topics) and recompute centres."""
    uniq, labels = np.unique(labels, return_inverse=True)
    cents = np.zeros((len(uniq), z.shape[1]), dtype=np.float32)
    np.add.at(cents, labels, z)
    cents /= np.maximum(np.linalg.norm(cents, axis=1, keepdims=True), 1e-9)
    return cents, labels


def _balance(z: np.ndarray, centroids: np.ndarray, labels: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """
    Safety net so one topic can never swallow the library again:
      - a topic larger than MAX_TOPIC_SHARE × the average size (and over 60
        passages) is split in two by k-means on its own passages, repeatedly;
      - a topic with fewer than MIN_TOPIC_POINTS passages is folded into
        the nearest other topic (a 1-point "topic" helps nobody).
    """
    for _ in range(50):  # bounded: each round splits at most one topic
        sizes = np.bincount(labels, minlength=len(centroids))
        limit = max(60, MAX_TOPIC_SHARE * len(labels) / max(1, len(centroids)))
        big = int(sizes.argmax())
        if sizes[big] <= limit or len(centroids) >= MAX_TOPICS:
            break
        members = np.nonzero(labels == big)[0]
        _, sub = _best_kmeans(z[members], 2, restarts=2)
        if sub.min() == sub.max():
            break
        labels = labels.copy()
        labels[members[sub == 1]] = len(centroids)
        centroids, labels = _recentre(z, labels)
    sizes = np.bincount(labels, minlength=len(centroids))
    small = np.nonzero(sizes < MIN_TOPIC_POINTS)[0]
    if len(small) and len(small) < len(centroids):
        keep = np.setdiff1d(np.arange(len(centroids)), small)
        labels = labels.copy()
        for i in np.nonzero(np.isin(labels, small))[0]:
            labels[i] = keep[int(np.argmax(centroids[keep] @ z[i]))]
        centroids, labels = _recentre(z, labels)
    return centroids, labels


def cluster(mat: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """
    The whole grouping step, kept separate so it can be tested on its own.
    mat: original unit vectors (N×D).
    RETURNS (labels N, fit N, centroids k×D, centred vectors N×D) — fit and
    centroids are in the centred space where LOOSE_FIT/LINK_TOPICS apply.
    """
    z = _centre(mat)
    centroids, labels = _best_kmeans(z, _choose_k(len(z)))
    centroids, labels = _merge_similar(centroids, labels, z)
    centroids, labels = _balance(z, centroids, labels)
    fit = np.einsum("ij,ij->i", z, centroids[labels])
    return labels, fit, centroids, z


def _merge_similar(centroids: np.ndarray, labels: np.ndarray, mat: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """
    Merge topics whose centres are ≥ MERGE_TOPICS similar (the same subject
    split in two), drop empty ones, and recompute centres. Union-find keeps
    chains of merges consistent.
    """
    k = len(centroids)
    parent = list(range(k))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    sims = centroids @ centroids.T
    for a in range(k):
        for b in np.nonzero(sims[a, a + 1:] >= MERGE_TOPICS)[0] + a + 1:
            parent[find(int(b))] = find(a)
    roots = np.array([find(int(l)) for l in range(k)])
    merged = roots[labels]
    uniq, new_labels = np.unique(merged, return_inverse=True)
    new_centroids = np.zeros((len(uniq), mat.shape[1]), dtype=np.float32)
    np.add.at(new_centroids, new_labels, mat)
    new_centroids /= np.maximum(np.linalg.norm(new_centroids, axis=1, keepdims=True), 1e-9)
    return new_centroids, new_labels


# ---------------------------------------------------------------------------
# Stage 3: repeat groups inside each topic
# ---------------------------------------------------------------------------

def _repeat_groups(ids: np.ndarray, mat: np.ndarray, hashes: list[str], labels: np.ndarray) -> np.ndarray:
    """
    For every passage, the id of the first passage that says the same thing
    (itself if unique). Compared only within a topic, which keeps the work
    small (topic sizes are hundreds, not tens of thousands).
    """
    group = ids.copy()
    for t in np.unique(labels):
        members = np.nonzero(labels == t)[0]
        # Exact repeats (same fingerprint) first — cheap and certain.
        first_by_hash: dict[str, int] = {}
        for m in members:
            h = hashes[m]
            if h in first_by_hash:
                group[m] = ids[first_by_hash[h]]
            else:
                first_by_hash[h] = m
        # Near repeats by meaning, among the remaining representatives.
        reps = [m for m in members if group[m] == ids[m]]
        for start in range(0, len(reps), 2048):
            block = reps[start:start + 2048]
            sims = mat[block] @ mat[reps].T
            for i, m in enumerate(block):
                earlier = [reps[j] for j in np.nonzero(sims[i] >= NEAR_DUPLICATE)[0] if reps[j] < m]
                if earlier:
                    group[m] = group[min(earlier)]
    return group


# ---------------------------------------------------------------------------
# Stage 5: names
# ---------------------------------------------------------------------------

_WORD = re.compile(r"[A-Za-z][A-Za-z0-9\-]{2,}")


def _keyword_title(texts: list[str], corpus_df: Counter, n_docs: int) -> str:
    """
    Fallback name: the 3 words most typical of this topic compared with the
    whole bank (a simple TF-IDF), e.g. "Kerberos · Ticket · Golden".
    """
    tf = Counter(w.lower() for t in texts for w in _WORD.findall(t) if w.lower() not in _STOPWORDS)
    scored = sorted(tf, key=lambda w: tf[w] * math.log((n_docs + 1) / (corpus_df[w] + 1)), reverse=True)
    words = [w.capitalize() if not w.isupper() else w for w in scored[:3]]
    return " · ".join(words) if words else "Untitled topic"


def _ai_name(samples: list[str]) -> tuple[str, str] | None:
    """
    Ask the fast local model for a short title and one-sentence summary.
    RETURNS (title, summary) or None if the answer can't be used.
    """
    joined = "\n\n".join(f"[{i + 1}] {s[:700]}" for i, s in enumerate(samples))
    prompt = (
        "These passages come from cybersecurity documents and are about one topic.\n\n"
        f"{joined}\n\n"
        'Reply with JSON only: {"title": "<2-6 word topic title>", '
        '"summary": "<one plain sentence saying what this topic covers>"}'
    )
    try:
        r = ollama_client.generate(
            config.FAST_MODEL, prompt,
            system="You name topics in a knowledge bank. Use only what the passages say. "
                   "Titles are specific (e.g. 'Kerberoasting detection', not 'Security').",
            temperature=0.1, num_ctx=4096,
        )
    except ollama_client.OllamaError:
        return None
    match = re.search(r"\{.*\}", r.text, re.S)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
        title = str(data.get("title", "")).strip().strip('"')[:80]
        summary = str(data.get("summary", "")).strip()[:300]
    except (json.JSONDecodeError, AttributeError):
        return None
    return (title, summary) if title else None


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60] or "topic"


# ---------------------------------------------------------------------------
# The job
# ---------------------------------------------------------------------------

def _run() -> None:
    """Run all stages; on any error, report it and leave existing topics intact."""
    global _running
    started = time.time()
    try:
        _load_numpy()
        _embed_missing()

        ids, mat, texts, hashes = _load_vectors()
        n = len(ids)
        if n == 0:
            raise RuntimeError("No passages yet. Import some files in the Library first.")

        _set(stage="topics", done=0, total=1, message="Grouping passages by meaning…")
        # Grouping happens on centred vectors (see the threshold notes above);
        # repeat detection below still uses the original vectors.
        labels, fit, centroids, _ = cluster(mat)
        k = len(centroids)
        _set(done=1)

        _set(stage="repeats", done=0, total=1, message="Finding passages that repeat each other…")
        groups = _repeat_groups(ids, mat, hashes, labels)
        _set(done=1)

        _set(stage="links", done=0, total=1, message="Connecting related topics…")
        csims = centroids @ centroids.T
        links: list[tuple[int, int, float]] = []
        for a in range(k):
            order = np.argsort(-csims[a])
            near = [int(b) for b in order if b != a and csims[a, b] >= LINK_TOPICS][:4]
            # Every topic keeps at least its 2 closest neighbours (if at all
            # alike), so the map never shows isolated islands just because a
            # library's topics are broad (v0.7).
            if len(near) < 2:
                near = [int(b) for b in order if b != a and csims[a, b] > 0.05][:2]
            links.extend((a, b, float(csims[a, b])) for b in near if a < b)
        _set(done=1)

        # Names: central, non-repeated passages of each topic.
        use_ai = ollama_client.is_running() and ollama_client.has_model(config.FAST_MODEL)
        _set(stage="names", done=0, total=k, naming_with=config.FAST_MODEL if use_ai else "keywords",
             message="Naming each topic…")
        corpus_df = Counter(w for t in texts for w in {x.lower() for x in _WORD.findall(t)})
        names: list[tuple[str, str]] = []
        for t in range(k):
            members = np.nonzero(labels == t)[0]
            members = members[np.argsort(-fit[members])]
            reps = [m for m in members if groups[m] == ids[m]][:NAMING_SAMPLES] or list(members[:NAMING_SAMPLES])
            samples = [texts[m] for m in reps]
            named = _ai_name(samples) if use_ai else None
            if named is None:
                named = (_keyword_title([texts[m] for m in members[:60]], corpus_df, n), "")
            names.append(named)
            _set(done=t + 1)

        _set(stage="saving", message="Saving topics…")
        _save(ids, labels, fit, groups, names, links, k)
        datapages.rebuild_data_topics()  # spreadsheets: one calculated topic each
        _judge_repeats()

        loose = int((fit < LOOSE_FIT).sum())
        db.set_setting("distill_last_run", {
            "at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "seconds": round(time.time() - started),
            "passages": n,
            "topics": k,
            "repeat_groups_merged": int(n - len(np.unique(groups))),
            "loose_passages": loose,
            "coverage_percent": 100.0,
            "named_with": _state.get("naming_with"),
        })
        _set(state="done", stage=None,
             message=f"{k} topics built from {n:,} passages.",
             finished_at=time.strftime("%H:%M"))
    except Exception as exc:
        _set(state="error", stage=None, message=str(exc))
    finally:
        with _lock:
            _running = False


def _judge_repeats() -> None:
    """
    v0.9.1: after topics exist, let the AI settle the borderline "same
    statement?" pairs (facts.py). Never blocks a build: skipped when the AI
    isn't running, and any failure is ignored (rules alone still apply).
    """
    try:
        from . import facts, understand
        if facts.ai_ready():
            _set(stage="repeats", done=0, total=1, message="Checking which statements repeat each other…")
            facts.judge_all(lambda n, total: _set(done=n, total=total))
            _set(stage="understanding", done=0, total=1, message="Working out what each point is for and how things connect…")
            understand.tag_all(lambda n, total: _set(done=n, total=total))
    except Exception:
        pass


def _save(ids, labels, fit, groups, names, links, k) -> None:
    """
    Replace all topics in ONE transaction.

    Written articles (Phase 3) and their lessons (v0.6) are carried over: each new topic that shares
    at least 60% of its passages with an old written topic (Jaccard
    similarity) inherits that article, so rebuilding topics after adding a
    few files doesn't throw away hours of overnight writing. Topics that
    changed a lot are marked unwritten and get a fresh article next run.
    """
    with db.connect() as conn:
        old_written: list[dict] = []
        for t in conn.execute(
            "SELECT id, status, body_markdown, citations, model_used, written_at FROM topics "
            "WHERE status = 'written' OR id IN (SELECT topic_id FROM lessons)"
        ).fetchall():
            members = {r[0] for r in conn.execute(
                "SELECT passage_id FROM topic_passages WHERE topic_id = ?", (t["id"],))}
            lesson = conn.execute("SELECT spec_json, checks_json, model_used FROM lessons WHERE topic_id = ?",
                                  (t["id"],)).fetchone()
            old_written.append({**dict(t), "members": members, "lesson": dict(lesson) if lesson else None})

        conn.execute("UPDATE passages SET cluster_id = NULL")
        conn.executemany(
            "UPDATE passages SET cluster_id = ? WHERE id = ?",
            [(int(g), int(i)) for g, i in zip(groups, ids)],
        )
        conn.execute("DELETE FROM topics")  # cascades links/memberships/conflicts
        topic_ids: list[int] = []
        used_slugs: set[str] = set()
        for t in range(k):
            title, summary = names[t]
            slug = base = _slugify(title)
            n = 2
            while slug in used_slugs:
                slug, n = f"{base}-{n}", n + 1
            used_slugs.add(slug)
            cur = conn.execute(
                "INSERT INTO topics(slug, title, summary, status) VALUES (?, ?, ?, 'draft')",
                (slug, title, summary or None),
            )
            topic_ids.append(cur.lastrowid)
        conn.executemany(
            "INSERT INTO topic_passages(topic_id, passage_id, fit) VALUES (?, ?, ?)",
            [(topic_ids[int(l)], int(i), float(f)) for l, i, f in zip(labels, ids, fit)],
        )
        conn.executemany(
            "INSERT OR REPLACE INTO topic_links(from_topic_id, to_topic_id, relation, weight) "
            "VALUES (?, ?, 'related', ?)",
            [(topic_ids[a], topic_ids[b], w) for a, b, w in links],
        )

        # Carry articles over to matching new topics.
        if old_written:
            new_members: dict[int, set[int]] = {}
            for l, i in zip(labels, ids):
                new_members.setdefault(int(l), set()).add(int(i))
            for t, members in new_members.items():
                best, best_score = None, 0.0
                for old in old_written:
                    union = len(members | old["members"])
                    score = len(members & old["members"]) / union if union else 0.0
                    if score > best_score:
                        best, best_score = old, score
                if best and best_score >= 0.6 and best["status"] == "written":
                    conn.execute(
                        "UPDATE topics SET body_markdown = ?, citations = ?, model_used = ?, "
                        "written_at = ?, status = 'written' WHERE id = ?",
                        (best["body_markdown"], best["citations"], best["model_used"],
                         best["written_at"], topic_ids[t]),
                    )
                if best and best_score >= 0.6:
                    if best["lesson"]:  # the topic's visual lesson moves with it (even without an article)
                        conn.execute(
                            "INSERT OR REPLACE INTO lessons(topic_id, spec_json, checks_json, model_used) "
                            "VALUES (?, ?, ?, ?)",
                            (topic_ids[t], best["lesson"]["spec_json"], best["lesson"]["checks_json"],
                             best["lesson"]["model_used"]),
                        )


# ---------------------------------------------------------------------------
# Reading topics (Topics screen)
# ---------------------------------------------------------------------------

def list_topics() -> dict:
    """
    Every topic with its size: passages, distinct points (repeat groups),
    files it draws on, and how many passages fit it only loosely. Largest
    first. Also the topic links, for the map.
    """
    with db.connect() as conn:
        rows = conn.execute(
            """
            SELECT t.id, t.slug, t.title, t.summary, t.status, t.written_at, t.kind,
                   EXISTS(SELECT 1 FROM lessons l WHERE l.topic_id = t.id) AS has_lesson,
                   COUNT(tp.passage_id)                AS passages,
                   COUNT(DISTINCT p.cluster_id)        AS points,
                   COUNT(DISTINCT p.source_id)         AS sources,
                   SUM(CASE WHEN tp.fit < ? THEN 1 ELSE 0 END) AS loose
            FROM topics t
            LEFT JOIN topic_passages tp ON tp.topic_id = t.id
            LEFT JOIN passages p ON p.id = tp.passage_id
            GROUP BY t.id
            ORDER BY passages DESC
            """,
            (LOOSE_FIT,),
        ).fetchall()
        links = conn.execute(
            "SELECT from_topic_id AS a, to_topic_id AS b, weight FROM topic_links"
        ).fetchall()
    return {"topics": [dict(r) for r in rows], "links": [dict(l) for l in links],
            "last_run": db.get_setting("distill_last_run"), "pending": pending_count()}


def topic_detail(topic_id: int, limit: int = 300) -> dict | None:
    """
    One topic: its points (repeat groups), most central first. Each point
    shows its text once plus every file + page that said it, the document
    part it comes from (section) and its position for reading order.
    """
    with db.connect() as conn:
        t = conn.execute(
            "SELECT id, slug, title, summary, status, body_markdown, citations, model_used, written_at, kind, checks_json "
            "FROM topics WHERE id = ?", (topic_id,)).fetchone()
        if not t:
            return None
        related = conn.execute(
            """
            SELECT t.id, t.title, l.weight FROM topic_links l
            JOIN topics t ON t.id = CASE WHEN l.from_topic_id = ? THEN l.to_topic_id ELSE l.from_topic_id END
            WHERE l.from_topic_id = ? OR l.to_topic_id = ?
            ORDER BY l.weight DESC
            """,
            (topic_id, topic_id, topic_id),
        ).fetchall()
    # v0.9.1: repeated statements are folded (facts.py) — a point shows each
    # statement once and lists every file + page that said it.
    from . import facts, understand
    with db.connect() as conn:
        folded, absorbed, fstats = facts.topic_points(conn, topic_id)
    points = {p["id"]: p for p in folded[:limit]}

    # Article markers [n] → the point (repeat group) they cite. Stored
    # citations hold passage ids; map each to its current group so the link
    # survives a topic rebuild.
    citations: dict[str, int] = {}
    raw = json.loads(t["citations"]) if t["citations"] else {}
    if raw:
        with db.connect() as conn:
            for marker, pid in raw.items():
                row = conn.execute("SELECT cluster_id FROM passages WHERE id = ?", (pid,)).fetchone()
                if row:
                    key = row["cluster_id"] or pid
                    citations[marker] = absorbed.get(key, key)
    topic = {k: t[k] for k in ("id", "slug", "title", "summary", "status", "model_used", "written_at", "kind")}
    topic["article"] = t["body_markdown"] if t["status"] == "written" else None
    topic["checks"] = json.loads(t["checks_json"]) if t["checks_json"] else None
    return {"topic": topic, "points": list(points.values()), "citations": citations,
            "folded": fstats["merged"],
            "structure": understand.structure(folded, fstats["conflicts"], topic.get("kind", "subject")),
            "related": [dict(x) for x in related], "loose_threshold": LOOSE_FIT}


def passage_context(passage_id: int, around: int = 1) -> dict | None:
    """
    "Read in context": the passage plus the `around` passages just before
    and after it in the same file (by page, then position on the page), so
    a point that starts mid-way ("Step 3 …") can be read with what came
    before and after it. RETURNS {"file_name", "section", "passages": [...]}.
    """
    with db.connect() as conn:
        me = conn.execute(
            "SELECT p.id, p.source_id, p.page_number, p.ordinal, p.section, COALESCE(s.title, s.file_name) AS file_name FROM passages p "
            "JOIN sources s ON s.id = p.source_id WHERE p.id = ?", (passage_id,)).fetchone()
        if not me:
            return None
        before = conn.execute(
            "SELECT id, text, page_number, section FROM passages WHERE source_id = ? AND "
            "(page_number < ? OR (page_number = ? AND ordinal < ?)) "
            "ORDER BY page_number DESC, ordinal DESC LIMIT ?",
            (me["source_id"], me["page_number"], me["page_number"], me["ordinal"], around)).fetchall()
        here = conn.execute("SELECT id, text, page_number, section FROM passages WHERE id = ?",
                            (passage_id,)).fetchone()
        after = conn.execute(
            "SELECT id, text, page_number, section FROM passages WHERE source_id = ? AND "
            "(page_number > ? OR (page_number = ? AND ordinal > ?)) "
            "ORDER BY page_number, ordinal LIMIT ?",
            (me["source_id"], me["page_number"], me["page_number"], me["ordinal"], around)).fetchall()
    rows = [*reversed(before), here, *after]
    return {"file_name": me["file_name"], "section": me["section"],
            "passages": [{"id": r["id"], "text": r["text"], "page": r["page_number"],
                          "section": r["section"], "current": r["id"] == passage_id} for r in rows]}


def section_passages(passage_id: int, limit: int = 60) -> dict | None:
    """
    "Read the whole section": every passage of the same file and document
    part (section) as this one, in reading order — e.g. the full "Use Case
    7: DLL Sideloading" write-up, including parts that belong to other
    topics. Falls back to passage_context when the passage has no section.
    """
    with db.connect() as conn:
        me = conn.execute("SELECT p.source_id, p.section, COALESCE(s.title, s.file_name) AS file_name FROM passages p JOIN sources s "
                          "ON s.id = p.source_id WHERE p.id = ?", (passage_id,)).fetchone()
        if not me:
            return None
        if not me["section"]:
            return passage_context(passage_id, around=2)
        rows = conn.execute(
            "SELECT id, text, page_number, section FROM passages WHERE source_id = ? AND section = ? "
            "ORDER BY page_number, ordinal LIMIT ?", (me["source_id"], me["section"], limit)).fetchall()
    return {"file_name": me["file_name"], "section": me["section"],
            "passages": [{"id": r["id"], "text": r["text"], "page": r["page_number"],
                          "section": r["section"], "current": r["id"] == passage_id} for r in rows]}


def flow() -> dict:
    """
    Data for the Overview flow map (FlowMap.jsx): which files feed which
    topics and how much. RETURNS {"files": [{id, name, type, passages}],
    "topics": [{id, title, passages}], "links": [{file, topic, passages}]}.
    Cheap: three grouped counts, no AI.
    """
    with db.connect() as conn:
        files = conn.execute(
            "SELECT s.id, COALESCE(s.title, s.file_name) AS file_name, s.file_type, COUNT(p.id) AS n FROM sources s "
            "JOIN passages p ON p.source_id = s.id GROUP BY s.id ORDER BY s.id").fetchall()
        topics = conn.execute(
            "SELECT t.id, t.title, COUNT(tp.passage_id) AS n FROM topics t "
            "JOIN topic_passages tp ON tp.topic_id = t.id GROUP BY t.id ORDER BY n DESC").fetchall()
        links = conn.execute(
            "SELECT p.source_id AS f, tp.topic_id AS t, COUNT(*) AS n FROM topic_passages tp "
            "JOIN passages p ON p.id = tp.passage_id GROUP BY p.source_id, tp.topic_id").fetchall()
    return {"files": [{"id": r["id"], "name": r["file_name"], "type": r["file_type"], "passages": r["n"]} for r in files],
            "topics": [{"id": r["id"], "title": r["title"], "passages": r["n"]} for r in topics],
            "links": [{"file": r["f"], "topic": r["t"], "passages": r["n"]} for r in links]}


def topic_map() -> dict:
    """
    Data for the animated topic map (TopicMap.jsx): every topic with its size
    and status, and the links between related topics (topic_links, made in
    stage 4 of Build topics). RETURNS {"nodes": [...], "links": [...]}.
    """
    with db.connect() as conn:
        nodes = conn.execute(
            """SELECT t.id, t.title, t.status, t.kind, COUNT(tp.passage_id) AS passages,
                      EXISTS(SELECT 1 FROM lessons l WHERE l.topic_id = t.id) AS has_lesson
               FROM topics t LEFT JOIN topic_passages tp ON tp.topic_id = t.id GROUP BY t.id""").fetchall()
        links = conn.execute("SELECT from_topic_id, to_topic_id, weight FROM topic_links").fetchall()
    # Weights rescaled to 0–1 for drawing (line width / pull strength).
    top = max([r["weight"] for r in links] or [1.0]) or 1.0
    return {"nodes": [dict(r) for r in nodes],
            "links": [{"source": r["from_topic_id"], "target": r["to_topic_id"],
                       "weight": round(max(0.1, r["weight"] / top), 3)} for r in links]}
