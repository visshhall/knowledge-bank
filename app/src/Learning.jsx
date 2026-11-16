/**
 * Learning.jsx — v0.16 the "Learning" screen: how the app improves apart from files the owner adds.
 *
 * WHAT:  Two cards.
 *        1. WEB LEARNING — one switch (OFF until he turns it on). While on, the app finds pages about
 *           the topics on its list (typed by him, or noticed from questions "My files" could not answer),
 *           reads them politely and adds them straight to the library, marked as learned. A "watch
 *           addresses" list is re-read about once a day (only changed content is added). Shows today's
 *           pages against the daily budget (he can change it), what it just did, the topic list with
 *           results, "Learn now", and "Remove everything it learned" (asks twice; his own files stay).
 *        2. TRAINING DATA — counts of the reactions the app has noticed (thumbs, Copy, Regenerate, Edit,
 *           corrections), how many training examples it has built from Free chat, a bar to the ~300
 *           where a fine-tune is worth trying, a review list (Reject / Restore any example), and
 *           "Export dataset", which writes the dataset and a how-to recipe into the data folder.
 * WHY:   The owner asked for the app to learn by itself, not only from data he adds. Everything it
 *        does on its own is visible here and can be switched off or undone.
 *        3. (v0.17) MISTAKES AND LESSONS — every answer that went wrong (thumbs-down, Regenerate, Correct, facts the
 *           checker removed) is logged; the app finds patterns (by counting his corrections, and with the AI) and
 *           turns them into short lessons it follows in every reply. Lessons apply automatically; each shows its
 *           evidence, whether it is working ("working" / "not helping — switched off") and can be turned off or
 *           deleted. "Find patterns now" runs the search at once.
 *        0. (v0.22) "Learning at a glance" pictures at the top: today's reading, pages per day, topic queue, lessons, sites (Glance.jsx)
 *        4. (v0.18) WHAT IT KNOWS AND WHAT'S MISSING — a bar per category (how well the library covers it, with a flag
 *           on weak ones and how often answers cited it), "Fill the gaps now" (adds web topics for the weakest
 *           categories), a switch for doing that automatically, counts of learned pages (useful / not used yet /
 *           thin), "Remove unused pages" (learned pages 45+ days old that no answer used), and the web sites it
 *           trusts or avoids with Block / Allow / Let the app decide.
 *        5. (v0.19) CATEGORIES — the built-in categories plus the ones the app grew from the data, each with its
 *           sub-categories and file counts; "Find new categories now"; a switch for doing it automatically; for grown
 *           categories Rename / Merge into… / Delete; how many files still fit no category.
 * WHEN:  Opened from the sidebar's Knowledge section. Polls /learn/status every 3 s while open (so a
 *        running round shows live) and /training/status every 6 s.
 * CONNECTED TO: bridge.js → engine /learn/status, /learn/enable, /learn/limits, /learn/run, /learn/topic/*,
 *        /learn/watch/*, /learn/pages, /learn/remove-all, /training/status, /training/examples,
 *        /training/example/status, /training/export, /lessons/status, /lessons/enable, /lessons/run, /lessons/rule/toggle, /lessons/rule/delete, /coverage/status, /coverage/plan, /coverage/auto, /coverage/site, /coverage/prune-unused, /taxonomy/status, /taxonomy/run, /taxonomy/auto, /taxonomy/rename, /taxonomy/merge, /taxonomy/delete (server.py → learner.py, training.py, mistakes.py, coverage.py, taxonomy.py); styles.css (.learn-*).
 */
import { useState } from "react";
import Icon from "./icons.jsx";
import { LearningGlance } from "./Glance.jsx";
import { kb, usePoll } from "./bridge.js";

