/**
 * Insights.jsx — v0.20 the "Insights" screen: the patterns the app finds, drawn and animated.
 *
 * WHAT:  Four views of what the library and the learning loops are doing (data from engine insights.py, one call):
 *        1. KNOWLEDGE MAP — a circle per category (size = files, colour = how well covered it is, dashed ring = a category
 *           the app added itself); lines join categories that share files, so related areas sit close together. Positions are
 *           worked out once with a small spring layout; on opening, circles glide from the middle to their place. Click a
 *           circle to see its numbers and sub-categories.
 *        2. COVERAGE HEATMAP — categories down, the last weeks across; each cell's depth = files added that week, or how often
 *           answers cited the category ("Added" / "Used" switch). Cells fade in row by row.
 *        3. MISTAKE TRENDS — bars per week split by kind (thumbs-down, Regenerate, Correct, facts removed), a line for the
 *           share of answers that went wrong, and diamonds on the weeks a lesson was added, so you can see whether lessons help.
 *        4. TIMELINE — a 30-day strip (files added, pages learned, mistakes) and a list of what the app did on its own.
 * WHY:   The owner asked for visualisation and animation so patterns can be seen, not only listed. No chart library: plain SVG,
 *        so it works offline and adds no weight.
 * WHEN:  Opened from the sidebar's Knowledge section; refreshes every 15 s while open. Animations are short, play once when the
 *        data first appears, and are switched off when the computer asks for reduced motion (styles.css).
 * CONNECTED TO: bridge.js → engine GET /insights/all (server.py → insights.py); styles.css (.ins-*); icons.jsx; App.jsx, Sidebar.jsx.
 */
import { useEffect, useMemo, useState } from "react";
import { usePoll } from "./bridge.js";

const KIND = {
  down: { label: "Thumbs-down", color: "var(--coral)" },
  regen: { label: "Regenerate", color: "var(--mustard)" },
  correct: { label: "Corrected by you", color: "var(--violet)" },
  removed: { label: "Facts removed", color: "var(--teal)" },
};
const EVENT_COLOR = { learned: "var(--teal)", category: "var(--violet)", lesson: "var(--mustard)", topic: "var(--forest)", site: "var(--coral)" };

export default function Insights() {
  const [data] = usePoll("/insights/all", 15000, { weeks: 12 });
  if (!data) return <p className="muted">Loading…</p>;
  return (
    <div className="learn-grid">
      <header className="page-head">
        <h1>Insights</h1>
        <p className="lede">
          The patterns the app finds in your library and in how you use it: what it knows, where it is thin, how often it gets
          things wrong, and what it has done by itself.
        </p>
      </header>
      <KnowledgeMap map={data.map} />
      <Heatmap heat={data.heatmap} />
      <MistakeTrends m={data.mistakes} />
      <Timeline t={data.timeline} />
    </div>
  );
}

/* ---------------------------------------------------------------- knowledge map */

