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
 *        5. Topic detail with three tabs:
 *             Lesson        — the automatic visual lesson (Lesson.jsx):
 *                             steps with diagrams, a quiz, fact-check note.
 *                             Shown first whenever a lesson exists.
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
import { lazy, Suspense, useEffect, useRef, useState } from "react";
import Icon from "./icons.jsx";
import { Formatted, Markdown } from "./Formatted.jsx";
// The lesson view carries the diagram layout engine (~1.4 MB), so it loads
// only when a lesson is first opened — app start-up stays quick.
const Lesson = lazy(() => import("./Lesson.jsx"));
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
  const lessons = topics.filter((t) => t.has_lesson).length;
  const allDone = written === topics.length && lessons === topics.length;

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
            <h2>2. Write articles and lessons</h2>
            <p className="muted">
              {topics.length
                ? `${written} of ${topics.length} articles and ${lessons} lessons ready. Each topic gets a written article and a step-by-step visual lesson, about 2 minutes per topic — leave it running overnight for a big library.`
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
              <button onClick={() => post("/write/start", { rewrite_all: false })} disabled={!topics.length || building || allDone}>
                <Icon name="sparkle" size={18} />
                {written === 0 && lessons === 0 ? "Write articles and lessons" : allDone ? "All written" : "Write remaining"}
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
                  {Boolean(t.has_lesson) && (
                    <span className="ready lesson-ready">
                      <Icon name="sparkle" size={13} /> Lesson ready
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
 * One topic: Lesson tab, Article tab (with clickable citations) and Source points tab.
 * onOpen(id) jumps to a related topic; onBack returns to the grid.
 */
function TopicDetail({ id, onBack, onOpen }) {
  const [data] = usePoll("/topic", 0, { id });
  const [lessonData] = usePoll("/lesson", 0, { id });
  const [tab, setTab] = useState(null);
  const [cited, setCited] = useState(null); // point shown in the side panel

  if (!data) return <p className="muted">Loading topic…</p>;
  const { topic, points, related, citations, loose_threshold } = data;
  const hasArticle = Boolean(topic.article);
  const hasLesson = Boolean(lessonData?.lesson);
  const view = tab ?? (hasLesson ? "lesson" : hasArticle ? "article" : "points");
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
        <button role="tab" aria-selected={view === "lesson"} className={view === "lesson" ? "tab on" : "tab"} onClick={() => setTab("lesson")}>
          Lesson
        </button>
        <button role="tab" aria-selected={view === "article"} className={view === "article" ? "tab on" : "tab"} onClick={() => setTab("article")}>
          Article
        </button>
        <button role="tab" aria-selected={view === "points"} className={view === "points" ? "tab on" : "tab"} onClick={() => setTab("points")}>
          Source points <span className="tab-count">{points.length}</span>
        </button>
      </div>

      {view === "lesson" && (
        // Diagrams keep the full width (so their text stays readable); a
        // clicked source opens just below the lesson instead of beside it.
        <div className="lesson-full">
          <Suspense fallback={<p className="muted">Loading lesson…</p>}>
            <Lesson topicId={id} onCite={(n, pointId) => byId[pointId] && setCited({ n, point: byId[pointId] })} />
          </Suspense>
          {cited && <CitePanel cited={cited} onClose={() => setCited(null)} />}
        </div>
      )}

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
            <CitePanel cited={cited} hint="Click any numbered chip in the article to see the exact text it came from, with its file and page." />
          )}
        </div>
      )}

      {view === "points" && <SourcePoints points={points} looseThreshold={loose_threshold} />}
    </div>
  );
}

/**
 * Source points tab (v0.6.1 — owner: "no context, random Step 3 / Step 5").
 * WHAT: - "In reading order" (default): points sorted by file, page and
 *         position, grouped under the document part they come from
 *         ("Use Case 7: Insider Data Theft"), so steps read 1 → 2 → 3.
 *       - "Best match first": the old order, most central to the topic first.
 *       - Every point has "Read in context": the text just before and after
 *         it in its file (GET /passage/context).
 */
function SourcePoints({ points, looseThreshold }) {
  const [order, setOrder] = useState("reading");
  const sorted =
    order === "central"
      ? points
      : [...points].sort((a, b) => {
          const x = a.order ?? [0, 0, a.id];
          const y = b.order ?? [0, 0, b.id];
          return x[0] - y[0] || x[1] - y[1] || x[2] - y[2];
        });
  let lastGroup = null;
  return (
    <div>
      <div className="points-bar" role="group" aria-label="Order of points">
        <button className={order === "reading" ? "seg on" : "seg"} onClick={() => setOrder("reading")} aria-pressed={order === "reading"}>
          In reading order
        </button>
        <button className={order === "central" ? "seg on" : "seg"} onClick={() => setOrder("central")} aria-pressed={order === "central"}>
          Best match first
        </button>
      </div>
      <ol className="points">
        {sorted.map((p) => {
          const group = `${p.sources[0]?.file_name ?? ""} › ${p.section ?? ""}`;
          const showGroup = order === "reading" && group !== lastGroup;
          lastGroup = group;
          return (
            <li key={p.id} className={p.fit < looseThreshold ? "is-loose" : ""}>
              {showGroup && (
                <p className="point-group">
                  <Icon name="file" size={14} />
                  <span>{p.sources[0]?.file_name}</span>
                  {p.section && <strong>{p.section}</strong>}
                </p>
              )}
              {order === "central" && p.section && <p className="point-section">From: {p.section}</p>}
              {p.fit < looseThreshold && (
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
              {p.passage_id && <InContext passageId={p.passage_id} />}
            </li>
          );
        })}
      </ol>
    </div>
  );
}

/** "Read in context": loads the passages just before and after this one. */
function InContext({ passageId }) {
  const [open, setOpen] = useState(false);
  const [data, setData] = useState(null);
  async function toggle() {
    if (!open && !data) {
      const r = await kb.get("/passage/context", { id: passageId });
      if (!r.error) setData(r);
    }
    setOpen(!open);
  }
  return (
    <div className="in-context">
      <button className="link small" onClick={toggle} aria-expanded={open}>
        {open ? "Hide context" : "Read in context"}
      </button>
      {open && data && (
        <div className="context-box">
          {data.passages.map((c) =>
            c.current ? (
              <p key={c.id} className="context-here small">This point · page {c.page}</p>
            ) : (
              <div key={c.id} className="context-part">
                <p className="small muted">
                  {c.id < passageId ? "Just before" : "Just after"} · page {c.page}
                </p>
                <Formatted text={c.text} collapseAt={12} />
              </div>
            )
          )}
        </div>
      )}
    </div>
  );
}

/**
 * Side panel showing one cited point: its exact text and every file + page
 * that said it. Used by both the Lesson and Article tabs.
 */
function CitePanel({ cited, hint, onClose }) {
  const ref = useRef(null);
  // Below a lesson the panel can be off-screen: bring it into view on open.
  useEffect(() => {
    if (onClose && cited) ref.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [cited, onClose]);
  return (
    <aside className="card source-panel" aria-live="polite" ref={ref}>
      {cited ? (
        <>
          <p className="source-panel-head">
            <span className="cite static">{cited.n}</span> Source
            {onClose && (
              <button className="link small close" onClick={onClose}>
                Close
              </button>
            )}
          </p>
          {cited.point.section && <p className="point-section">From: {cited.point.section}</p>}
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
        <p className="muted small">{hint}</p>
      )}
    </aside>
  );
}
