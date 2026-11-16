/**
 * Brain.jsx — v0.21 "Live learning": watch the app learn. Every file and web page is a dot; a new one appears next to the
 * things it relates to, lights up, and connects to them.
 *
 * WHAT:  - A canvas map. Dot = one file or web page (colour = category, size = how much text, dashed ring = read from the web).
 *          Lines = "these two are about the same thing" (thicker/brighter = closer). Dots of one category drift together.
 *        - When the engine links a new file (brain.py, every ~15 s) the next refresh (every 4 s) brings it in: it pops in beside its
 *          closest relatives, a ripple spreads from it, and a bright pulse runs along each new line to the file it relates to.
 *        - "Replay growth" takes the newest dots away and brings them back one by one in the order they were learned.
 *        - Hover a dot for its name; click it to see, as text, which files it relates to and how closely.
 *        - Side panel (all text, for anyone who prefers reading): status, "What just happened" feed, category legend (click one to
 *          highlight it), "Link new files now".
 * WHY:   The owner wanted to SEE the AI being trained — new dots, related to old data, correlated with incoming data — with text
 *        only as a companion. Pan with drag, zoom with the wheel. No library: plain canvas so it works offline.
 * WHEN:  Opened from the sidebar's Knowledge section ("Live learning"). Refreshes every 4 s while open; "Pause" stops refreshing.
 *        Motion is skipped when the computer asks for reduced motion (dots simply appear in place).
 * CONNECTED TO: bridge.js → engine GET /brain/graph, GET /brain/related, POST /brain/run (server.py → brain.py); styles.css (.brain-*);
 *        App.jsx, Sidebar.jsx.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { kb } from "./bridge.js";

const REDUCED = typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
const ease = (t) => 1 + 2.7 * Math.pow(t - 1, 3) + 1.7 * Math.pow(t - 1, 2); // easeOutBack: a small pop

/** Radius from the amount of text (kept in a readable range). */
const radiusOf = (passages) => 5 + Math.min(11, Math.sqrt(passages || 1) * 1.4);

