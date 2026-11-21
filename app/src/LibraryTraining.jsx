/**
 * LibraryTraining.jsx — v0.23 "Learn from your files": the app reads every page of every file, and the owner turns that
 * into a real trained model in three steps.
 *
 * WHAT:  Pictures first, each with a line of text:
 *          - a ring: share of all pages read (with pages left and a time estimate),
 *          - bars: pages read per day for 30 days,
 *          - a donut: question-and-answer pairs kept vs dropped, and why they were dropped,
 *          - one bar per subject: how much of it has been read.
 *        The newest kept pairs (with file and page) and a Reject link for any that look wrong.
 *        A three-step path, drawn as a line of steps that fill in as they are done:
 *          1. Make the training package (every page as text + the checked pairs + chat examples, and the notebook),
 *          2. Train on a free Google GPU (opens Google Colab; the package's README says what to click),
 *          3. Bring in the trained model (choose kb-model.gguf; Chat switches to it; one click switches back).
 *        A plain note on what training does and does not do, so expectations are right.
 * WHY:   Owner (18 Nov 2026): the model should read every PDF and learn directly, not have "half knowledge"; the old
 *        training count was stuck because it only counted rated Free-chat answers.
 * WHEN:  On the Learning screen, under the "at a glance" pictures. Polls GET /libtrain/status every 5 s (every 1.5 s
 *        while a trained model is being brought in).
 * CONNECTED TO: bridge.js (kb.get/post, kb.openTraining, kb.pickModel, kb.webOpen 'colab'); server.py /libtrain/* →
 *        libtrain.py; viz.jsx (Ring, Bars, Donut, catColor); Learning.jsx (renders it); styles.css (.lt-*).
 */
import { useState } from "react";
import { kb, usePoll } from "./bridge.js";
import { Bars, Donut, Ring, catColor } from "./viz.jsx";

const REASON_LABELS = {
  "a fact is not on the page": "A number or ID not on the page",
  "not enough of it is on the page": "Says more than the page",
  "refers to the page": "Not readable on its own",
  "too short": "Too short",
  "too long": "Too long",
  repeat: "Repeated",
  // v0.23.1: made visible instead of disappearing silently
  "no pairs written": "Page gave no pairs",
  "the AI could not read it": "AI could not read the page",
};
const REASON_COLORS = ["#f08a68", "#c4567a", "#e8b840", "#7d7d7d", "#b5651d", "#d9a0c8", "#6a4ba8", "#3b7ea1"];

function hours(h) {
  if (h === null || h === undefined) return "working out how long";
  if (h < 1) return "under an hour";
  if (h < 48) return `about ${Math.round(h)} hours`;
  return `about ${Math.round(h / 24)} days`;
}