/** A small spring layout: linked categories pull together, all circles push apart. Deterministic (no randomness). */
export function layout(nodes, links, w = 760, h = 420) {
  const n = nodes.length;
  const pos = nodes.map((_, i) => ({ x: w / 2 + Math.cos((2 * Math.PI * i) / n) * 140, y: h / 2 + Math.sin((2 * Math.PI * i) / n) * 110 }));
  const radius = nodes.map((nd) => 14 + Math.sqrt(nd.files) * 7);
  const idx = Object.fromEntries(nodes.map((nd, i) => [nd.id, i]));
  for (let step = 0; step < 220; step++) {
    const cool = 1 - step / 220;
    const force = pos.map(() => ({ x: 0, y: 0 }));
    for (let i = 0; i < n; i++) {
      for (let j = i + 1; j < n; j++) {
        let dx = pos[i].x - pos[j].x, dy = pos[i].y - pos[j].y;
        const d = Math.max(1, Math.hypot(dx, dy));
        const min = radius[i] + radius[j] + 18;
        const push = d < min * 2.4 ? ((min * 2.4 - d) / d) * 0.5 : 0;
        force[i].x += dx * push; force[i].y += dy * push;
        force[j].x -= dx * push; force[j].y -= dy * push;
      }
    }
    for (const l of links) {
      const a = idx[l.a], b = idx[l.b];
      if (a === undefined || b === undefined) continue;
      const dx = pos[b].x - pos[a].x, dy = pos[b].y - pos[a].y;
      const pull = 0.02 * Math.min(l.weight, 6);
      force[a].x += dx * pull; force[a].y += dy * pull;
      force[b].x -= dx * pull; force[b].y -= dy * pull;
    }
    for (let i = 0; i < n; i++) {
      force[i].x += (w / 2 - pos[i].x) * 0.01; force[i].y += (h / 2 - pos[i].y) * 0.01;
      pos[i].x = Math.min(w - radius[i] - 6, Math.max(radius[i] + 6, pos[i].x + force[i].x * 0.6 * cool));
      pos[i].y = Math.min(h - radius[i] - 18, Math.max(radius[i] + 6, pos[i].y + force[i].y * 0.6 * cool));
    }
  }
  return nodes.map((nd, i) => ({ ...nd, x: pos[i].x, y: pos[i].y, r: radius[i] }));
}

function KnowledgeMap({ map }) {
  const W = 760, H = 420;
  const placed = useMemo(() => layout(map.nodes, map.links, W, H), [JSON.stringify(map.nodes.map((x) => [x.id, x.files])), map.links.length]);
  const [ready, setReady] = useState(false);
  const [pick, setPick] = useState(null);
  useEffect(() => { const t = setTimeout(() => setReady(true), 60); return () => clearTimeout(t); }, []);
  const byId = Object.fromEntries(placed.map((p) => [p.id, p]));
  const sel = pick && byId[pick];
  return (
    <section className="card learn-card" aria-label="Knowledge map">
      <div className="learn-head"><h2>Knowledge map</h2></div>
      <p className="muted">
        Bigger circle = more files. Green = well covered, amber = thin. A dashed ring is a category the app added by itself. Lines
        join categories that share files.
      </p>
      <svg className="ins-map" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Map of categories">
        {map.links.map((l) => {
          const a = byId[l.a], b = byId[l.b];
          return a && b ? <line key={l.a + l.b} x1={a.x} y1={a.y} x2={b.x} y2={b.y} className="ins-link" strokeWidth={1 + Math.min(l.weight, 8) * 0.6} style={{ opacity: ready ? 0.45 : 0 }} /> : null;
        })}
        {placed.map((p, i) => (
          <g key={p.id} className={`ins-node ${pick === p.id ? "on" : ""}`} onClick={() => setPick(pick === p.id ? null : p.id)} tabIndex={0}
             onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && setPick(pick === p.id ? null : p.id)}
             style={{ transform: `translate(${ready ? p.x : W / 2}px, ${ready ? p.y : H / 2}px)`, transitionDelay: `${i * 45}ms` }}>
            <title>{`${p.id}: ${p.files} files, coverage ${p.score}/100`}</title>
            <circle r={p.r} fill={p.weak ? "var(--mustard)" : "var(--teal)"} fillOpacity={0.25 + (p.score / 100) * 0.6} stroke={p.weak ? "var(--mustard)" : "var(--teal)"} strokeWidth="2" strokeDasharray={p.grown ? "5 4" : undefined} />
            <text y={p.r + 13} textAnchor="middle" className="ins-label">{p.id}</text>
            <text y="4" textAnchor="middle" className="ins-count">{p.files}</text>
          </g>
        ))}
      </svg>
      {sel ? (
        <div className="ins-detail">
          <strong>{sel.id}</strong>
          <span>{sel.files} files · {sel.passages} passages · {sel.learned} learned from the web · coverage {sel.score}/100</span>
          {sel.subs.length > 0 && <span className="small muted">Sub-categories: {sel.subs.join(", ")}</span>}
        </div>
      ) : <p className="muted small">Click a circle for its numbers.</p>}
    </section>
  );
}