export default function Learning() {
  return (
    <div className="learn-grid">
      <header className="page-head">
        <h1>Learning</h1>
        <p className="lede">
          How the app gets better on its own: it can read the web for topics you care about, and it turns the answers
          you like or correct into training examples. Everything it does is listed here and can be switched off or undone.
        </p>
      </header>
      <LearningGlance />
      <WebLearning />
      <Lessons />
      <Coverage />
      <Categories />
      <TrainingData />
    </div>
  );
}

function WebLearning() {
  const [st, reload] = usePoll("/learn/status", 3000);
  const [topic, setTopic] = useState("");
  const [watchUrl, setWatchUrl] = useState("");
  const [scope, setScope] = useState("section");
  const [msg, setMsg] = useState("");
  const [sure, setSure] = useState(false);
  const [budget, setBudget] = useState("");

  async function call(path, body) {
    const r = await kb.post(path, body ?? {});
    setMsg(r.ok === false || r.error ? r.message || r.error : r.message && path.endsWith("remove-all") ? r.message : "");
    reload();
    return r;
  }

  if (!st) return <section className="card learn-card"><p className="muted">Loading…</p></section>;
  const used = Math.min(100, Math.round((st.pages_today / st.daily_budget) * 100));
  const pending = st.topics.filter((t) => t.status === "pending").length;

  return (
    <section className="card learn-card" aria-label="Web learning">
      <div className="learn-head">
        <h2>Learn from the web</h2>
        <label className="learn-switch">
          <input type="checkbox" checked={st.on} onChange={(e) => call("/learn/enable", { on: e.target.checked })} />
          {st.on ? "On" : "Off"}
        </label>
      </div>
      <p className="muted">
        {st.on ? st.message : "Off. Turn it on and the app searches the web for the topics below, reads the best pages and adds them to your library by itself. It only runs while you are online, never faster than your daily limit, and obeys each site's robots.txt."}
      </p>

      {st.on && (
        <>
          <div className="learn-stats">
            <div className="learn-stat"><strong>{st.pages_today}</strong><span className="small muted">pages today of {st.daily_budget}</span></div>
            <div className="learn-stat"><strong>{st.learned_pages}</strong><span className="small muted">learned in total</span></div>
            <div className="learn-stat"><strong>{pending}</strong><span className="small muted">topics waiting</span></div>
          </div>
          <div className="learn-bar" aria-hidden="true"><div style={{ width: `${used}%` }} /></div>
        </>
      )}

      <form
        className="learn-form"
        onSubmit={async (e) => {
          e.preventDefault();
          const r = await call("/learn/topic/add", { topic });
          if (r.ok) setTopic("");
        }}
      >
        <input value={topic} onChange={(e) => setTopic(e.target.value)} placeholder="A topic to learn about, e.g. Sentinel analytics rule tuning" aria-label="Topic to learn about" maxLength={140} />
        <button type="submit" className="small-btn" disabled={topic.trim().length < 3}>Add topic</button>
        {st.on && <button type="button" className="secondary small-btn" onClick={() => call("/learn/run")}>Learn now</button>}
      </form>
      {msg && <p className="notice error">{msg}</p>}

      {st.topics.length > 0 && (
        <ul className="learn-list" aria-label="Topics">
          {st.topics.slice(0, 15).map((t) => (
            <li key={t.id}>
              <span>{t.topic}</span>
              <span className={`learn-tag ${t.status}`}>{t.status === "pending" ? "waiting" : t.status === "done" ? `${t.pages_added} page${t.pages_added === 1 ? "" : "s"}` : "nothing found"}</span>
              {t.origin === "gap" && <span className="learn-tag" title="Your files could not answer this question">from a question</span>}
              {t.origin === "coverage" && <span className="learn-tag" title="The library is thin on this category">fills a gap</span>}
              <button className="link small" onClick={() => call("/learn/topic/remove", { id: t.id })} aria-label={`Remove topic ${t.topic}`}>Remove</button>
            </li>
          ))}
        </ul>
      )}

      <h3 className="model-sub">Addresses to re-read every day</h3>
      <form
        className="learn-form"
        onSubmit={async (e) => {
          e.preventDefault();
          const r = await call("/learn/watch/add", { url: watchUrl, scope, max_pages: scope === "page" ? 1 : scope === "section" ? 30 : 100 });
          if (r.ok) setWatchUrl("");
        }}
      >
        <input value={watchUrl} onChange={(e) => setWatchUrl(e.target.value)} placeholder="https://example.com/blog/" aria-label="Web address to watch" />
        <select value={scope} onChange={(e) => setScope(e.target.value)} aria-label="How much to read">
          <option value="page">This page only</option>
          <option value="section">This page and the pages under it</option>
          <option value="site">The whole site</option>
        </select>
        <button type="submit" className="small-btn" disabled={watchUrl.trim().length < 4}>Watch</button>
      </form>
      {st.watch.length > 0 && (
        <ul className="learn-list" aria-label="Watched addresses">
          {st.watch.map((w) => (
            <li key={w.id}>
              <span>{w.url}</span>
              <span className="learn-tag">{w.pages_added} added{w.last_run ? "" : " · not read yet"}</span>
              <button className="link small" onClick={() => call("/learn/watch/remove", { id: w.id })} aria-label={`Stop watching ${w.url}`}>Stop</button>
            </li>
          ))}
        </ul>
      )}

      {st.recent.length > 0 && (
        <>
          <h3 className="model-sub">What it just did</h3>
          <ul className="learn-list" aria-label="Recent activity">
            {[...st.recent].reverse().map((r, i) => (
              <li key={i}>
                <span className="small">{r.at} · {r.topic}{r.url ? ` · ${r.url}` : ""}</span>
                <span className="learn-tag">{r.result}</span>
              </li>
            ))}
          </ul>
        </>
      )}

      <div className="learn-form">
        <label className="small muted" htmlFor="learn-budget">Pages per day</label>
        <input
          id="learn-budget"
          type="number"
          min="5"
          max="300"
          value={budget || st.daily_budget}
          onChange={(e) => setBudget(e.target.value)}
          onBlur={() => budget && call("/learn/limits", { daily_pages: Number(budget) }).then(() => setBudget(""))}
          style={{ width: 90 }}
        />
        <span className="muted small">(5–300)</span>
        <span style={{ flex: 1 }} />
        {st.learned_pages > 0 && (
          <button
            className={`secondary small-btn ${sure ? "danger" : ""}`}
            onClick={async () => {
              if (!sure) return setSure(true);
              setSure(false);
              await call("/learn/remove-all");
            }}
            onBlur={() => setSure(false)}
          >
            {sure ? `Click again to remove ${st.learned_pages} learned pages` : "Remove everything it learned"}
          </button>
        )}
      </div>
      <p className="muted small">Learned pages appear in Library like any file (with the web address), are used in “My files” answers, and are only ever removed here or by you. Pages you added yourself are never touched.</p>
    </section>
  );
}