export default function LibraryTraining() {
  const [busyImport, setBusyImport] = useState(false);
  const [st, reload] = usePoll("/libtrain/status", busyImport ? 1500 : 5000);
  const [pkg, setPkg] = useState(null);
  const [working, setWorking] = useState("");
  const [msg, setMsg] = useState(null);

  if (!st) return null;
  const p = st.pages, pr = st.pairs;
  const imp = st.import ?? {};
  if (busyImport && imp.state !== "running") setTimeout(() => setBusyImport(false), 0);

  const reasonParts = Object.entries(pr.reasons ?? {}).map(([k, v], i) => ({
    label: REASON_LABELS[k] ?? k, value: v, color: REASON_COLORS[i % REASON_COLORS.length],
  }));
  const steps = [
    { n: 1, title: "Make the training package", done: Boolean(st.last_package || pkg?.ok) },
    { n: 2, title: "Train on a free Google GPU", done: st.tuned.installed },
    { n: 3, title: "Bring in the trained model", done: st.tuned.installed },
  ];

  async function toggle() {
    await kb.post("/libtrain/on", { on: !st.on });
    reload();
  }
  async function makePackage() {
    setWorking("package");
    setPkg(await kb.post("/libtrain/package", {}));
    setWorking("");
    reload();
  }
  async function bringIn() {
    const path = await kb.pickModel();
    if (!path) return;
    const r = await kb.post("/libtrain/import", { path });
    setMsg(r);
    if (r.ok) setBusyImport(true);
    reload();
  }
  async function use(which) {
    setMsg(await kb.post("/libtrain/use", { which }));
    reload();
  }
  async function reject(id) {
    await kb.post("/libtrain/reject", { id });
    reload();
  }

  return (
    <section className="card learn-card glance" aria-label="Learn from your files">
      <div className="learn-head">
        <h2>Learn from your files</h2>
        <button className="small-btn secondary" onClick={toggle}>{st.on ? "Pause reading" : "Resume reading"}</button>
      </div>
      <p className="muted">
        The app reads every page of your own files and writes question-and-answer pairs from each one. Every answer is
        checked against its page; anything not on the page is dropped. Together with the full text of every page, this is
        what your model is trained on. {st.on ? st.message : "Reading is paused."}
      </p>

      <div className="glance-grid">
        <div className="glance-panel">
          <h3>Pages read</h3>
          <div className="glance-rings">
            <Ring value={p.done} max={Math.max(1, p.total)} label={`${p.done.toLocaleString("en-US")} of ${p.total.toLocaleString("en-US")}`}
                  sub="pages" color="var(--teal)" />
          </div>
          <p className="muted small">
            {p.left ? `${p.left.toLocaleString("en-US")} pages left, ${hours(st.eta_hours)}${st.sec_per_page ? ` (${Math.round(st.sec_per_page)} s a page)` : ""}. Pauses while you chat.`
              : p.total ? "Every page has been read." : "Add files in Library to start."}
            {" "}{st.files.done} of {st.files.total} files finished.
          </p>
        </div>
        <div className="glance-panel wide">
          <h3>Pages read per day</h3>
          <Bars days={st.daily.map((d) => ({ date: d.date, a: d.pages }))} aLabel="pages read" aColor="var(--teal)" />
          <p className="muted small">{st.daily.reduce((a, d) => a + d.pairs, 0).toLocaleString("en-US")} checked pairs written in the last 30 days.</p>
        </div>
        <div className="glance-panel">
          <h3>Checked pairs</h3>
          <Donut size={120} thickness={16} center={pr.kept.toLocaleString("en-US")} sub="kept"
                 parts={[{ label: "Kept", value: pr.kept, color: "var(--teal)" }, ...reasonParts]} />
          <p className="muted small">Dropped pairs are never trained on. The page's text still is.</p>
        </div>
        <div className="glance-panel wide">
          <h3>Read so far, by subject</h3>
          {st.categories.length ? (
            <ul className="topic-bars">
              {st.categories.slice(0, 10).map((c) => (
                <li key={c.name}>
                  <span className="tb-name" title={c.name}>{c.name}</span>
                  <span className="tb-track"><span className="tb-fill" style={{ width: `${c.pct}%`, background: catColor(c.name) }} /></span>
                  <span className="muted small tb-n">{c.pct}% of {c.total.toLocaleString("en-US")}</span>
                </li>
              ))}
            </ul>
          ) : <p className="muted small">Subjects appear once files are read.</p>}
        </div>
      </div>

      {st.recent.length > 0 && (
        <div className="lt-recent">
          <h3>Newest pairs</h3>
          {st.recent.map((r) => (
            <article key={r.id} className="learn-ex">
              <p className="q">{r.q}</p>
              <p>{r.a}</p>
              <p className="small muted">
                {r.file}, page {r.page} · <button className="link small" onClick={() => reject(r.id)}>Reject (wrong)</button>
              </p>
            </article>
          ))}
        </div>
      )}

      <ol className="lt-steps" aria-label="Train your model in three steps">
        {steps.map((s) => (
          <li key={s.n} className={s.done ? "done" : ""}>
            <span className="lt-dot" aria-hidden="true">{s.done ? "✓" : s.n}</span>
            <span>{s.title}</span>
          </li>
        ))}
      </ol>

      <div className="lt-step">
        <h3>1. Make the training package</h3>
        <p className="muted small">
          Every page of your files as text, all checked pairs and your Free-chat examples, plus the training notebook. You can
          make it at any time. The text always covers every page, and making it again later adds the newer pairs.
        </p>
        <div className="learn-form">
          <button onClick={makePackage} disabled={working === "package" || !p.total}>
            {working === "package" ? "Making the package…" : "Make training package"}
          </button>
          {(pkg?.folder || st.last_package) && (
            <button className="secondary" onClick={() => kb.openTraining(pkg?.folder || st.last_package)}>Show folder</button>
          )}
        </div>
        {pkg && <p className={`notice ${pkg.ok ? "ok" : "error"}`}>{pkg.message}{pkg.note ? ` ${pkg.note}` : ""}</p>}
      </div>

      <div className="lt-step">
        <h3>2. Train on a free Google GPU</h3>
        <p className="muted small">
          Your laptop's graphics card is too small to train a 4B model, so training runs in Google Colab for free (about 2–4
          hours). Upload <code>KB_finetune.ipynb</code> from the package folder, choose a T4 GPU, press Run all, and upload the
          zip when asked. README.txt in the folder walks through every click. It saves <code>kb-model.gguf</code> to your
          Google Drive.
        </p>
        <div className="learn-form">
          <button className="secondary" onClick={() => kb.webOpen("colab", "colab")}>Open Google Colab</button>
        </div>
      </div>

      <div className="lt-step">
        <h3>3. Bring in the trained model</h3>
        <p className="muted small">Choose the kb-model.gguf you downloaded. The app adds it to the AI engine and Chat starts using it.</p>
        <div className="learn-form">
          <button onClick={bringIn} disabled={imp.state === "running"}>
            {imp.state === "running" ? "Bringing it in…" : "Bring in the trained model"}
          </button>
          {st.tuned.installed && !st.tuned.active && <button className="secondary" onClick={() => use("tuned")}>Use the trained model</button>}
          {st.tuned.active && st.tuned.previous && (
            <button className="secondary" onClick={() => use("previous")}>Switch back to {st.tuned.previous}</button>
          )}
        </div>
        {imp.state === "running" && <div className="learn-bar indeterminate" aria-hidden="true"><div /></div>}
        {imp.message && imp.state !== "idle" && <p className={`notice ${imp.state === "error" ? "error" : "ok"}`}>{imp.message}</p>}
        {msg && !msg.ok && <p className="notice error">{msg.message || msg.error}</p>}
        {msg?.ok && msg.current && <p className="notice ok">{msg.message}</p>}
        {st.tuned.active && <p className="notice ok">Chat is answering with the model trained on your files.</p>}
      </div>

      <p className="lt-note small">
        <strong>What training does:</strong> the model learns your subjects, terms and the way your files explain them, so its
        own answers are much closer to your material. <strong>What it does not do:</strong> no model remembers every exact
        number or line of 200 PDFs. For answers with page references, “My files” answers still read the pages themselves.
      </p>
    </section>
  );
}
