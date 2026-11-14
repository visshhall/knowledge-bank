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
import SourceChip from "./SourceChip.jsx";
import { Formatted, Markdown } from "./Formatted.jsx";
// The lesson view carries the diagram layout engine (~1.4 MB), so it loads
// only when a lesson is first opened — app start-up stays quick.
const Lesson = lazy(() => import("./Lesson.jsx"));
const TopicMap = lazy(() => import("./TopicMap.jsx"));
const Visual = lazy(() => import("./Diagrams.jsx"));

/**
 * Put the lesson's diagrams into the article (v0.8): each diagram goes at the
 * end of the article section that shares the most words with its step, at
 * most one per section. Tables and the Subnet Lab stay in the lesson only.
 * RETURNS {sectionIndex: {step, visual}}.
 */
function figuresFor(article, lesson) {
  if (!article || !lesson?.steps) return {};
  const sections = article.split(/\n(?=#{2,3}\s)/).filter((x) => /^#{2,3}\s/.test(x.trim()));
  const words = (t) => new Set(String(t).toLowerCase().match(/[a-z0-9]{4,}/g) || []);
  const secWords = sections.map(words);
  const out = {};
  for (const step of lesson.steps) {
    if (!step.visual || ["table", "subnetlab", "ipcalc", "verify"].includes(step.visual.type)) continue;
    const w = words(`${step.title} ${step.text} ${JSON.stringify(step.visual)}`);
    let best = -1;
    let score = 0;
    secWords.forEach((sw, k) => {
      if (out[k]) return;
      const sc = [...w].filter((x) => sw.has(x)).length;
      if (sc > score) {
        score = sc;
        best = k;
      }
    });
    if (best >= 0 && score >= 2) out[best] = step;
  }
  return out;
}
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

export default function Topics({ focus }) {
  const [status] = usePoll("/distill/status", 1500);
  const [write] = usePoll("/write/status", 1500);
  const [list, reloadList] = usePoll("/topics", 0);
  const [openId, setOpenId] = useState(null);
  const [layout, setLayout] = useState("cards"); // "cards" | "map"

  // Opened from elsewhere (Overview map, quick search): show that topic.
  useEffect(() => {
    if (focus?.topicId) setOpenId(focus.topicId);
  }, [focus]);
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
    return (
      <TopicDetail key={openId}
        id={openId}
        focusPoint={focus?.topicId === openId ? focus.pointId : null}
        onBack={() => setOpenId(null)}
        onOpen={setOpenId}
      />
    );
  }

  const building = status?.state === "running";
  const writing = write?.state === "running";
  const run = list?.last_run;
  const topics = list?.topics ?? [];
  const pending = list?.pending ?? 0; // passages from new files not yet in a topic (Phase 7)
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
            <p className="muted">
              {pending > 0 && topics.length
                ? `${pending.toLocaleString("en-US")} new passage${pending === 1 ? "" : "s"} from recently added files ${pending === 1 ? "isn't" : "aren't"} in a topic yet.`
                : "Group passages by subject and merge repeats. New files are added to your topics automatically."}
            </p>
            {!building && status?.state === "done" && status.added > 0 && <p className="small ok-text">{status.message}</p>}
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
              <div className="job-buttons">
                {pending > 0 && topics.length > 0 && (
                  <button onClick={() => post("/distill/update")} disabled={writing} title="Add the new passages to your existing topics — keeps names, articles, lessons and flashcard progress">
                    <Icon name="sparkle" size={18} />
                    Add new files to topics
                  </button>
                )}
                <button
                  className={pending > 0 && topics.length ? "secondary" : ""}
                  onClick={() => post("/distill/start")}
                  disabled={writing}
                  title={topics.length ? "Regroup everything from scratch — best after adding a lot of new material" : undefined}
                >
                  <Icon name="refresh" size={18} />
                  {topics.length ? "Rebuild topics" : "Build topics"}
                </button>
              </div>
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
              <div className="job-buttons">
                <button onClick={() => post("/write/start", { rewrite_all: false })} disabled={!topics.length || building || allDone}>
                  <Icon name="sparkle" size={18} />
                  {written === 0 && lessons === 0 ? "Write articles and lessons" : allDone ? "All written" : "Write remaining"}
                </button>
                {written > 0 && (
                  <button
                    className="secondary"
                    disabled={building}
                    onClick={() =>
                      window.confirm(
                        `Rewrite all ${written} articles and their lessons from scratch? This takes about 2 minutes per topic. Flashcard progress is kept.`
                      ) && post("/write/start", { rewrite_all: true })
                    }
                    title="Write every article again — e.g. after a model update"
                  >
                    <Icon name="refresh" size={18} />
                    Rewrite all
                  </button>
                )}
              </div>
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
        <div className="points-bar view-switch" role="group" aria-label="How to show topics">
          <button className={layout === "cards" ? "seg on" : "seg"} onClick={() => setLayout("cards")} aria-pressed={layout === "cards"}>
            <Icon name="grid" size={15} /> Cards
          </button>
          <button className={layout === "map" ? "seg on" : "seg"} onClick={() => setLayout("map")} aria-pressed={layout === "map"}>
            <Icon name="map" size={15} /> Map
          </button>
        </div>
      )}
      {topics.length > 0 && layout === "map" && (
        <section className="card">
          <Suspense fallback={<p className="muted">Loading map…</p>}>
            <TopicMap onOpen={setOpenId} />
          </Suspense>
        </section>
      )}
      {topics.length > 0 && layout === "cards" && (
        <ul className="topic-grid" aria-label="Topics">
          {topics.map((t, i) => (
            <li key={t.id}>
              <button className={`topic-card tone-${TONES[i % TONES.length]}`} onClick={() => setOpenId(t.id)}>
                <span className="topic-bar" aria-hidden="true" />
                <span className="topic-title">{t.title}</span>
                {t.summary && <span className="topic-summary">{t.summary}</span>}
                <span className="topic-meta">
                  {t.status === "written" && t.kind !== "data" && (
                    <span className="ready">
                      <Icon name="check" size={13} /> Article ready
                    </span>
                  )}
                  {t.kind === "data" && (
                    <span className="ready data-badge">
                      <Icon name="grid" size={13} /> Spreadsheet · calculated
                    </span>
                  )}
                  {Boolean(t.has_lesson) && t.kind !== "data" && (
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
function TopicDetail({ id, focusPoint, onBack, onOpen }) {
  const [data, reloadTopic] = usePoll("/topic", 0, { id });
  const [lessonData] = usePoll("/lesson", 0, { id });
  const [tab, setTab] = useState(null);
  const [cited, setCited] = useState(null); // point shown in the side panel
  // Live writing (v0.8): while the writer works on THIS topic, its text
  // streams in and is shown as it is written.
  const [write, reloadWrite] = usePoll("/write/status", 1000);
  const liveHere = write?.state === "running" && write.live_topic === id && typeof write.live === "string";
  const [notice, setNotice] = useState("");
  const wasLive = useRef(false);
  const [topicData, setTopicData] = useState(null);
  useEffect(() => {
    if (wasLive.current && !liveHere) kb.get("/topic", { id }).then((r) => !r.error && setTopicData(r));
    wasLive.current = liveHere;
  }, [liveHere, id]);
  async function writeNow() {
    setNotice("");
    const r = await kb.post("/write/topic", { topic_id: id });
    setNotice(r.message || r.error || "");
    reloadWrite();
    setTab("article");
  }

  if (!data) return <p className="muted">Loading topic…</p>;
  const { topic, points, related, citations, loose_threshold } = topicData ?? data;
  const hasArticle = Boolean(topic.article);
  const hasLesson = Boolean(lessonData?.lesson);
  // From quick search: show the exact passage in Source points.
  const view = tab ?? (focusPoint ? "points" : hasLesson ? "lesson" : hasArticle ? "article" : "points");
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
        <TopicEditBar
          topic={topic}
          onDone={(r) => {
            setNotice(r.message || r.error || "");
            setTopicData(null);
            reloadTopic();
            if (r.open) onOpen(r.open);
          }}
        />
        <p className="hero-meta">
          {formatCount(points.length)} distinct points
          {topic.kind === "data"
            ? " · calculated from your spreadsheet's cells (no AI)"
            : hasArticle
              ? ` · article written by ${topic.model_used}`
              : " · article not written yet"}
        </p>
      </header>
      {notice && view !== "article" && <p className="notice ok">{notice}</p>}

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
            {liveHere ? (
              <div className="live-writing" aria-live="polite">
                <p className="live-tag">
                  <span className="live-dot" aria-hidden="true" /> Writing now with {write.model} — {write.message}
                </p>
                <Markdown text={write.live || "…"} onCite={() => {}} />
                <span className="live-cursor" aria-hidden="true" />
              </div>
            ) : hasArticle ? (
              <>
                <Suspense fallback={<Markdown text={topic.article} onCite={openCitation} />}>
                  <Markdown
                    text={topic.article}
                    onCite={openCitation}
                    figures={Object.fromEntries(
                      Object.entries(figuresFor(topic.article, lessonData?.lesson)).map(([k, step]) => [
                        k,
                        <figure className="article-fig" key={k}>
                          <Visual spec={step.visual} />
                          <figcaption>
                            <strong>Figure:</strong> {step.title}
                            {step.text ? ` — ${step.text}` : ""}
                          </figcaption>
                        </figure>,
                      ])
                    )}
                  />
                </Suspense>
                <p className="article-checks small">
                  <Icon name="check" size={14} />{" "}
                  {topic.kind === "data"
                    ? "Calculated from your spreadsheet — no AI involved."
                    : topic.checks
                      ? `Checked against the sources: ${topic.checks.removed_count ? `${topic.checks.removed_count} unsupported item${topic.checks.removed_count === 1 ? "" : "s"} removed` : "nothing needed removing"}.${
                          topic.checks.rewritten
                            ? ` The first draft had ${topic.checks.first_removed_count} unsupported item${topic.checks.first_removed_count === 1 ? "" : "s"}, so it was written again more strictly.`
                            : ""
                        }`
                      : "Every line links to its source."}
                </p>
              </>
            ) : (
              <div className="article-empty">
                <p className="muted">
                  {write?.state === "running"
                    ? "The writer is busy with other topics. Jump the queue to write this one next."
                    : "This topic doesn't have a written article yet. Write it now — you can watch it being written — or use Write articles to do all topics."}
                </p>
                <button onClick={writeNow}>
                  <Icon name="sparkle" size={18} /> Write this topic now
                </button>
                {notice && <p className="small muted">{notice}</p>}
              </div>
            )}
          </article>
          {hasArticle && (
            <CitePanel cited={cited} hint="Click any numbered chip in the article to see the exact text it came from, with its file and page." />
          )}
        </div>
      )}

      {view === "points" && (
        <SourcePoints
          points={points}
          looseThreshold={loose_threshold}
          focusPoint={focusPoint}
          topic={topic}
          onEdited={(r) => {
            setNotice(r.message || r.error || "");
            setTopicData(null);
            reloadTopic();
            if (r.open) onOpen(r.open);
          }}
        />
      )}
    </div>
  );
}

/**
 * Source points tab.
 * WHAT: - "In reading order" (default): ONE card per document part — every
 *         point from the same file and section ("Use Case 7: …") joined in
 *         reading order, so a write-up is never split across cards (v0.6.3,
 *         owner: "why half half things are in different cards"). A dotted
 *         marker shows where text that belongs to another topic was skipped;
 *         "Read the whole section" opens the full part from the file.
 *       - "Best match first": one card per point, most central first.
 *       - Points that repeat across files are already shown once (repeat
 *         groups) with "Said in N places".
 */
function SourcePoints({ points, looseThreshold, focusPoint, topic, onEdited }) {
  const [order, setOrder] = useState("reading");
  // v0.9 hand edits: tick points, then move them to another topic or make
  // a new topic from them (topicedit.py). Hidden for spreadsheet topics.
  const [editing, setEditing] = useState(false);
  const [picked, setPicked] = useState(() => new Set());
  const toggle = (pid) =>
    setPicked((old) => {
      const next = new Set(old);
      if (next.has(pid)) next.delete(pid);
      else next.add(pid);
      return next;
    });
  const tick = (p) =>
    editing && (
      <label className="pick">
        <input type="checkbox" checked={picked.has(p.id)} onChange={() => toggle(p.id)} /> Select
      </label>
    );
  const focused = useRef(null);
  // Scroll to (and briefly highlight) the passage chosen in quick search.
  useEffect(() => {
    if (focusPoint && focused.current) focused.current.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [focusPoint]);
  const key = (p) => (p.order ? p.order : [0, 0, p.id]);
  const sorted = [...points].sort((a, b) => {
    const x = key(a);
    const y = key(b);
    return x[0] - y[0] || x[1] - y[1] || x[2] - y[2];
  });
  // Group consecutive points of the same file + section into one card.
  const groups = [];
  for (const p of sorted) {
    const g = groups[groups.length - 1];
    const sameFile = g && key(g.points[0])[0] === key(p)[0];
    if (g && sameFile && (g.section ?? "") === (p.section ?? "")) g.points.push(p);
    else groups.push({ section: p.section, file: p.sources[0]?.file_name, points: [p] });
  }
  return (
    <div>
      <div className="points-bar" role="group" aria-label="Order of points">
        <button className={order === "reading" ? "seg on" : "seg"} onClick={() => setOrder("reading")} aria-pressed={order === "reading"}>
          In reading order
        </button>
        <button className={order === "central" ? "seg on" : "seg"} onClick={() => setOrder("central")} aria-pressed={order === "central"}>
          Best match first
        </button>
        {topic?.kind !== "data" && (
          <button
            className={editing ? "seg on" : "seg"}
            onClick={() => {
              setEditing(!editing);
              setPicked(new Set());
            }}
            aria-pressed={editing}
          >
            {editing ? "Done editing" : "Move or split points"}
          </button>
        )}
      </div>
      {editing && (
        <PointActions
          topic={topic}
          picked={[...picked]}
          onDone={(r) => {
            setPicked(new Set());
            onEdited?.(r);
          }}
        />
      )}
      {order === "reading" ? (
        <ol className="points">
          {groups.map((g, gi) => {
            const pages = [...new Set(g.points.map((p) => key(p)[1]))].sort((a, b) => a - b);
            return (
              <li key={gi} className="section-card">
                <p className="point-group">
                  <Icon name="file" size={14} />
                  <span>{g.file}</span>
                  {g.section && <strong>{g.section}</strong>}
                </p>
                {g.points.map((p, i) => {
                  const prev = g.points[i - 1];
                  const gap = prev && (key(p)[1] !== key(prev)[1] ? key(p)[2] !== 0 : key(p)[2] - key(prev)[2] > 1);
                  return (
                    <div
                      key={p.id}
                      className={`section-part ${p.id === focusPoint ? "found" : ""}`}
                      ref={p.id === focusPoint ? focused : undefined}
                    >
                      {gap && <p className="skip-mark" title="Text between these parts belongs to another topic">· · ·</p>}
                      {tick(p)}
                      {p.fit < looseThreshold && (
                        <p className="loose-flag">
                          <Icon name="alert" size={15} /> Loose fit: may belong to another topic
                        </p>
                      )}
                      <Formatted text={withoutHeading(p.text, g.section)} collapseAt={40} />
                      {p.sources.length > 1 && (
                        <p className="small muted">
                          Also said in {p.sources.slice(1).map((s) => `${s.file_name} p.${s.page}`).join(", ")} — shown once.
                        </p>
                      )}
                    </div>
                  );
                })}
                <ul className="point-sources" aria-label="Pages — click to open the original">
                  {pages.map((pg) => (
                    <SourceChip key={pg} sourceId={key(g.points[0])[0]} fileName={g.file} page={pg} />
                  ))}
                </ul>
                {g.points[0].passage_id && <InContext passageId={g.points[0].passage_id} whole={Boolean(g.section)} />}
              </li>
            );
          })}
        </ol>
      ) : (
        <ol className="points">
          {points.map((p) => (
            <li key={p.id} className={p.fit < looseThreshold ? "is-loose" : ""}>
              {tick(p)}
              {p.section && <p className="point-section">From: {p.section}</p>}
              {p.fit < looseThreshold && (
                <p className="loose-flag">
                  <Icon name="alert" size={15} /> Loose fit: may belong to another topic
                </p>
              )}
              <Formatted text={withoutHeading(p.text, p.section)} />
              <ul className="point-sources" aria-label="Sources">
                {p.sources.map((s, i) => (
                  <SourceChip key={i} sourceId={s.source_id} fileName={s.file_name} page={s.page} />
                ))}
              </ul>
              {p.sources.length > 1 && <p className="small muted">Said in {p.sources.length} places, shown once.</p>}
              {p.passage_id && <InContext passageId={p.passage_id} />}
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

/**
 * v0.9: rename this topic, or merge another topic into it (topicedit.py).
 * Hand edits mark the topic for rewriting; "Rebuild topics" replaces them.
 */
function TopicEditBar({ topic, onDone }) {
  const [mode, setMode] = useState(null); // "rename" | "merge"
  const [title, setTitle] = useState(topic.title);
  const [other, setOther] = useState("");
  const [names] = usePoll("/topics/names", 0);
  const choices = (names?.topics ?? []).filter((t) => t.id !== topic.id && t.kind !== "data");
  async function save() {
    const r =
      mode === "rename"
        ? await kb.post("/topics/rename", { topic_id: topic.id, title })
        : await kb.post("/topics/merge", { topic_id: topic.id, others: [Number(other)] });
    setMode(null);
    onDone(r);
  }
  if (!mode)
    return (
      <p className="topic-edit-links">
        <button className="link" onClick={() => setMode("rename")}>
          Rename
        </button>
        {topic.kind !== "data" && choices.length > 0 && (
          <>
            {" · "}
            <button className="link" onClick={() => setMode("merge")}>
              Merge another topic into this one
            </button>
          </>
        )}
      </p>
    );
  return (
    <div className="topic-edit">
      {mode === "rename" ? (
        <input value={title} onChange={(e) => setTitle(e.target.value)} aria-label="New topic name" autoFocus />
      ) : (
        <select value={other} onChange={(e) => setOther(e.target.value)} aria-label="Topic to merge in">
          <option value="">Choose a topic to merge in…</option>
          {choices.map((t) => (
            <option key={t.id} value={t.id}>
              {t.title}
            </option>
          ))}
        </select>
      )}
      <button onClick={save} disabled={mode === "merge" ? !other : !title.trim()}>
        {mode === "rename" ? "Save name" : "Merge"}
      </button>
      <button className="secondary" onClick={() => setMode(null)}>
        Cancel
      </button>
    </div>
  );
}

/** v0.9: what to do with the ticked points — move them, or make a new topic. */
function PointActions({ topic, picked, onDone }) {
  const [to, setTo] = useState("");
  const [name, setName] = useState("");
  const [names] = usePoll("/topics/names", 0);
  const choices = (names?.topics ?? []).filter((t) => t.id !== topic.id && t.kind !== "data");
  const n = picked.length;
  async function move() {
    onDone(await kb.post("/topics/move", { topic_id: topic.id, points: picked, to_topic_id: Number(to) }));
  }
  async function split() {
    const r = await kb.post("/topics/split", { topic_id: topic.id, points: picked, title: name });
    onDone({ ...r, open: r.ok ? r.topic_id : null });
  }
  return (
    <div className="point-actions">
      <p className="small muted">
        {n ? `${n} point${n === 1 ? "" : "s"} selected.` : "Tick the points you want to move."} Changed topics are
        rewritten by "Write remaining". "Rebuild topics" regroups everything and replaces hand edits.
      </p>
      <div className="topic-edit">
        <select value={to} onChange={(e) => setTo(e.target.value)} aria-label="Move to topic">
          <option value="">Move to…</option>
          {choices.map((t) => (
            <option key={t.id} value={t.id}>
              {t.title}
            </option>
          ))}
        </select>
        <button onClick={move} disabled={!n || !to}>
          Move
        </button>
        <span className="muted small">or</span>
        <input placeholder="Name for a new topic" value={name} onChange={(e) => setName(e.target.value)} />
        <button onClick={split} disabled={!n || !name.trim()}>
          Make new topic
        </button>
      </div>
    </div>
  );
}

/** Drop a passage's first line when it only repeats the section shown above it. */
function withoutHeading(text, section) {
  if (!section) return text;
  const [first, ...rest] = String(text).split("\n");
  return first.trim() === section.trim() && rest.length ? rest.join("\n") : text;
}

/** "Read in context": loads the passages just before and after this one. */
function InContext({ passageId, whole = false }) {
  const [open, setOpen] = useState(false);
  const [data, setData] = useState(null);
  async function toggle() {
    if (!open && !data) {
      const r = await kb.get(whole ? "/passage/section" : "/passage/context", { id: passageId });
      if (!r.error) setData(r);
    }
    setOpen(!open);
  }
  return (
    <div className="in-context">
      <button className="link small" onClick={toggle} aria-expanded={open}>
        {open ? (whole ? "Hide section" : "Hide context") : whole ? "Read the whole section" : "Read in context"}
      </button>
      {open && data && (
        <div className="context-box">
          {data.passages.map((c) =>
            whole ? (
              <div key={c.id} className="context-part whole">
                <Formatted text={withoutHeading(c.text, data.section)} collapseAt={40} />
              </div>
            ) : c.current ? (
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
              <SourceChip key={i} sourceId={s.source_id} fileName={s.file_name} page={s.page} />
            ))}
          </ul>
        </>
      ) : (
        <p className="muted small">{hint}</p>
      )}
    </aside>
  );
}
