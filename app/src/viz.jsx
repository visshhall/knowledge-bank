/**
 * viz.jsx — v0.22 small shared pictures (donut, ring, bars, treemap, stacked bar) used on Overview, Library, Topics, Learning.
 *
 * WHAT:  Plain SVG/CSS pieces, each with a text legend or caption under it so the numbers can also be read:
 *        Donut (parts of a whole, total in the middle), Ring (one figure against a target), Bars (a series over days, optionally
 *        two stacked series), Treemap (rectangles sized by a number, click to pick one), StackBar (one bar split in parts),
 *        Legend (coloured list with counts). catColor() gives each category the same colour on every screen.
 * WHY:   The owner wants pictures first, text beside them. One small set of pieces keeps every screen consistent and adds no
 *        chart library (works offline, tiny).
 * WHEN:  Imported by Glance.jsx, Library.jsx, Topics.jsx, Learning.jsx, Brain.jsx. Each piece animates once when it first appears
 *        and not at all when the computer asks for reduced motion (styles.css .viz-*).
 * CONNECTED TO: styles.css (.viz-*), the screens above.
 */
import { useEffect, useMemo, useState } from "react";

export const PALETTE = ["#23705f", "#f08a68", "#6a4ba8", "#e8b840", "#2c5a43", "#3b7ea1", "#c4567a", "#8a9a2b", "#b5651d", "#5aa6a0", "#7d7d7d", "#d9a0c8"];

/** Built-in categories keep a fixed, distinct colour so neighbours in a chart never look alike. */
const PINNED = ["SIEM & Detection", "Endpoint", "Identity & Access", "Cloud", "Network", "Email & Phishing", "Malware", "Incident Response", "Threat Intel & Hunting", "Vulnerabilities & AppSec", "Governance & Compliance"];

/** The same category always gets the same colour: pinned for built-ins, a stable hash for grown ones. */
export function catColor(name) {
  const i = PINNED.indexOf(name);
  if (i >= 0) return PALETTE[i];
  let h = 0;
  for (const ch of String(name)) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return PALETTE[h % PALETTE.length];
}

/** True one frame after mount, so CSS transitions play on first show. */
function useMounted() {
  const [m, setM] = useState(false);
  useEffect(() => { const t = requestAnimationFrame(() => setM(true)); return () => cancelAnimationFrame(t); }, []);
  return m;
}

export function Legend({ parts, onPick, active }) {
  return (
    <ul className="viz-legend">
      {parts.map((p) => (
        <li key={p.label}>
          <button type="button" className={active === p.label ? "on" : ""} disabled={!onPick} onClick={() => onPick?.(p.label)}>
            <i style={{ background: p.color }} />
            {p.label}
            <span className="muted small"> {p.value.toLocaleString("en-US")}</span>
          </button>
        </li>
      ))}
    </ul>
  );
}

/** Parts of a whole. parts: [{label, value, color}]. center: big text in the middle (default: the total). */
export function Donut({ parts, size = 150, thickness = 20, center, sub, onPick, active }) {
  const shown = parts.filter((p) => p.value > 0);
  const total = shown.reduce((a, p) => a + p.value, 0);
  const r = (size - thickness) / 2, C = 2 * Math.PI * r, mounted = useMounted();
  let acc = 0;
  return (
    <div className="viz-donut">
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} role="img" aria-label={shown.map((p) => `${p.label} ${p.value}`).join(", ") || "No data"}>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--surface-2)" strokeWidth={thickness} />
        {shown.map((p) => {
          const len = total ? (p.value / total) * C : 0, off = acc;
          acc += len;
          return (
            <circle key={p.label} className="viz-arc" cx={size / 2} cy={size / 2} r={r} fill="none" stroke={p.color} strokeWidth={thickness}
                    strokeDasharray={`${mounted ? Math.max(0, len - 1.5) : 0} ${C}`} strokeDashoffset={-off}
                    transform={`rotate(-90 ${size / 2} ${size / 2})`} onClick={() => onPick?.(p.label)} style={{ cursor: onPick ? "pointer" : "default", opacity: active && active !== p.label ? 0.35 : 1 }}>
              <title>{`${p.label}: ${p.value}`}</title>
            </circle>
          );
        })}
        <text x="50%" y={sub ? "48%" : "53%"} textAnchor="middle" className="viz-center">{center ?? total.toLocaleString("en-US")}</text>
        {sub && <text x="50%" y="63%" textAnchor="middle" className="viz-sub">{sub}</text>}
      </svg>
      <Legend parts={shown} onPick={onPick} active={active} />
    </div>
  );
}

/** One figure against a target (0–100 by default). */
export function Ring({ value, max = 100, label, sub, color = "var(--teal)", size = 96, text }) {
  const t = 11, r = (size - t) / 2, C = 2 * Math.PI * r, mounted = useMounted();
  const frac = Math.max(0, Math.min(1, max ? value / max : 0));
  return (
    <figure className="viz-ring">
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} role="img" aria-label={`${label}: ${text ?? Math.round(frac * 100) + "%"}`}>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--surface-2)" strokeWidth={t} />
        <circle className="viz-arc" cx={size / 2} cy={size / 2} r={r} fill="none" stroke={color} strokeWidth={t} strokeLinecap="round"
                strokeDasharray={`${mounted ? frac * C : 0} ${C}`} transform={`rotate(-90 ${size / 2} ${size / 2})`} />
        <text x="50%" y="55%" textAnchor="middle" className="viz-center small">{text ?? `${Math.round(frac * 100)}%`}</text>
      </svg>
      <figcaption><strong>{label}</strong>{sub && <span className="muted small">{sub}</span>}</figcaption>
    </figure>
  );
}