function TrainingData() {
  const [st, reloadSt] = usePoll("/training/status", 6000);
  const [show, setShow] = useState("new"); // which list to review: new | rejected
  const [list, reloadList] = usePoll("/training/examples", 6000, { status: show, limit: 20 });
  const [out, setOut] = useState(null);

  if (!st) return null;
  const pct = Math.min(100, Math.round((st.usable / st.ready_at) * 100));

  async function setStatus(id, status) {
    await kb.post("/training/example/status", { id, status });
    reloadList();
    reloadSt();
  }

  return (
    <section className="card learn-card" aria-label="Training data">
      <div className="learn-head">
        <h2>Learn from how you use it</h2>
      </div>
      <p className="muted">
        In Free chat, a thumbs-up or Copy marks an answer as good; thumbs-down or Regenerate marks it as not good; and “Correct”
        lets you rewrite it your way — the most valuable signal. The app keeps the good ones as training examples. A fine-tune is
        worth trying at about {st.ready_at} examples. {st.message}
      </p>
      <div className="learn-bar" aria-hidden="true"><div style={{ width: `${pct}%` }} /></div>
      <div className="learn-stats">
        <div className="learn-stat"><strong>{st.usable}</strong><span className="small muted">examples</span></div>
        <div className="learn-stat"><strong>{st.corrections}</strong><span className="small muted">your corrections</span></div>
        <div className="learn-stat"><strong>{st.signals.up + st.signals.copy}</strong><span className="small muted">liked / copied</span></div>
        <div className="learn-stat"><strong>{st.signals.down + st.signals.regen}</strong><span className="small muted">not good</span></div>
      </div>

      <div className="learn-form">
        <button
          onClick={async () => setOut(await kb.post("/training/export", {}))}
          disabled={st.usable < 20}
          title={st.usable < 20 ? "Collect at least 20 examples first" : "Write the dataset and the how-to into your data folder"}
        >
          <Icon name="upload" size={16} /> Export dataset
        </button>
        <span className="muted small">Only Free-chat answers are used (library answers depend on your files, so they would teach the model to invent).</span>
      </div>
      {out && (out.ok ? (
        <p className="notice ok">
          Saved {out.count} examples ({out.corrections} corrections). Open this folder and follow HOW_TO_FINE_TUNE.md:<br />
          <code>{out.folder}</code>
        </p>
      ) : (
        <p className="notice error">{out.message || out.error}</p>
      ))}

      <div className="learn-form">
        <button className={`small-btn ${show === "new" ? "" : "secondary"}`} onClick={() => setShow("new")}>Examples ({st.usable})</button>
        <button className={`small-btn ${show === "rejected" ? "" : "secondary"}`} onClick={() => setShow("rejected")}>Rejected ({st.rejected})</button>
      </div>
      {list?.examples?.length ? (
        <div className="learn-grid">
          {list.examples.map((e) => (
            <article key={e.id} className="learn-ex">
              <p className="q">{e.prompt}</p>
              {e.kind === "correction" && e.original && <p className="muted small">The model said: {e.original}</p>}
              <p>{e.response}</p>
              <p className="small muted">
                {e.kind === "correction" ? "Your correction" : "Liked answer"} ·{" "}
                {show === "new" ? (
                  <button className="link small" onClick={() => setStatus(e.id, "rejected")}>Reject</button>
                ) : (
                  <button className="link small" onClick={() => setStatus(e.id, "new")}>Restore</button>
                )}
              </p>
            </article>
          ))}
          {list.total > list.examples.length && <p className="muted small">Showing the newest {list.examples.length} of {list.total}.</p>}
        </div>
      ) : (
        <p className="muted small">{show === "new" ? "No examples yet. Use Free chat and press the thumbs-up on answers you like, or Correct on ones you would write differently." : "Nothing rejected."}</p>
      )}
    </section>
  );
}