export default function Brain() {
  const canvasRef = useRef(null);
  const wrapRef = useRef(null);
  const sim = useRef({ nodes: new Map(), links: [], alpha: 1, view: { x: 0, y: 0, k: 1 }, first: true, since: null, hover: null,
                       focusCat: null, filter: "all", selected: null, paused: false, size: { w: 800, h: 520 }, replay: null, autoFit: true });
  const colors = useRef(new Map());
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [paused, setPaused] = useState(false);
  const [filter, setFilter] = useState("all");
  const [focusCat, setFocusCat] = useState(null);
  const [selected, setSelected] = useState(null);
  const [related, setRelated] = useState(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");
  const [replaying, setReplaying] = useState(false);

  const colorOf = useCallback((cat) => {
    if (!colors.current.has(cat)) colors.current.set(cat, catColor(cat)); // v0.22: same colour as every other screen
    return colors.current.get(cat);
  }, []);

  /* ------------------------------------------------------------ data in */
  const merge = useCallback((g) => {
    const s = sim.current;
    const now = performance.now();
    const present = new Set(g.nodes.map((n) => n.id));
    for (const id of s.nodes.keys()) if (!present.has(id)) s.nodes.delete(id);
    const byId = new Map(g.nodes.map((n) => [n.id, n]));
    const nbr = new Map();
    for (const l of g.links) {
      (nbr.get(l.a) ?? nbr.set(l.a, []).get(l.a)).push(l.b);
      (nbr.get(l.b) ?? nbr.set(l.b, []).get(l.b)).push(l.a);
    }
    const { w, h } = s.size;
    g.nodes.forEach((n, i) => {
      let node = s.nodes.get(n.id);
      if (node) { Object.assign(node, { title: n.title, cat: n.category, learned: n.learned, r: radiusOf(n.passages), color: colorOf(n.category), at: n.at }); return; }
      const friends = (nbr.get(n.id) ?? []).map((id) => s.nodes.get(id)).filter(Boolean);
      let x, y;
      if (friends.length) { x = friends.reduce((a, f) => a + f.x, 0) / friends.length + (Math.random() - 0.5) * 50; y = friends.reduce((a, f) => a + f.y, 0) / friends.length + (Math.random() - 0.5) * 50; }
      else if (s.first) { const a = Math.random() * 6.283, d = 40 + Math.random() * Math.min(w, h) * 0.38; x = w / 2 + Math.cos(a) * d; y = h / 2 + Math.sin(a) * d; }
      else { const a = Math.random() * 6.283; x = w / 2 + Math.cos(a) * w * 0.45; y = h / 2 + Math.sin(a) * h * 0.45; }
      const fresh = !s.first && n.new;
      s.nodes.set(n.id, { id: n.id, title: n.title, cat: n.category, learned: n.learned, r: radiusOf(n.passages), color: colorOf(n.category), at: n.at,
                          x, y, vx: 0, vy: 0, born: fresh ? now : -1e9, appear: REDUCED ? 1 : fresh ? 0 : -(i * 12) / 1000, hidden: false });
    });
    s.links = g.links.map((l) => ({ ...l }));
    s.since = g.now;
    s.first = false;
    s.alpha = REDUCED ? 0 : 1;
    if (REDUCED) settle(s, 250);
  }, [colorOf]);

  useEffect(() => {
    let live = true, timer;
    const pull = async () => {
      if (sim.current.paused || sim.current.replay) return schedule();
      const g = await kb.get("/brain/graph", { limit: 300, ...(sim.current.since ? { since: sim.current.since } : {}) });
      if (!live) return;
      if (g?.error) setError(g.error); else { setError(""); setData(g); merge(g); }
      schedule();
    };
    const schedule = () => { if (live) timer = setTimeout(pull, 4000); };
    pull();
    return () => { live = false; clearTimeout(timer); };
  }, [merge]);

  useEffect(() => { sim.current.paused = paused; }, [paused]);
  useEffect(() => { sim.current.filter = filter; }, [filter]);
  useEffect(() => { sim.current.focusCat = focusCat; }, [focusCat]);
  useEffect(() => {
    sim.current.selected = selected;
    setRelated(null);
    if (selected) kb.get("/brain/related", { id: selected }).then((r) => !r?.error && setRelated(r));
  }, [selected]);

  /* ------------------------------------------------------------ animation loop */
  useEffect(() => {
    const canvas = canvasRef.current, wrap = wrapRef.current;
    if (!canvas || !wrap) return;
    const ctx = canvas.getContext("2d");
    let raf, dead = false;
    const fit = () => {
      const w = wrap.clientWidth, h = Math.max(380, Math.min(620, Math.round(w * 0.62))), dpr = window.devicePixelRatio || 1;
      canvas.width = w * dpr; canvas.height = h * dpr; canvas.style.height = h + "px";
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      sim.current.size = { w, h };
    };
    fit();
    const ro = new ResizeObserver(fit); ro.observe(wrap);
    const frame = (t) => {
      if (dead) return;
      const s = sim.current;
      if (!s.paused || s.replay) step(s, t);
      draw(ctx, s, t);
      raf = requestAnimationFrame(frame);
    };
    raf = requestAnimationFrame(frame);
    return () => { dead = true; cancelAnimationFrame(raf); ro.disconnect(); };
  }, []);

  /* ------------------------------------------------------------ pointer: hover, click, drag, zoom */
  const toWorld = (e) => {
    const r = canvasRef.current.getBoundingClientRect(), v = sim.current.view;
    return { x: (e.clientX - r.left - v.x) / v.k, y: (e.clientY - r.top - v.y) / v.k, sx: e.clientX - r.left, sy: e.clientY - r.top };
  };
  const hit = (p) => {
    let best = null, bd = 1e9;
    for (const n of sim.current.nodes.values()) {
      if (n.hidden || n.appear <= 0.05 || !visible(sim.current, n)) continue;
      const d = Math.hypot(n.x - p.x, n.y - p.y);
      if (d <= n.r + 5 && d < bd) { best = n; bd = d; }
    }
    return best;
  };
  const drag = useRef(null);
  const onDown = (e) => { sim.current.autoFit = false; const p = toWorld(e); drag.current = { sx: p.sx, sy: p.sy, vx: sim.current.view.x, vy: sim.current.view.y, moved: false, node: hit(p) }; canvasRef.current.setPointerCapture(e.pointerId); };
  const onMove = (e) => {
    const p = toWorld(e), d = drag.current;
    if (d && (Math.abs(p.sx - d.sx) > 3 || Math.abs(p.sy - d.sy) > 3)) d.moved = true;
    if (d?.moved) { sim.current.view.x = d.vx + (p.sx - d.sx); sim.current.view.y = d.vy + (p.sy - d.sy); }
    else sim.current.hover = hit(p)?.id ?? null;
  };
  const onUp = (e) => { const d = drag.current; drag.current = null; if (d && !d.moved) setSelected(d.node ? (d.node.id === sim.current.selected ? null : d.node.id) : null); };
  const onWheel = (e) => {
    e.preventDefault();
    sim.current.autoFit = false;
    const s = sim.current, v = s.view, p = toWorld(e), k = Math.min(3, Math.max(0.4, v.k * (e.deltaY < 0 ? 1.12 : 0.9)));
    v.x = p.sx - p.x * k; v.y = p.sy - p.y * k; v.k = k;
  };
  useEffect(() => { const c = canvasRef.current; c?.addEventListener("wheel", onWheel, { passive: false }); return () => c?.removeEventListener("wheel", onWheel); });

  /* ------------------------------------------------------------ actions */
  async function linkNow() {
    setBusy(true);
    const r = await kb.post("/brain/run", { limit: 60 });
    setNote(r.error ? r.error : r.done ? `Linked ${r.done} file${r.done === 1 ? "" : "s"}.` : r.message || "Nothing waiting.");
    setBusy(false);
  }
  function replay() {
    const s = sim.current;
    const all = [...s.nodes.values()].sort((a, b) => String(a.at).localeCompare(String(b.at)));
    const later = all.slice(-Math.min(40, all.length));
    if (later.length < 2) return setNote("Not enough dots to replay yet.");
    later.forEach((n) => { n.hidden = true; });
    s.replay = true; setReplaying(true);
    let i = 0;
    const next = () => {
      if (i >= later.length) { s.replay = null; setReplaying(false); return; }
      const n = later[i++];
      const mates = s.links.filter((l) => l.a === n.id || l.b === n.id).map((l) => s.nodes.get(l.a === n.id ? l.b : l.a)).filter((m) => m && !m.hidden);
      if (mates.length) { n.x = mates.reduce((a, m) => a + m.x, 0) / mates.length + (Math.random() - 0.5) * 50; n.y = mates.reduce((a, m) => a + m.y, 0) / mates.length + (Math.random() - 0.5) * 50; }
      n.hidden = false; n.born = performance.now(); n.appear = REDUCED ? 1 : 0; s.alpha = 1;
      s.replayTimer = setTimeout(next, REDUCED ? 80 : 500);
    };
    next();
  }
  useEffect(() => () => clearTimeout(sim.current.replayTimer), []);

  /* ------------------------------------------------------------ text side */
  const cats = useMemo(() => {
    const m = new Map();
    (data?.nodes ?? []).forEach((n) => m.set(n.category, (m.get(n.category) ?? 0) + 1));
    return [...m.entries()].sort((a, b) => b[1] - a[1]);
  }, [data]);

  if (error) return <p className="muted">Could not load the live view: {error}</p>;
  const st = data?.status;
  const empty = data && data.total === 0;
  return (
    <div className="learn-grid">
      <header className="page-head">
        <h1>Live learning</h1>
        <p className="lede">
          Every file and web page is a dot. When something new is learned it appears next to what it relates to, lights up, and
          connects to it, so you can watch the library grow and see what links to what.
        </p>
      </header>
      <section className="card learn-card" aria-label="Live learning map">
        <div className="brain-bar">
          <div className="ins-switch" role="group" aria-label="Which dots to show">
            {[["all", "All"], ["files", "My files"], ["web", "Read from the web"]].map(([k, l]) => (
              <button key={k} className={filter === k ? "on" : ""} onClick={() => setFilter(k)}>{l}</button>
            ))}
          </div>
          <button className="small-btn" onClick={() => setPaused(!paused)}>{paused ? "Resume live updates" : "Pause live updates"}</button>
          <button className="small-btn" disabled={replaying || !data || data.total < 3} onClick={replay}>{replaying ? "Replaying…" : "Replay growth"}</button>
          <button className="small-btn" disabled={busy || !st?.pending} onClick={linkNow}>{busy ? "Linking…" : `Link new files now${st?.pending ? ` (${st.pending})` : ""}`}</button>
        </div>
        <div className="brain-stage" ref={wrapRef}>
          <canvas ref={canvasRef} role="img" aria-label={`Map of ${data?.total ?? 0} files and web pages and how they relate. The same information is listed as text beside the map.`}
                  onPointerDown={onDown} onPointerMove={onMove} onPointerUp={onUp} onPointerLeave={() => { sim.current.hover = null; }} />
          {empty && (
            <div className="brain-empty">
              <strong>Nothing to draw yet</strong>
              <span>Add files or let it read the web. New dots appear here within a minute.{st?.pending ? ` ${st.pending} waiting to be linked.` : ""}</span>
            </div>
          )}
        </div>
        <p className="muted small">
          Drag to move, scroll to zoom, click a dot for what it relates to. Dashed ring = read from the web. Brighter, thicker line = more alike.
          {note && <strong> {note}</strong>}
        </p>
      </section>

      <section className="card learn-card" aria-label="Live learning details">
        <div className="brain-cols">
          <div>
            <h2>Status</h2>
            {st && (
              <ul className="brain-facts">
                <li><strong>{data.total}</strong> dots · {data.links.length} connections shown</li>
                <li>{st.message}</li>
                <li>
                  {st.methods.embed ? `${st.methods.embed} linked by meaning` : ""}
                  {st.methods.embed && st.methods.terms ? " · " : ""}
                  {st.methods.terms ? `${st.methods.terms} linked by shared key words (upgrades once ${st.model} is ready)` : ""}
                </li>
                {!st.model_ready && <li className="muted small">The embedding model ({st.model}) is not available right now; start the AI engine or download it in Setup for better links.</li>}
              </ul>
            )}
            <h3>Categories</h3>
            <ul className="brain-legend" aria-label="Categories (click to highlight)">
              {cats.map(([c, n]) => (
                <li key={c}>
                  <button className={focusCat === c ? "on" : ""} onClick={() => setFocusCat(focusCat === c ? null : c)}>
                    <i style={{ background: colorOf(c) }} />{c}<span className="muted small"> {n}</span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
          <div>
            <h2>{selected && related ? related.title : "What just happened"}</h2>
            {selected && related ? (
              <div>
                <p className="muted small">{related.category} · {related.learned ? "read from the web" : "your file"}</p>
                {related.related.length ? (
                  <ul className="brain-rel" aria-label="Related files">
                    {related.related.map((r) => (
                      <li key={r.id}>
                        <button onClick={() => setSelected(r.id)}><i style={{ background: colorOf(r.category) }} />{r.title}</button>
                        <span className="brain-sim" title={`${r.how} related`}><b style={{ width: `${Math.round(Math.min(1, r.sim) * 100)}%` }} /></span>
                        <span className="small muted">{r.how}</span>
                      </li>
                    ))}
                  </ul>
                ) : <p className="muted small">Nothing related yet. It starts a new area.</p>}
                <button className="small-btn" onClick={() => setSelected(null)}>Back to the feed</button>
              </div>
            ) : (
              <ol className="ins-events brain-feed" aria-label="Recent arrivals">
                {(data?.events ?? []).slice(0, 14).map((e) => (
                  <li key={e.id}>
                    <i style={{ background: colorOf(e.category) }} />
                    <span><button className="brain-link" onClick={() => setSelected(e.source_id)}>{e.text}</button></span>
                    <span className="small muted">{String(e.at).slice(5, 16)}</span>
                  </li>
                ))}
                {!data?.events?.length && <li className="muted small">Nothing yet. New files and pages appear here as they are linked.</li>}
              </ol>
            )}
          </div>
        </div>
      </section>
    </div>
  );
}

/* ---------------------------------------------------------------- simulation */

function visible(s, n) {
  if (s.filter === "files" && n.learned) return false;
  if (s.filter === "web" && !n.learned) return false;
  return true;
}

/** Runs the layout to rest in one go (reduced motion, and the first picture). */
function settle(s, rounds) { for (let i = 0; i < rounds; i++) { s.alpha = Math.max(s.alpha, 0.3); physics(s); } s.alpha = 0; }

/** One physics step: dots push apart, linked dots pull together, categories gather. */
function physics(s) {
  const list = [...s.nodes.values()].filter((n) => !n.hidden);
  const { w, h } = s.size, a = s.alpha;
  const cent = new Map();
  for (const n of list) { const c = cent.get(n.cat) ?? { x: 0, y: 0, n: 0 }; c.x += n.x; c.y += n.y; c.n++; cent.set(n.cat, c); }
  for (let i = 0; i < list.length; i++) {
    const p = list[i];
    for (let j = i + 1; j < list.length; j++) {
      const q = list[j], dx = p.x - q.x, dy = p.y - q.y, d2 = dx * dx + dy * dy;
      const min = p.r + q.r + 14;
      if (d2 < 190 * 190 && d2 > 0.01) {
        const d = Math.sqrt(d2), f = ((min * 3 - d) > 0 ? (min * 3 - d) / d : 0) * 0.06 * a + (d < min ? 0.5 : 0);
        p.vx += dx * f; p.vy += dy * f; q.vx -= dx * f; q.vy -= dy * f;
      }
    }
    const c = cent.get(p.cat);
    p.vx += (c.x / c.n - p.x) * 0.004 * a + (w / 2 - p.x) * 0.0012 * a;
    p.vy += (c.y / c.n - p.y) * 0.004 * a + (h / 2 - p.y) * 0.0012 * a;
  }
  for (const l of s.links) {
    const p = s.nodes.get(l.a), q = s.nodes.get(l.b);
    if (!p || !q || p.hidden || q.hidden) continue;
    const dx = q.x - p.x, dy = q.y - p.y, d = Math.max(1, Math.hypot(dx, dy)), rest = 70 - Math.min(1, l.sim) * 30;
    const f = ((d - rest) / d) * (0.015 + Math.min(1, l.sim) * 0.03) * Math.max(a, 0.2);
    p.vx += dx * f; p.vy += dy * f; q.vx -= dx * f; q.vy -= dy * f;
  }
  for (const n of list) { n.vx *= 0.82; n.vy *= 0.82; n.x += n.vx; n.y += n.vy; }
}

/** Keeps the whole map in view (until the owner pans or zooms): eases the view toward the box around all visible dots. */
function fitView(s) {
  const list = [...s.nodes.values()].filter((n) => !n.hidden && visible(s, n));
  if (!list.length) return;
  let x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9;
  for (const n of list) { x0 = Math.min(x0, n.x - n.r); y0 = Math.min(y0, n.y - n.r); x1 = Math.max(x1, n.x + n.r); y1 = Math.max(y1, n.y + n.r); }
  const { w, h } = s.size, pad = 34;
  const k = Math.min(1.6, Math.max(0.4, Math.min((w - pad * 2) / Math.max(40, x1 - x0), (h - pad * 2 - 20) / Math.max(40, y1 - y0))));
  const tx = w / 2 - ((x0 + x1) / 2) * k, ty = h / 2 + 8 - ((y0 + y1) / 2) * k, v = s.view, e = REDUCED ? 1 : 0.08;
  v.k += (k - v.k) * e; v.x += (tx - v.x) * e; v.y += (ty - v.y) * e;
}

function step(s, t) {
  if (s.alpha > 0.015) { physics(s); s.alpha *= 0.992; }
  if (s.autoFit) fitView(s);
  for (const n of s.nodes.values()) if (!n.hidden && n.appear < 1) n.appear = Math.min(1, n.appear + 0.025);
}

/* ---------------------------------------------------------------- drawing */

function draw(ctx, s, t) {
  const { w, h } = s.size, v = s.view, now = performance.now();
  ctx.clearRect(0, 0, w, h);
  ctx.save();
  ctx.translate(v.x, v.y); ctx.scale(v.k, v.k);
  const sel = s.selected, selNbr = new Set();
  if (sel) for (const l of s.links) { if (l.a === sel) selNbr.add(l.b); if (l.b === sel) selNbr.add(l.a); }
  const dim = (n) => (s.focusCat && n.cat !== s.focusCat) || (sel && n.id !== sel && !selNbr.has(n.id));
  // links, with a travelling pulse along the newest ones
  for (const l of s.links) {
    const p = s.nodes.get(l.a), q = s.nodes.get(l.b);
    if (!p || !q || p.hidden || q.hidden || !visible(s, p) || !visible(s, q) || p.appear <= 0 || q.appear <= 0) continue;
    const grow = Math.min(p.appear, q.appear), sim = Math.min(1, l.sim);
    const on = sel && (l.a === sel || l.b === sel);
    ctx.globalAlpha = (dim(p) && dim(q) ? 0.06 : 0.14 + sim * 0.5) * grow * (on ? 1.6 : 1);
    ctx.strokeStyle = on ? "#1d2921" : "#2c5a43";
    ctx.lineWidth = (0.8 + sim * 2.4) * (on ? 1.4 : 1);
    ctx.beginPath(); ctx.moveTo(p.x, p.y); ctx.lineTo(q.x, q.y); ctx.stroke();
    const fresh = p.born > q.born ? p : q, other = fresh === p ? q : p, age = (now - fresh.born) / 1000;
    if (!REDUCED && age < 4) {
      const u = (age * 0.7) % 1;
      ctx.globalAlpha = 1 - age / 4; ctx.fillStyle = "#e8b840";
      ctx.beginPath(); ctx.arc(fresh.x + (other.x - fresh.x) * u, fresh.y + (other.y - fresh.y) * u, 3.2, 0, 6.283); ctx.fill();
    }
  }
  // dots
  for (const n of s.nodes.values()) {
    if (n.hidden || !visible(s, n) || n.appear <= 0) continue;
    const age = (now - n.born) / 1000, pop = REDUCED ? 1 : ease(Math.min(1, n.appear)), r = n.r * pop;
    ctx.globalAlpha = dim(n) ? 0.18 : 0.9;
    if (!REDUCED && age < 4) {                                   // glow + ripple on arrival
      ctx.save(); ctx.globalAlpha = 0.9 * (1 - age / 4); ctx.strokeStyle = n.color; ctx.lineWidth = 2;
      ctx.beginPath(); ctx.arc(n.x, n.y, r + age * 26, 0, 6.283); ctx.stroke(); ctx.restore();
      ctx.shadowColor = n.color; ctx.shadowBlur = 18 * (1 - age / 4);
    }
    ctx.fillStyle = n.color; ctx.beginPath(); ctx.arc(n.x, n.y, Math.max(0.1, r), 0, 6.283); ctx.fill();
    ctx.shadowBlur = 0;
    if (n.learned) { ctx.setLineDash([3, 3]); ctx.strokeStyle = "#1d2921"; ctx.lineWidth = 1.4; ctx.beginPath(); ctx.arc(n.x, n.y, r + 3, 0, 6.283); ctx.stroke(); ctx.setLineDash([]); }
    if (n.id === sel) { ctx.strokeStyle = "#1d2921"; ctx.lineWidth = 2.5; ctx.beginPath(); ctx.arc(n.x, n.y, r + 5, 0, 6.283); ctx.stroke(); }
  }
  // labels: hovered, selected and arrivals of the last few seconds
  ctx.globalAlpha = 1; ctx.font = "600 12px sans-serif"; ctx.textAlign = "center";
  for (const n of s.nodes.values()) {
    if (n.hidden || !visible(s, n)) continue;
    const show = n.id === s.hover || n.id === sel || (!REDUCED && now - n.born < 5000);
    if (!show) continue;
    const text = n.title.length > 38 ? n.title.slice(0, 36) + "…" : n.title, tw = ctx.measureText(text).width + 12;
    ctx.fillStyle = "rgba(247,249,245,.92)"; ctx.fillRect(n.x - tw / 2, n.y - n.r - 26, tw, 20);
    ctx.fillStyle = "#1d2921"; ctx.fillText(text, n.x, n.y - n.r - 12);
  }
  ctx.restore();
}
