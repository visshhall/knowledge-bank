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
 * WHEN:  Opened from the sidebar's Knowledge section. Polls /learn/status every 3 s while open (so a
 *        running round shows live) and /training/status every 6 s.
 * CONNECTED TO: bridge.js → engine /learn/status, /learn/enable, /learn/limits, /learn/run, /learn/topic/*,
 *        /learn/watch/*, /learn/pages, /learn/remove-all, /training/status, /training/examples,
 *        /training/example/status, /training/export (server.py → learner.py, training.py); styles.css (.learn-*).
 */
import { useState } from "react";
import Icon from "./icons.jsx";
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
      <WebLearning />
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