/* ---------------------------------------------------------------- heatmap */

function Heatmap({ heat }) {
  const [mode, setMode] = useState("added");
  const rows = heat.rows.filter((r) => r.total > 0 || heat.rows.length <= 12);
  const max = Math.max(1, ...rows.flatMap((r) => r[mode]));
  const weeks = heat.weeks;
  return (
    <section className="card learn-card" aria-label="Coverage heatmap">
      <div className="learn-head">
        <h2>Coverage heatmap</h2>
        <div className="ins-switch" role="group" aria-label="What the colour shows">
          <button className={mode === "added" ? "on" : ""} onClick={() => setMode("added")}>Added</button>
          <button className={mode === "used" ? "on" : ""} onClick={() => setMode("used")}>Used in answers</button>
        </div>
      </div>
      <p className="muted">Each square is one week, the latest on the right. Darker = {mode === "added" ? "more files added to that category" : "answers cited that category more often"}.</p>
      <div className="ins-heat" style={{ gridTemplateColumns: `minmax(120px, 190px) repeat(${weeks}, 1fr)` }} key={mode}>
        {rows.map((r, ri) => (
          <div className="ins-heat-row" key={r.category}>
            <span className="ins-heat-name">{r.category}</span>
            {r[mode].map((v, wi) => (
              <span key={wi} className="ins-cell" title={`${r.category}, ${wi === weeks - 1 ? "this week" : `${weeks - 1 - wi} week${weeks - 1 - wi === 1 ? "" : "s"} ago`}: ${v}`}
                    style={{ background: v ? `color-mix(in srgb, var(--teal) ${18 + (v / max) * 82}%, transparent)` : "var(--surface-2)", animationDelay: `${ri * 40 + wi * 8}ms` }} />
            ))}
          </div>
        ))}
        <div className="ins-heat-axis"><span /><span>{weeks} weeks ago</span><span>now</span></div>
      </div>
    </section>
  );
}

/* ---------------------------------------------------------------- mistake trends */

