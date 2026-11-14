/**
 * Topics.jsx — Phase 2 screen: build topics and explore them.
 *
 * WHAT:  1. "Build topics" panel: starts the distil job and shows its live
 *           progress as five named stages (Reading meaning → Grouping →
 *           Repeats → Connections → Naming).
 *        2. Results of the last run: topics, repeats merged, loose fits,
 *           coverage.
 *        3. A colourful grid of topic cards, largest first, each with its
 *           summary and how many distinct points, files and loose fits it has.
 *        4. Topic detail (click a card): every distinct point once, in the
 *           reading font, with every file + page that said it, and related
 *           topics you can jump to. Loose fits are marked for review.
 * WHY:   This is where "many PDFs, same knowledge, different words" becomes
 *        one organised list without repeats — and where the owner checks
 *        nothing was missed (coverage, loose fits) before Phase 3 writes the
 *        merged articles.
 * WHEN:  When "Topics" is chosen in the side rail. Polls job status every
 *        1.5 s; reloads the topic list when a run finishes.
 * CONNECTED TO: bridge.js → engine POST /distill/start, GET /distill/status,
 *        GET /topics, GET /topic (server.py → distill.py); icons.jsx.
 */
import { useEffect, useRef, useState } from "react";
import Icon from "./icons.jsx";
import { formatCount, kb, percent, usePoll } from "./bridge.js";

/** The job's stages in order, with the words the owner sees. */
const STAGES = [
  ["embed", "Reading meaning"],
  ["topics", "Grouping"],
  ["repeats", "Repeats"],
  ["links", "Connections"],
  ["names", "Naming"],
];

/** Card colours cycle through the theme's four accents. */
const TONES = ["teal", "coral", "violet", "mustard"];