const KIND_LABEL = { down: "thumbs-down", regen: "asked again", correct: "you corrected it", removed: "facts removed" };
const VERDICT = { new: "new", working: "working", unclear: "no clear effect yet", not_helping: "not helping" };

/** v0.19 card: the category tree (built-in + grown), with sub-categories and owner controls for grown ones. */
function Categories() {
  const [st, reload] = usePoll("/taxonomy/status", 8000);
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState({});
  if (!st) return null;

  async function act(path, body, after) {
    setBusy(true);
    const r = await kb.post(path, body || {});
    setMsg(r.ok === false ? r.message || r.error || "Not done." : after ? after(r) : r.message || "");
    setBusy(false);
    reload();
  }
  const grown = st.categories.filter((c) => c.grown);

  return (
    <section className="card learn-card" aria-label="Categories">
      <div className="learn-head">
        <h2>Categories that grow</h2>
        <label className="learn-switch" title="Let the app add categories and sub-categories as your files change">
          <input type="checkbox" checked={st.auto} onChange={async (e) => { await kb.post("/taxonomy/auto", { on: e.target.checked }); reload(); }} />
          {st.auto ? "Grows by itself" : "Manual"}
        </label>
      </div>
      <p className="muted">
        Files that fit no category are grouped into new ones, and a category with many files is split into sub-categories.
        The built-in categories stay; the ones the app adds can be renamed, merged into another, or deleted.
      </p>
      <div className="learn-form">
        <button className="small-btn" disabled={busy} onClick={() => act("/taxonomy/run", {}, (r) => r.message)}>
          {busy ? "Looking…" : "Find new categories now"}
        </button>
        <span className="muted small">
          {st.unplaced ? `${st.unplaced} file${st.unplaced === 1 ? "" : "s"} fit no category yet. ` : "Every file has a category. "}
          {st.last?.at ? `Last run ${st.last.at}: ${st.last.message}` : ""}
        </span>
      </div>
      {msg && <p className="notice ok">{msg}</p>}
      <ul className="cat-tree" aria-label="Categories">
        {st.categories.map((c) => (
          <li key={c.name}>
            <div className="cat-row">
              <button className="cat-toggle" disabled={!c.subs.length} onClick={() => setOpen({ ...open, [c.name]: !open[c.name] })} aria-expanded={!!open[c.name]}>
                {c.subs.length ? (open[c.name] ? "▾" : "▸") : "·"}
              </button>
              <span className="cat-name">{c.name}</span>
              <span className="small muted">{c.files} file{c.files === 1 ? "" : "s"}{c.subs.length ? ` · ${c.subs.length} sub` : ""}</span>
              {c.grown && <span className="learn-tag done" title={c.terms.join(", ")}>{c.origin === "owner" ? "renamed by you" : "added by the app"}</span>}
              {c.grown && (
                <span className="cat-actions">
                  <button className="small-btn" disabled={busy} onClick={() => { const n = window.prompt("New name for this category", c.name); if (n && n !== c.name) act("/taxonomy/rename", { name: c.name, new: n }, () => "Renamed."); }}>Rename</button>
                  <select aria-label={`Merge ${c.name} into`} disabled={busy} value="" onChange={(e) => e.target.value && act("/taxonomy/merge", { name: c.name, into: e.target.value }, () => "Merged.")}>
                    <option value="">Merge into…</option>
                    {st.categories.filter((o) => o.name !== c.name).map((o) => <option key={o.name} value={o.name}>{o.name}</option>)}
                  </select>
                  <button className="small-btn" disabled={busy} onClick={() => window.confirm(`Delete “${c.name}”? Its files stay in the library and become uncategorised.`) && act("/taxonomy/delete", { name: c.name }, () => "Deleted.")}>Delete</button>
                </span>
              )}
            </div>
            {open[c.name] && c.subs.length > 0 && (
              <ul className="cat-subs">
                {c.subs.map((x) => <li key={x.name}><span>{x.name}</span><span className="small muted">{x.files} file{x.files === 1 ? "" : "s"}</span></li>)}
              </ul>
            )}
          </li>
        ))}
      </ul>
      {grown.length === 0 && <p className="muted small">No category has been added yet. They appear when several files fit none of the built-in ones.</p>}
    </section>
  );
}