/** A series over days. days: [{date, a, b}] — b is stacked on top of a. */
export function Bars({ days, aColor = "var(--forest)", bColor = "var(--teal)", aLabel = "", bLabel = "", height = 90 }) {
  const max = Math.max(1, ...days.map((d) => (d.a || 0) + (d.b || 0)));
  const w = 300, bw = w / days.length;
  return (
    <svg className="viz-bars" viewBox={`0 0 ${w} ${height}`} role="img" aria-label={`${aLabel} ${days.reduce((x, d) => x + (d.a || 0), 0)}, ${bLabel} ${days.reduce((x, d) => x + (d.b || 0), 0)} over ${days.length} days`}>
      <line x1="0" x2={w} y1={height - 1} y2={height - 1} stroke="var(--line)" />
      {days.map((d, i) => {
        const ha = ((d.a || 0) / max) * (height - 8), hb = ((d.b || 0) / max) * (height - 8);
        return (
          <g key={d.date} style={{ animationDelay: `${i * 14}ms` }} className="viz-bar">
            <title>{`${d.date}: ${d.a || 0} ${aLabel}, ${d.b || 0} ${bLabel}`}</title>
            {ha > 0 && <rect x={i * bw + 1} width={Math.max(1, bw - 2)} y={height - 1 - ha} height={ha} fill={aColor} rx="1.5" />}
            {hb > 0 && <rect x={i * bw + 1} width={Math.max(1, bw - 2)} y={height - 1 - ha - hb} height={hb} fill={bColor} rx="1.5" />}
          </g>
        );
      })}
    </svg>
  );
}

/** One bar split into parts, each with its share. */
export function StackBar({ parts }) {
  const shown = parts.filter((p) => p.value > 0), total = shown.reduce((a, p) => a + p.value, 0), mounted = useMounted();
  return (
    <div>
      <div className="viz-stack" role="img" aria-label={shown.map((p) => `${p.label} ${p.value}`).join(", ") || "No data"}>
        {shown.map((p) => <span key={p.label} title={`${p.label}: ${p.value}`} style={{ width: mounted ? `${(p.value / total) * 100}%` : 0, background: p.color }} />)}
      </div>
      <Legend parts={shown} />
    </div>
  );
}

/** Squarified treemap: rectangles sized by value. items: [{name, value, color}]. */
export function squarify(items, w, h) {
  const total = items.reduce((a, i) => a + i.value, 0) || 1;
  const nodes = items.filter((i) => i.value > 0).map((i) => ({ ...i, area: (i.value / total) * w * h })).sort((a, b) => b.area - a.area);
  const out = [];
  let x = 0, y = 0, W = w, H = h, row = [];
  const worst = (r, side) => {
    const s = r.reduce((a, n) => a + n.area, 0), mx = Math.max(...r.map((n) => n.area)), mn = Math.min(...r.map((n) => n.area));
    return Math.max((side * side * mx) / (s * s), (s * s) / (side * side * mn));
  };
  const flush = () => {
    const s = row.reduce((a, n) => a + n.area, 0);
    if (W >= H) { const cw = s / H; let cy = y; row.forEach((n) => { const ch = n.area / cw; out.push({ ...n, x, y: cy, w: cw, h: ch }); cy += ch; }); x += cw; W -= cw; }
    else { const rh = s / W; let cx = x; row.forEach((n) => { const cw2 = n.area / rh; out.push({ ...n, x: cx, y, w: cw2, h: rh }); cx += cw2; }); y += rh; H -= rh; }
    row = [];
  };
  for (const n of nodes) {
    const side = Math.min(W, H);
    if (row.length && worst([...row, n], side) > worst(row, side)) flush();
    row.push(n);
  }
  if (row.length) flush();
  return out;
}

export function Treemap({ items, height = 230, onPick, active }) {
  const W = 600, tiles = useMemo(() => squarify(items, W, height), [JSON.stringify(items), height]);
  return (
    <svg className="viz-tree" viewBox={`0 0 ${W} ${height}`} role="img" aria-label={items.map((i) => `${i.name} ${i.value}`).join(", ") || "No data"} preserveAspectRatio="none">
      {tiles.map((t, i) => (
        <g key={t.name} className="viz-tile" style={{ animationDelay: `${i * 40}ms`, cursor: onPick ? "pointer" : "default", opacity: active && active !== t.name ? 0.4 : 1 }} onClick={() => onPick?.(t.name)}>
          <title>{`${t.name}: ${t.value}`}</title>
          <rect x={t.x + 1.5} y={t.y + 1.5} width={Math.max(0, t.w - 3)} height={Math.max(0, t.h - 3)} rx="8" fill={t.color} fillOpacity="0.88" stroke={active === t.name ? "var(--ink)" : "none"} strokeWidth="2.5" />
          {t.w > 70 && t.h > 34 && <text x={t.x + 11} y={t.y + 22} className="viz-tile-name">{t.name.length > t.w / 7.5 ? t.name.slice(0, Math.max(3, Math.floor(t.w / 7.5) - 1)) + "…" : t.name}</text>}
          {t.w > 70 && t.h > 52 && <text x={t.x + 11} y={t.y + 40} className="viz-tile-n">{t.value}</text>}
        </g>
      ))}
    </svg>
  );
}