export default function Topics() {
  const [status] = usePoll("/distill/status", 1500);
  const [list, reloadList] = usePoll("/topics", 0);
  const [openId, setOpenId] = useState(null);
  const [notice, setNotice] = useState("");
  const lastState = useRef(null);

  // When a run finishes, refresh the topic list automatically.
  useEffect(() => {
    if (lastState.current === "running" && status?.state !== "running") reloadList();
    lastState.current = status?.state;
  }, [status?.state, reloadList]);

  async function build() {
    setNotice("");
    const r = await kb.post("/distill/start", {});
    if (r.error) setNotice(r.error);
  }

  if (openId !== null) {
    return <TopicDetail id={openId} onBack={() => setOpenId(null)} onOpen={setOpenId} />;
  }

  const running = status?.state === "running";
  const run = list?.last_run;
  const topics = list?.topics ?? [];

  return (
    <div className="topics">
      <header className="page-head">
        <h1>Topics</h1>
        <p className="lede">
          Everything your files say, grouped by subject. Passages that repeat each other are joined
          into one point, with every file and page that said it.
        </p>
      </header>

      <section className="card build" aria-label="Build topics">
        <div className="build-row">
          <div>
            <h2>{topics.length ? "Rebuild topics" : "Build your topics"}</h2>
            <p className="muted">
              Run this after importing new files. It uses the AI models on this laptop and takes a
              few minutes for a large library.
            </p>
          </div>
          <button className="primary" onClick={build} disabled={running}>
            <Icon name="sparkle" size={18} />
            {running ? "Building…" : topics.length ? "Rebuild topics" : "Build topics"}
          </button>
        </div>

        {running && (
          <div className="stages" aria-live="polite">
            <ol>
              {STAGES.map(([key, label], i) => {
                const current = STAGES.findIndex(([k]) => k === status.stage);
                const state = i < current ? "done" : i === current ? "now" : "later";
                return (
                  <li key={key} className={`stage-${state}`}>
                    <span className="stage-dot" aria-hidden="true">
                      {state === "done" ? <Icon name="check" size={14} /> : i + 1}
                    </span>
                    {label}
                  </li>
                );
              })}
            </ol>
            <p className="small muted">{status.message}</p>
            {status.total > 1 && (
              <div className="bar">
                <div style={{ width: `${percent(status.done, status.total)}%` }} />
              </div>
            )}
          </div>
        )}
        {status?.state === "error" && <p className="notice error">{status.message}</p>}
        {notice && <p className="notice error">{notice}</p>}
      </section>

      {run && (
        <section className="tiles" aria-label="Last run">
          <div className="tile tone-violet">
            <p className="tile-value">{formatCount(run.topics)}</p>
            <p className="tile-label">Topics</p>
          </div>
          <div className="tile tone-coral">
            <p className="tile-value">{formatCount(run.repeat_groups_merged)}</p>
            <p className="tile-label">Repeated passages merged</p>
          </div>
          <div className="tile tone-mustard">
            <p className="tile-value">{formatCount(run.loose_passages)}</p>
            <p className="tile-label">Loose fits to review</p>
          </div>
          <div className="tile tone-teal">
            <p className="tile-value">{run.coverage_percent}%</p>
            <p className="tile-label">Passages covered</p>
          </div>
        </section>
      )}
      {run && (
        <p className="small muted run-meta">
          Built {run.at} from {formatCount(run.passages)} passages in {run.seconds}s. Named by{" "}
          {run.named_with === "keywords" ? "keywords (AI model not available)" : run.named_with}.
        </p>
      )}

      {topics.length === 0 && !running && (
        <section className="card empty">
          <Icon name="topics" size={28} />
          <p>No topics yet. Import files in the Library, then press Build topics.</p>
        </section>
      )}

      {topics.length > 0 && (
        <ul className="topic-grid" aria-label="Topics">
          {topics.map((t, i) => (
            <li key={t.id}>
              <button className={`topic-card tone-${TONES[i % TONES.length]}`} onClick={() => setOpenId(t.id)}>
                <span className="topic-bar" aria-hidden="true" />
                <span className="topic-title">{t.title}</span>
                {t.summary && <span className="topic-summary">{t.summary}</span>}
                <span className="topic-meta">
                  <span>{formatCount(t.points)} points</span>
                  <span>{formatCount(t.sources)} files</span>
                  {t.loose > 0 && <span className="loose">{t.loose} loose</span>}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/**
 * One topic: its distinct points with sources, plus related topics.
 * onOpen(id) jumps to a related topic; onBack returns to the grid.
 */
function TopicDetail({ id, onBack, onOpen }) {
  const [data] = usePoll("/topic", 0, { id });

  if (!data) return <p className="muted">Loading topic…</p>;
  const { topic, points, related, loose_threshold } = data;

  return (
    <div className="topic-detail">
      <button className="ghost back" onClick={onBack}>
        <Icon name="arrow-left" size={18} />
        All topics
      </button>

      <header className="topic-hero">
        <h1>{topic.title}</h1>
        {topic.summary && <p>{topic.summary}</p>}
        <p className="hero-meta">
          {formatCount(points.length)} distinct points. A merged, written article for this topic arrives
          in the next update.
        </p>
      </header>

      {related.length > 0 && (
        <section className="related" aria-label="Related topics">
          <h2>Related</h2>
          <ul>
            {related.map((r) => (
              <li key={r.id}>
                <button className="chip-button" onClick={() => onOpen(r.id)}>
                  {r.title}
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}

      <ol className="points">
        {points.map((p) => (
          <li key={p.id} className={p.fit < loose_threshold ? "is-loose" : ""}>
            {p.fit < loose_threshold && (
              <p className="loose-flag">
                <Icon name="alert" size={15} /> Loose fit: may belong to another topic
              </p>
            )}
            <p className="point-text">{p.text}</p>
            <ul className="point-sources" aria-label="Sources">
              {p.sources.map((s, i) => (
                <li key={i}>
                  <Icon name="file" size={14} />
                  {s.file_name} <span>p.{s.page}</span>
                </li>
              ))}
            </ul>
            {p.sources.length > 1 && (
              <p className="small muted">Said in {p.sources.length} places, shown once.</p>
            )}
          </li>
        ))}
      </ol>
    </div>
  );
}