/** v0.18 card: coverage per category, gaps, learned-page usefulness and trusted/avoided sites. */
function Coverage() {
  const [st, reload] = usePoll("/coverage/status", 8000);
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  if (!st) return null;

  async function act(path, body, after) {
    setBusy(true);
    const r = await kb.post(path, body || {});
    setMsg(after ? after(r) : r.message || r.error || "");
    setBusy(false);
    reload();
  }

  const L = st.learned;
  return (
    <section className="card learn-card" aria-label="What the library knows and what is missing">
      <div className="learn-head">
        <h2>What it knows and what is missing</h2>
        <label className="learn-switch" title="Let the app add web topics for weak categories by itself (needs Web learning on)">
          <input type="checkbox" checked={st.auto} onChange={async (e) => { await kb.post("/coverage/auto", { on: e.target.checked }); reload(); }} />
          {st.auto ? "Fills gaps itself" : "Gaps: manual"}
        </label>
      </div>
      <p className="muted">
        Each bar shows how well your library covers a category: files, depth and how recent. Categories that your
        questions keep using but that are thin are flagged. “Fill the gaps” adds web-learning topics for the weakest ones.
      </p>
      <ul className="cov-list" aria-label="Coverage by category">
        {st.categories.map((c) => (
          <li key={c.category} className={c.weak ? "weak" : ""}>
            <span className="cov-name">{c.category}</span>
            <div className="learn-bar" role="img" aria-label={`${c.category} coverage ${c.score} out of 100`}><div style={{ width: `${c.score}%` }} /></div>
            <span className="small muted cov-meta">{c.sources} files · {c.passages} passages{c.cited ? ` · used ${c.cited}×` : ""}</span>
            {c.weak && <span className="learn-tag pending" title="Below the coverage target">gap</span>}
          </li>
        ))}
      </ul>
      <div className="learn-form">
        <button className="small-btn" disabled={busy || !st.weak.length} onClick={() => act("/coverage/plan")}>
          Fill the gaps now
        </button>
        <span className="muted small">Web learning must be on for the topics to be read.</span>
      </div>

      <div className="learn-stats">
        <div className="learn-stat"><strong>{L.useful}</strong><span className="small muted">learned pages used in answers</span></div>
        <div className="learn-stat"><strong>{L.unused}</strong><span className="small muted">not used yet</span></div>
        <div className="learn-stat"><strong>{L.total}</strong><span className="small muted">learned pages kept</span></div>
      </div>
      <div className="learn-form">
        <button
          className="small-btn"
          disabled={busy || !L.unused}
          onClick={() => act("/coverage/prune-unused", { days: 45 }, (r) => (r.removed ? `Removed ${r.removed} unused page${r.removed === 1 ? "" : "s"}.` : r.message || "Nothing old and unused."))}
        >
          Remove unused pages (45+ days)
        </button>
        <span className="muted small">Pages with almost no readable text are removed automatically.</span>
      </div>
      {msg && <p className="notice ok">{msg}</p>}

      <h3>Web sites</h3>
      {st.sites.length ? (
        <ul className="learn-list" aria-label="Web sites it has read">
          {st.sites.map((w) => (
            <li key={w.host} style={w.blocked ? { opacity: 0.7 } : undefined}>
              <span>
                {w.host}
                <span className="small muted"><br />{w.useful} used · {w.pages} kept · {w.thin} thin · {w.removed} removed by you</span>
              </span>
              <span className={`learn-tag ${w.blocked ? "failed" : w.manual === 2 ? "done" : ""}`}>
                {w.blocked ? (w.manual === 1 ? "blocked by you" : "skipped — mostly junk") : w.manual === 2 ? "always allowed" : "trusted"}
              </span>
              {w.blocked ? (
                <button className="small-btn" disabled={busy} onClick={() => act("/coverage/site", { host: w.host, action: "allow" }, () => "Allowed.")}>Allow</button>
              ) : (
                <button className="small-btn" disabled={busy} onClick={() => act("/coverage/site", { host: w.host, action: "block" }, () => "Blocked.")}>Block</button>
              )}
              {w.manual !== 0 && (
                <button className="small-btn" disabled={busy} onClick={() => act("/coverage/site", { host: w.host, action: "auto" }, () => "The app decides again.")}>Let the app decide</button>
              )}
            </li>
          ))}
        </ul>
      ) : (
        <p className="muted small">No site yet. Once web learning has read pages, each site appears here with how useful it was.</p>
      )}
    </section>
  );
}