function MistakeTrends({ m }) {
  const W = 760, H = 220, pad = { l: 34, r: 40, t: 12, b: 24 };
  const n = m.weeks, bw = (W - pad.l - pad.r) / n;
  const maxTotal = Math.max(1, ...m.total);
  const y = (v) => pad.t + (1 - v / maxTotal) * (H - pad.t - pad.b);
  const rates = m.rate.map((r) => (r === null ? null : Math.min(1, r)));
  const anyData = m.total.some((v) => v > 0);
  const points = rates.map((r, i) => (r === null ? null : [pad.l + bw * i + bw / 2, pad.t + (1 - r) * (H - pad.t - pad.b)]));
  const path = points.reduce((d, p) => (p ? d + (d && !d.endsWith("M") ? "L" : "M") + p[0].toFixed(1) + " " + p[1].toFixed(1) + " " : d), "");
  return (
    <section className="card learn-card" aria-label="Mistake trends">
      <div className="learn-head"><h2>Mistake trends</h2></div>
      <p className="muted">
        Bars: answers that went wrong each week. Line: share of that week’s answers that went wrong (right-hand scale). Diamonds: a
        lesson was added that week — the line should fall after them.
      </p>
      {!anyData ? <p className="muted small">No mistakes noted in these weeks.</p> : (
        <svg className="ins-chart" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Mistakes per week">
          {[0, 0.5, 1].map((f) => (
            <g key={f}>
              <line x1={pad.l} x2={W - pad.r} y1={pad.t + (1 - f) * (H - pad.t - pad.b)} y2={pad.t + (1 - f) * (H - pad.t - pad.b)} className="ins-grid" />
              <text x={pad.l - 6} y={pad.t + (1 - f) * (H - pad.t - pad.b) + 4} textAnchor="end" className="ins-axis">{Math.round(f * maxTotal)}</text>
              <text x={W - pad.r + 6} y={pad.t + (1 - f) * (H - pad.t - pad.b) + 4} className="ins-axis">{Math.round(f * 100)}%</text>
            </g>
          ))}
          {m.total.map((_, i) => {
            let acc = 0;
            return (
              <g key={i}>
                {Object.keys(KIND).map((k) => {
                  const v = m.kinds[k][i];
                  if (!v) return null;
                  const top = y(acc + v), h = y(acc) - top;
                  acc += v;
                  return <rect key={k} x={pad.l + bw * i + bw * 0.18} y={top} width={bw * 0.64} height={h} fill={KIND[k].color} className="ins-bar" style={{ animationDelay: `${i * 35}ms` }}><title>{`${KIND[k].label}: ${v}`}</title></rect>;
                })}
              </g>
            );
          })}
          {path && <path d={path} className="ins-line" pathLength="1" fill="none" />}
          {points.map((p, i) => p && <circle key={i} cx={p[0]} cy={p[1]} r="3" className="ins-dot"><title>{`${Math.round(m.rate[i] * 100)}% of ${m.answers[i]} answers`}</title></circle>)}
          {m.lessons.map((l, i) => (
            <g key={i} transform={`translate(${pad.l + bw * l.week + bw / 2} ${H - pad.b + 11})`}>
              <title>{`Lesson added: ${l.text}`}</title>
              <rect x="-5" y="-5" width="10" height="10" transform="rotate(45)" className={`ins-lesson ${l.status === "off" ? "off" : ""}`} />
            </g>
          ))}
        </svg>
      )}
      <div className="ins-legend">
        {Object.entries(KIND).map(([k, v]) => <span key={k}><i style={{ background: v.color }} />{v.label}</span>)}
        <span><i className="ln" />Share wrong</span><span><i className="dia" />Lesson added</span>
      </div>
    </section>
  );
}

/* ---------------------------------------------------------------- timeline */

function Timeline({ t }) {
  const max = Math.max(1, ...t.days.flatMap((d) => [d.files, d.learned, d.mistakes]));
  const W = 760, H = 70, bw = W / t.days.length;
  const series = [["files", "Files added", "var(--forest)"], ["learned", "Web pages learned", "var(--teal)"], ["mistakes", "Mistakes", "var(--coral)"]];
  return (
    <section className="card learn-card" aria-label="Timeline">
      <div className="learn-head"><h2>Timeline</h2></div>
      <p className="muted">The last 30 days, and what the app has done by itself.</p>
      <svg className="ins-strip" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Activity in the last 30 days">
        {t.days.map((d, i) => series.map(([k, , color], si) => d[k] ? (
          <rect key={i + k} x={i * bw + 1 + si * (bw / 3.2)} width={bw / 3.4} y={H - 4 - (d[k] / max) * (H - 10)} height={(d[k] / max) * (H - 10)} fill={color} className="ins-bar" style={{ animationDelay: `${i * 18}ms` }}>
            <title>{`${d.date}: ${d[k]} ${k}`}</title>
          </rect>
        ) : null))}
      </svg>
      <div className="ins-legend">{series.map(([k, label, color]) => <span key={k}><i style={{ background: color }} />{label}</span>)}</div>
      {t.events.length ? (
        <ol className="ins-events" aria-label="What the app did">
          {t.events.map((e, i) => (
            <li key={i} style={{ animationDelay: `${Math.min(i, 15) * 40}ms` }}>
              <i style={{ background: EVENT_COLOR[e.kind] || "var(--line)" }} />
              <span>{e.text}</span>
              <span className="small muted">{String(e.at).slice(0, 10)}</span>
            </li>
          ))}
        </ol>
      ) : <p className="muted small">Nothing yet. As it learns from the web, adds categories and writes lessons, each step appears here.</p>}
    </section>
  );
}
