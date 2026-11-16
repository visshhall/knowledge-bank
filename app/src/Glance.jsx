/**
 * Glance.jsx — v0.22 the "at a glance" pictures for Overview and Learning, each with a plain-words caption.
 *
 * WHAT:  LibraryGlance (Overview): what the library is made of (donut of file kinds + your files vs web pages), subjects (treemap
 *        of categories), the last 30 days (bars: files added, web pages read), and three health rings (linked to related files,
 *        grouped into topics, subjects well covered).
 *        LearningGlance (Learning): today's reading against the daily limit (ring), web pages read per day (bars), the topic
 *        queue (stacked bar: waiting / done / nothing found), whether lessons are working (donut), and which sites are trusted or
 *        skipped (donut).
 * WHY:   Pictures first, text beside them (owner). Each panel has a one-line caption so someone who prefers reading gets the same message.
 * WHEN:  Rendered at the top of Overview and Learning; data refreshes every 15 s (GET /glance/all plus the Learning endpoints that
 *        screen already polls).
 * CONNECTED TO: viz.jsx, bridge.js → /glance/all, /learn/status, /lessons/status, /coverage/status (server.py → glance.py, learner.py,
 *        mistakes.py, coverage.py); Overview.jsx, Learning.jsx; styles.css (.glance-*).
 */
import { usePoll } from "./bridge.js";
import { Bars, Donut, Ring, StackBar, Treemap, catColor } from "./viz.jsx";

const KIND_COLORS = ["#23705f", "#f08a68", "#6a4ba8", "#e8b840", "#3b7ea1", "#c4567a", "#7d7d7d"];

export function LibraryGlance() {
  const [g] = usePoll("/glance/all", 15000);
  if (!g || !g.files.total) return null;
  const f = g.files, h = g.health;
  const kinds = f.kinds.map((k, i) => ({ label: k.label, value: k.n, color: KIND_COLORS[i % KIND_COLORS.length] }));
  const days = g.daily.map((d) => ({ date: d.date, a: d.files, b: d.web }));
  const addedFiles = g.daily.reduce((a, d) => a + d.files, 0), addedWeb = g.daily.reduce((a, d) => a + d.web, 0);
  const top = g.categories.slice(0, 3).map((c) => c.name).join(", ");
  return (
    <section className="card glance" aria-label="Your library at a glance">
      <h2>Your library at a glance</h2>
      <div className="glance-grid">
        <div className="glance-panel">
          <h3>What it is made of</h3>
          <Donut parts={kinds} sub="files" />
          <p className="muted small">{f.mine} of your own files{f.web ? ` and ${f.web} web page${f.web === 1 ? "" : "s"} the app read by itself` : ""}.</p>
        </div>
        <div className="glance-panel wide">
          <h3>Subjects</h3>
          <Treemap items={g.categories.map((c) => ({ name: c.name, value: c.files, color: catColor(c.name) }))} />
          <p className="muted small">{g.categories.length ? `Bigger rectangle = more files. Most files are about ${top}.` : "Files appear here by subject once they are read."}</p>
        </div>
        <div className="glance-panel">
          <h3>Last 30 days</h3>
          <Bars days={days} aLabel="files added" bLabel="web pages read" aColor="var(--forest)" bColor="var(--coral)" />
          <p className="muted small"><i className="dot" style={{ background: "var(--forest)" }} /> {addedFiles} files added · <i className="dot" style={{ background: "var(--coral)" }} /> {addedWeb} web pages read</p>
        </div>
        <div className="glance-panel wide">
          <h3>How well it is connected</h3>
          <div className="glance-rings">
            <Ring value={h.linked_pct} label="Linked" sub="to related files" color="var(--teal)" />
            <Ring value={h.topics_pct} label="In topics" sub="of all passages" color="var(--violet)" />
            <Ring value={h.well_covered_pct} label="Covered" sub={`${h.subjects - h.weak} of ${h.subjects} subjects`} color="var(--forest)" />
          </div>
          <p className="muted small">
            {h.pending_links ? `${h.pending_links} file${h.pending_links === 1 ? " is" : "s are"} waiting to be linked. ` : ""}
            {h.weak ? `${h.weak} subject${h.weak === 1 ? " is" : "s are"} thin; Learning can fetch more.` : "Every subject has good coverage."}
          </p>
        </div>
      </div>
    </section>
  );
}