function Lessons() {
  const [st, reload] = usePoll("/lessons/status", 5000);
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  if (!st) return null;

  async function find() {
    setBusy(true);
    const r = await kb.post("/lessons/run", {});
    setMsg(r.message || r.error || "");
    setBusy(false);
    reload();
  }

  return (
    <section className="card learn-card" aria-label="Mistakes and lessons">
      <div className="learn-head">
        <h2>Learn from its mistakes</h2>
        <label className="learn-switch">
          <input
            type="checkbox"
            checked={st.on}
            onChange={async (e) => {
              await kb.post("/lessons/enable", { on: e.target.checked });
              reload();
            }}
          />
          {st.on ? "On" : "Off"}
        </label>
      </div>
      <p className="muted">
        Every answer that goes wrong is noted: a thumbs-down, Regenerate, a Correct, or facts the checker had to remove.
        The app looks for patterns (for example “your corrections are always shorter”) and turns them into short lessons
        it follows in later answers. It then checks whether each lesson really reduced mistakes, and switches it off if it
        did not. You can turn off or delete any lesson.
      </p>
      <div className="learn-stats">
        <div className="learn-stat"><strong>{st.total}</strong><span className="small muted">mistakes noted</span></div>
        <div className="learn-stat"><strong>{st.active}</strong><span className="small muted">lessons in use</span></div>
        <div className="learn-stat"><strong>{st.counts.correct}</strong><span className="small muted">your corrections</span></div>
        <div className="learn-stat"><strong>{st.counts.removed}</strong><span className="small muted">facts removed</span></div>
      </div>
      <div className="learn-form">
        <button className="small-btn" onClick={find} disabled={busy || st.running || !st.on}>
          {busy || st.running ? "Looking…" : "Find patterns now"}
        </button>
        <span className="muted small">It also does this by itself once enough new mistakes have piled up.</span>
      </div>
      {msg && <p className="notice ok">{msg}</p>}

      {st.rules.length > 0 ? (
        <ul className="learn-list" aria-label="Lessons">
          {st.rules.map((r) => (
            <li key={r.id} style={r.status === "off" ? { opacity: 0.6 } : undefined}>
              <span>
                {r.text}
                {r.note && <span className="small muted"><br />{r.note}</span>}
              </span>
              <span className="learn-tag" title="Where this lesson applies">{r.scope === "all" ? "everywhere" : r.scope === "free" ? "Free chat" : r.scope === "library" ? "My files" : "Files + general"}</span>
              <span className="learn-tag" title={r.source === "pattern" ? "Found by counting how you change answers" : "Found by the AI from similar mistakes"}>{r.source === "pattern" ? "counted" : "AI"} · {r.evidence}×</span>
              <span className={`learn-tag ${r.verdict === "working" ? "done" : r.verdict === "not_helping" ? "failed" : "pending"}`}>{VERDICT[r.verdict]}</span>
              <button className="link small" onClick={async () => { await kb.post("/lessons/rule/toggle", { id: r.id, on: r.status !== "active" }); reload(); }}>
                {r.status === "active" ? "Turn off" : "Turn on"}
              </button>
              <button className="link small" onClick={async () => { await kb.post("/lessons/rule/delete", { id: r.id }); reload(); }} aria-label={`Delete lesson ${r.text}`}>Delete</button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="muted small">No lessons yet. They appear after a few corrections or thumbs-downs in Free chat.</p>
      )}

      {st.recent.length > 0 && (
        <>
          <h3 className="model-sub">Latest mistakes noted</h3>
          <ul className="learn-list" aria-label="Recent mistakes">
            {st.recent.map((m) => (
              <li key={m.id}>
                <span className="small">{m.question || "(no question)"}{m.kind === "removed" && m.detail ? ` — ${m.detail}` : ""}</span>
                <span className="learn-tag">{KIND_LABEL[m.kind]}</span>
                {m.rule_id && <span className="learn-tag done">fed a lesson</span>}
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
