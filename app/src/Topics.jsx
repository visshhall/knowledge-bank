/**
 * Topics.jsx — Phases 2 + 3 screen: build topics, write articles, read them.
 *
 * WHAT:  1. "Build topics" panel: starts the distil job and shows its five
 *           live stages (Reading meaning → Grouping → Repeats → Connections
 *           → Naming).
 *        2. "Write articles" panel: starts the writer job (Phase 3) with live
 *           progress (current topic, n of N, elapsed time) and Cancel.
 *        3. Results of the last build: topics, repeats merged, loose fits,
 *           coverage.
 *        4. Colourful topic cards (largest first) marked "Article ready"
 *           once written.
 *        5. Topic detail with two tabs:
 *             Article       — the written article (Formatted.jsx Markdown):
 *                             coloured sections, bullets, steps, query
 *                             blocks with Copy, MITRE/event tags, and
 *                             citation chips; clicking a chip opens that
 *                             source (text + file + page) in the side panel.
 *             Source points — every distinct point once, structured and
 *                             collapsible, with all its files + pages.
 * WHY:   Owner feedback (14 Nov 2026): raw passages shown as one big block
 *        were unreadable. Articles turn each topic into a clean study page,
 *        and every line can still be checked against its source in one click.
 * WHEN:  When "Topics" is chosen in the side rail. Polls the two jobs every
 *        1.5 s; reloads topics when a job finishes.
 * CONNECTED TO: bridge.js → engine /distill/*, /write/*, /topics, /topic
 *        (server.py → distill.py, writer.py); Formatted.jsx; icons.jsx.
 */
import { useEffect, useRef, useState } from "react";
import Icon from "./icons.jsx";
import { Formatted, Markdown } from "./Formatted.jsx";
import { formatCount, kb, percent, usePoll } from "./bridge.js";

/** The distil job's stages in order, with the words the owner sees. */
const STAGES = [
  ["embed", "Reading meaning"],
  ["topics", "Grouping"],
  ["repeats", "Repeats"],
  ["links", "Connections"],
  ["names", "Naming"],
];

/** Card colours cycle through the theme's four accents. */
const TONES = ["teal", "coral", "violet", "mustard"];

/** "12 min" / "45 s" since a Unix timestamp (seconds). */
function since(ts) {
  if (!ts) return "";
  const s = Math.max(0, Math.round(Date.now() / 1000 - ts));
  return s >= 60 ? `${Math.floor(s / 60)} min` : `${s} s`;
}