export function LearningGlance() {
  const [g] = usePoll("/glance/all", 15000);
  const [ln] = usePoll("/learn/status", 5000);
  const [ls] = usePoll("/lessons/status", 8000);
  const [cv] = usePoll("/coverage/status", 10000);
  if (!g || !ln) return null;
  const days = g.daily.map((d) => ({ date: d.date, a: d.web, b: 0 }));
  const q = { pending: 0, done: 0, empty: 0 };
  (ln.topics ?? []).forEach((t) => { if (t.status === "pending") q.pending++; else if (t.pages_added > 0) q.done++; else q.empty++; });
  const verdicts = { working: 0, new: 0, unclear: 0, not_helping: 0 };
  (ls?.rules ?? []).forEach((r) => { if (verdicts[r.verdict] !== undefined) verdicts[r.verdict]++; });
  const sites = { trusted: 0, skipped: 0, byYou: 0 };
  (cv?.sites ?? []).forEach((s) => { if (s.blocked) (s.manual === 1 ? sites.byYou++ : sites.skipped++); else sites.trusted++; });
  const todayFrac = ln.daily_budget ? ln.pages_today / ln.daily_budget : 0;
  return (
    <section className="card glance" aria-label="Learning at a glance">
      <h2>Learning at a glance</h2>
      <div className="glance-grid">
        <div className="glance-panel">
          <h3>Today</h3>
          <div className="glance-rings"><Ring value={ln.pages_today} max={Math.max(1, ln.daily_budget)} label={`${ln.pages_today} of ${ln.daily_budget}`} sub="pages today" text={String(ln.pages_today)} color={todayFrac > 0.9 ? "var(--coral)" : "var(--teal)"} /></div>
          <p className="muted small">{ln.on ? "Web learning is on." : "Web learning is off."} It stops for the day at the limit.</p>
        </div>
        <div className="glance-panel wide">
          <h3>Web pages read per day</h3>
          <Bars days={days} aLabel="web pages" aColor="var(--teal)" />
          <p className="muted small">{g.files.web} web page{g.files.web === 1 ? "" : "s"} kept in total.</p>
        </div>
        <div className="glance-panel wide">
          <h3>Topic queue</h3>
          <StackBar parts={[{ label: "Waiting", value: q.pending, color: "var(--mustard)" }, { label: "Read", value: q.done, color: "var(--teal)" }, { label: "Nothing found", value: q.empty, color: "var(--line)" }]} />
          {!(ln.topics ?? []).length && <p className="muted small">No topics yet. Add one below, or let it find gaps.</p>}
        </div>
        <div className="glance-panel">
          <h3>Are lessons working?</h3>
          <Donut size={120} thickness={16} center={String(Object.values(verdicts).reduce((a, b) => a + b, 0))} sub="lessons"
                 parts={[{ label: "Working", value: verdicts.working, color: "var(--teal)" }, { label: "Too early", value: verdicts.new, color: "var(--mustard)" }, { label: "Unclear", value: verdicts.unclear, color: "var(--line)" }, { label: "Not helping", value: verdicts.not_helping, color: "var(--coral)" }]} />
        </div>
        <div className="glance-panel">
          <h3>Web sites</h3>
          <Donut size={120} thickness={16} center={String(sites.trusted + sites.skipped + sites.byYou)} sub="sites"
                 parts={[{ label: "Trusted", value: sites.trusted, color: "var(--teal)" }, { label: "Skipped as junk", value: sites.skipped, color: "var(--coral)" }, { label: "Blocked by you", value: sites.byYou, color: "var(--violet)" }]} />
        </div>
      </div>
    </section>
  );
}

/**
 * LibraryStrip (Library screen, v0.22): two clickable pictures above the file list, worked out from the list already on screen.
 * Subjects treemap -> picks the category filter; status donut -> picks the status filter. Click again to clear.
 */
export function LibraryStrip({ sources, cat, setCat, state, setState }) {
  if (!sources.length) return null;
  const byCat = {};
  sources.forEach((s) => (s.categories?.length ? s.categories : ["Uncategorised"]).slice(0, 1).forEach((c) => { byCat[c] = (byCat[c] || 0) + 1; }));
  const items = Object.entries(byCat).map(([name, value]) => ({ name, value, color: catColor(name) })).sort((a, b) => b.value - a.value);
  const byState = {};
  sources.forEach((s) => { const k = s.status || "ready"; byState[k] = (byState[k] || 0) + 1; });
  const stateColor = { ready: "#23705f", failed: "#c4567a", set_aside: "#7d7d7d" };
  const parts = Object.entries(byState).map(([label, value], i) => ({ label, value, color: stateColor[label] || KIND_COLORS[(i + 3) % KIND_COLORS.length] }));
  return (
    <section className="card glance" aria-label="Library by subject and status">
      <div className="glance-grid">
        <div className="glance-panel wide">
          <h3>By subject</h3>
          <Treemap items={items} height={180} active={cat} onPick={(n) => setCat(cat === n ? "" : n)} />
          <p className="muted small">Click a rectangle to show only that subject; click again to clear.</p>
        </div>
        <div className="glance-panel">
          <h3>By status</h3>
          <Donut parts={parts} size={120} thickness={16} sub="files" active={state} onPick={(n) => setState(state === n ? "" : n)} />
        </div>
      </div>
    </section>
  );
}

/** TopicSizes (Topics screen, v0.22): the ten biggest topics as bars, with a plain count beside each. */
export function TopicSizes({ topics }) {
  if (!topics.length) return null;
  const top = [...topics].sort((a, b) => (b.passages || 0) - (a.passages || 0)).slice(0, 10);
  const max = Math.max(1, ...top.map((t) => t.passages || 0));
  return (
    <section className="card glance" aria-label="Topic sizes">
      <h2>Biggest topics</h2>
      <ul className="topic-bars">
        {top.map((t) => (
          <li key={t.id ?? t.title}>
            <span className="tb-name" title={t.title}>{t.title}</span>
            <span className="tb-track"><span className="tb-fill" style={{ width: `${((t.passages || 0) / max) * 100}%`, background: "var(--violet)" }} /></span>
            <span className="muted small tb-n">{(t.passages || 0).toLocaleString("en-US")} passages</span>
          </li>
        ))}
      </ul>
      <p className="muted small">Longer bar = more passages grouped into that topic.</p>
    </section>
  );
}