export default function Topics() {
  const [status] = usePoll("/distill/status", 1500);
  const [write] = usePoll("/write/status", 1500);
  const [list, reloadList] = usePoll("/topics", 0);
  const [openId, setOpenId] = useState(null);
  const [notice, setNotice] = useState("");
  const lastDistill = useRef(null);
  const lastWrite = useRef(null);

  // When either job finishes, refresh the topic list automatically.
  useEffect(() => {
    if (lastDistill.current === "running" && status?.state !== "running") reloadList();
    lastDistill.current = status?.state;
  }, [status?.state, reloadList]);
  useEffect(() => {
    if (lastWrite.current === "running" && write?.state !== "running") reloadList();
    if (write?.state === "running" && write?.done !== lastWrite.doneSeen) {
      lastWrite.doneSeen = write?.done;
      reloadList(); // show "Article ready" badges as articles land
    }
    lastWrite.current = write?.state;
  }, [write?.state, write?.done, reloadList]);

  async function post(path, body = {}) {
    setNotice("");
    const r = await kb.post(path, body);
    if (r.error || r.ok === false) setNotice(r.error || r.message);
  }

  if (openId !== null) {
    return <TopicDetail id={openId} onBack={() => setOpenId(null)} onOpen={setOpenId} />;
  }

  const building = status?.state === "running";
  const writing = write?.state === "running";
  const run = list?.last_run;
  const topics = list?.topics ?? [];
  const written = topics.filter((t) => t.status === "written").length;

  return (
    <div className="topics">
      <header className="page-head">
        <h1>Topics</h1>
        <p className="lede">
          Everything your files say, grouped by subject and written up as one clean page per topic.
          Every line links back to the file and page it came from.
        </p>
      </header>

      <div className="job-row">
        <section className="card job" aria-label="Build topics">
          <span className="job-icon tone-violet" aria-hidden="true">
            <Icon name="topics" size={22} />
          </span>
          <div className="job-body">
            <h2>1. Build topics</h2>
            <p className="muted">Group passages by subject and merge repeats. Run again after importing files.</p>
            {building ? (
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
            ) : (
              <button onClick={() => post("/distill/start")} disabled={writing}>
                <Icon name="sparkle" size={18} />
                {topics.length ? "Rebuild topics" : "Build topics"}
              </button>
            )}
            {status?.state === "error" && <p className="notice error">{status.message}</p>}
          </div>
        </section>

        <section className="card job" aria-label="Write articles">
          <span className="job-icon tone-coral" aria-hidden="true">
            <Icon name="library" size={22} />
          </span>
          <div className="job-body">
            <h2>2. Write articles</h2>
            <p className="muted">
              {topics.length
                ? `${written} of ${topics.length} topics written. About 1 minute per topic — leave it running overnight for a big library.`
                : "Available after topics are built."}
            </p>
            {writing ? (
              <div aria-live="polite">
                <p className="small">
                  <strong>{write.current || "Starting"}</strong>
                  <span className="muted"> — {write.message}</span>
                </p>
                <div className="bar coral">
                  <div style={{ width: `${percent(write.done, write.total)}%` }} />
                </div>
                <p className="small muted">
                  {write.done} of {write.total} done, running {since(write.started_at)}. Model {write.model}.
                </p>
                <button className="secondary" onClick={() => post("/write/cancel")}>
                  Stop after this article
                </button>
              </div>
            ) : (
              <button onClick={() => post("/write/start", { rewrite_all: false })} disabled={!topics.length || building || written === topics.length}>
                <Icon name="sparkle" size={18} />
                {written === 0 ? "Write articles" : written < topics.length ? "Write remaining" : "All written"}
              </button>
            )}
            {write?.state === "error" && <p className="notice error">{write.message}</p>}
          </div>
        </section>
      </div>
      {notice && <p className="notice error">{notice}</p>}

      {run && (
        <section className="tiles" aria-label="Last build">
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

      {topics.length === 0 && !building && (
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
                  {t.status === "written" && (
                    <span className="ready">
                      <Icon name="check" size={13} /> Article ready
                    </span>
                  )}
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
 * One topic: Article tab (with clickable citations) and Source points tab.
 * onOpen(id) jumps to a related topic; onBack returns to the grid.
 */
function TopicDetail({ id, onBack, onOpen }) {
  const [data] = usePoll("/topic", 0, { id });
  const [tab, setTab] = useState(null);
  const [cited, setCited] = useState(null); // point shown in the side panel

  if (!data) return <p className="muted">Loading topic…</p>;
  const { topic, points, related, citations, loose_threshold } = data;
  const hasArticle = Boolean(topic.article);
  const view = tab ?? (hasArticle ? "article" : "points");
  const byId = Object.fromEntries(points.map((p) => [p.id, p]));

  function openCitation(n) {
    const point = byId[citations?.[n]];
    if (point) setCited({ n, point });
  }

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
          {formatCount(points.length)} distinct points
          {hasArticle ? ` · article written by ${topic.model_used}` : " · article not written yet"}
        </p>
      </header>

      {related.length > 0 && (
        <section className="related" aria-label="Related topics">
          <h2>Related</h2>
          <ul>
            {related.map((r) => (
              <li key={r.id}>
                <button className="chip-button" onClick={() => { setCited(null); setTab(null); onOpen(r.id); }}>
                  {r.title}
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}

      <div className="tabs" role="tablist" aria-label="Topic views">
        <button role="tab" aria-selected={view === "article"} className={view === "article" ? "tab on" : "tab"} onClick={() => setTab("article")}>
          Article
        </button>
        <button role="tab" aria-selected={view === "points"} className={view === "points" ? "tab on" : "tab"} onClick={() => setTab("points")}>
          Source points <span className="tab-count">{points.length}</span>
        </button>
      </div>

      {view === "article" && (
        <div className="article-layout">
          <article className="card article">
            {hasArticle ? (
              <Markdown text={topic.article} onCite={openCitation} />
            ) : (
              <p className="muted">
                This topic doesn't have a written article yet. Go back and press Write articles — meanwhile,
                the Source points tab shows everything this topic contains.
              </p>
            )}
          </article>
          {hasArticle && (
            <aside className="card source-panel" aria-live="polite">
              {cited ? (
                <>
                  <p className="source-panel-head">
                    <span className="cite static">{cited.n}</span> Source
                  </p>
                  <Formatted text={cited.point.text} collapseAt={10} />
                  <ul className="point-sources">
                    {cited.point.sources.map((s, i) => (
                      <li key={i}>
                        <Icon name="file" size={14} />
                        {s.file_name} <span>p.{s.page}</span>
                      </li>
                    ))}
                  </ul>
                </>
              ) : (
                <p className="muted small">
                  Click any numbered chip in the article to see the exact text it came from, with its file
                  and page.
                </p>
              )}
            </aside>
          )}
        </div>
      )}

      {view === "points" && (
        <ol className="points">
          {points.map((p) => (
            <li key={p.id} className={p.fit < loose_threshold ? "is-loose" : ""}>
              {p.fit < loose_threshold && (
                <p className="loose-flag">
                  <Icon name="alert" size={15} /> Loose fit: may belong to another topic
                </p>
              )}
              <Formatted text={p.text} />
              <ul className="point-sources" aria-label="Sources">
                {p.sources.map((s, i) => (
                  <li key={i}>
                    <Icon name="file" size={14} />
                    {s.file_name} <span>p.{s.page}</span>
                  </li>
                ))}
              </ul>
              {p.sources.length > 1 && <p className="small muted">Said in {p.sources.length} places, shown once.</p>}
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
