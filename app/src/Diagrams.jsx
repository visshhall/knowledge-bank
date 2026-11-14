/**
 * Diagrams.jsx — every lesson visual, drawn from data and explained
 * interactively.
 *
 * WHAT:  <Visual spec autoPlay onDone /> picks the drawing for a lesson visual:
 *          flow / tree → node cards laid out by ELK (a professional graph
 *                        layout engine, offline), rounded arrows that "flow",
 *                        a moving packet showing direction
 *          chain       → animated timeline
 *          stack       → layers that lift as they're explained
 *          cards       → flip cards (term on the front, meaning on the back)
 *          compare     → comparison grid with row/column highlighting
 *          query       → a query explained line by line
 *          chart       → interactive line chart of your numbers (log or
 *                        linear scale, hover read-outs, ratio to previous)
 *          verify      → your sheet checked against a formula, row by row
 *          bits        → a 32-bit mask that builds bit by bit
 *          subnetlab   → type any IP + prefix: network, broadcast, usable
 *                        range, mask, wildcard, the bitwise AND animated, and
 *                        where the network sits among its neighbours
 *          table       → the exact cells of a sheet/table
 *        "Walk me through" (most visuals): plays the parts one at a time
 *        with a caption that explains each part; ‹ › step manually; click a
 *        part to explain just that. Lesson autoplay (Lesson.jsx) starts the
 *        walk automatically and moves on when it ends (onDone).
 * WHY:   Owner (14 Nov 2026): diagrams looked "weak"; wanted them "more
 *        advanced and better looking, with interactive animation" and a
 *        better way of explaining. Each diagram now teaches in order — the
 *        way a teacher draws and talks — instead of showing everything at
 *        once. All positions are computed; the AI only supplies words.
 *        Windows "reduce animations" turns motion off (content stays).
 * WHEN:  Rendered by Lesson.jsx (lesson steps) and Topics.jsx (figures).
 * CONNECTED TO: Lesson.jsx, Topics.jsx; elkjs; styles.css (.dg-*, .walk-*,
 *        .chart-*, .lab-*, .tl-*, .lyr-*, .flip-*). No engine calls.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import ELK from "elkjs/lib/elk.bundled.js";

const elk = new ELK();
const TONES = ["teal", "coral", "violet", "mustard"];
const reduceMotion = () => Boolean(window.matchMedia?.("(prefers-reduced-motion: reduce)").matches);

// ---------------------------------------------------------------------------
// Walk-through: step through a visual's parts with captions
// ---------------------------------------------------------------------------

/**
 * i = -1 shows everything (overview); 0…count-1 is the part being explained.
 * play() runs through all parts automatically; onDone fires at the end.
 */
function useWalk(count, ms, autoPlay, onDone) {
  const [i, setI] = useState(-1);
  const [playing, setPlaying] = useState(false);
  const doneRef = useRef(onDone);
  doneRef.current = onDone;

  useEffect(() => {
    if (autoPlay && count) {
      setI(-1);
      setPlaying(true);
    }
  }, [autoPlay, count]);

  useEffect(() => {
    if (!playing) return undefined;
    if (i >= count - 1) {
      const t = setTimeout(() => {
        setPlaying(false);
        doneRef.current?.();
      }, ms);
      return () => clearTimeout(t);
    }
    const t = setTimeout(() => setI((x) => x + 1), i < 0 ? 350 : ms);
    return () => clearTimeout(t);
  }, [playing, i, count, ms]);

  return {
    i,
    playing,
    play() {
      if (i >= count - 1) setI(-1);
      setPlaying(true);
    },
    pause: () => setPlaying(false),
    go(k) {
      setPlaying(false);
      setI(Math.max(-1, Math.min(count - 1, k)));
    },
  };
}

/** Controls + caption under a visual. */
function WalkBar({ walk, count, caption, partName = "part" }) {
  return (
    <div className="walk">
      <div className="walk-controls">
        {walk.playing ? (
          <button className="walk-play" onClick={walk.pause} aria-label="Pause">
            <span className="walk-icon pause" aria-hidden="true" /> Pause
          </button>
        ) : (
          <button className="walk-play" onClick={walk.play}>
            <span className="walk-icon play" aria-hidden="true" />{" "}
            {walk.i >= 0 && walk.i < count - 1 ? "Continue" : "Walk me through"}
          </button>
        )}
        <button className="walk-step" onClick={() => walk.go(walk.i - 1)} disabled={walk.i <= 0} aria-label={`Previous ${partName}`}>
          ‹
        </button>
        <ol className="walk-dots" aria-label={`${count} ${partName}s`}>
          {Array.from({ length: count }, (_, k) => (
            <li key={k}>
              <button className={k === walk.i ? "on" : k < walk.i ? "seen" : ""} onClick={() => walk.go(k)} aria-label={`${partName} ${k + 1}`} />
            </li>
          ))}
        </ol>
        <button className="walk-step" onClick={() => walk.go(walk.i + 1)} disabled={walk.i >= count - 1} aria-label={`Next ${partName}`}>
          ›
        </button>
        {walk.i >= 0 && (
          <button className="walk-all link small" onClick={() => walk.go(-1)}>
            Show all
          </button>
        )}
      </div>
      <p className={`walk-caption ${walk.i >= 0 ? "on" : ""}`} aria-live="polite">
        {caption}
      </p>
    </div>
  );
}

/** Width of an element, kept up to date. */
function useWidth(ref, fallback = 800) {
  const [w, setW] = useState(fallback);
  useEffect(() => {
    const el = ref.current;
    if (!el) return undefined;
    const ro = new ResizeObserver(([e]) => setW(Math.floor(e.contentRect.width)));
    ro.observe(el);
    return () => ro.disconnect();
  }, [ref]);
  return w;
}

// ---------------------------------------------------------------------------
// Flow / tree (ELK layout)
// ---------------------------------------------------------------------------

function wrap(label, max = 22) {
  const words = String(label).split(/\s+/);
  const lines = [""];
  for (const w of words) {
    const cur = lines[lines.length - 1];
    if ((cur + " " + w).trim().length > max && cur) lines.push(w);
    else lines[lines.length - 1] = (cur + " " + w).trim();
  }
  if (lines.length > 2) return [lines[0], lines.slice(1).join(" ").slice(0, max - 1) + "…"];
  return lines;
}

function boxSize(label) {
  const lines = wrap(label);
  const width = Math.max(130, Math.min(230, Math.max(...lines.map((l) => l.length)) * 8 + 58));
  return { width, height: lines.length === 1 ? 52 : 70, lines };
}

/** Orthogonal route → SVG path with rounded corners. */
function roundedPath(pts, r = 10) {
  if (pts.length < 2) return "";
  let d = `M${pts[0].x},${pts[0].y}`;
  for (let k = 1; k < pts.length - 1; k++) {
    const a = pts[k - 1];
    const b = pts[k];
    const c = pts[k + 1];
    const d1 = Math.min(r, Math.hypot(b.x - a.x, b.y - a.y) / 2);
    const d2 = Math.min(r, Math.hypot(c.x - b.x, c.y - b.y) / 2);
    const ux = Math.sign(b.x - a.x);
    const uy = Math.sign(b.y - a.y);
    const vx = Math.sign(c.x - b.x);
    const vy = Math.sign(c.y - b.y);
    d += ` L${b.x - ux * d1},${b.y - uy * d1} Q${b.x},${b.y} ${b.x + vx * d2},${b.y + vy * d2}`;
  }
  const last = pts[pts.length - 1];
  return `${d} L${last.x},${last.y}`;
}

/** Nodes in teaching order: start nodes first, then along the arrows. */
function teachingOrder(nodes, edges) {
  const incoming = new Map(nodes.map((n) => [n.id, 0]));
  for (const e of edges) incoming.set(e.to, (incoming.get(e.to) ?? 0) + 1);
  const out = new Map(nodes.map((n) => [n.id, []]));
  for (const e of edges) out.get(e.from)?.push(e.to);
  const order = [];
  const seen = new Set();
  const queue = nodes.filter((n) => !incoming.get(n.id)).map((n) => n.id);
  if (!queue.length && nodes.length) queue.push(nodes[0].id);
  while (queue.length) {
    const id = queue.shift();
    if (seen.has(id)) continue;
    seen.add(id);
    order.push(id);
    for (const t of out.get(id) ?? []) if (!seen.has(t)) queue.push(t);
  }
  for (const n of nodes) if (!seen.has(n.id)) order.push(n.id);
  return order;
}

function Graph({ nodes, edges, direction, autoPlay, onDone }) {
  const [layout, setLayout] = useState(null);
  const [dir, setDir] = useState(direction);
  const box = useRef(null);
  const room = useWidth(box, 0);
  const shape = JSON.stringify({ nodes, edges });
  const order = useMemo(() => teachingOrder(nodes, edges), [shape]); // eslint-disable-line react-hooks/exhaustive-deps
  const walk = useWalk(order.length, 2400, autoPlay, onDone);

  useEffect(() => setDir(direction), [direction, shape]);

  useEffect(() => {
    let alive = true;
    const graph = {
      id: "root",
      layoutOptions: {
        "elk.algorithm": "layered",
        "elk.direction": dir,
        "elk.edgeRouting": "ORTHOGONAL",
        "elk.layered.spacing.nodeNodeBetweenLayers": "64",
        "elk.spacing.nodeNode": "30",
        "elk.spacing.edgeLabel": "6",
        "elk.layered.nodePlacement.strategy": "BRANDES_KOEPF",
      },
      children: nodes.map((n) => ({ id: n.id, ...boxSize(n.label) })),
      edges: edges.map((e, k) => ({
        id: `e${k}`,
        sources: [e.from],
        targets: [e.to],
        labels: e.label ? [{ text: e.label, width: e.label.length * 6.6 + 12, height: 18 }] : [],
      })),
    };
    elk.layout(graph).then((g) => alive && setLayout(g)).catch(() => alive && setLayout("error"));
    return () => {
      alive = false;
    };
  }, [shape, dir]); // eslint-disable-line react-hooks/exhaustive-deps

  // Too wide even at 75%? Lay it out top-to-bottom instead.
  useEffect(() => {
    if (layout && layout !== "error" && room && dir === "RIGHT" && (layout.width + 40) * 0.75 > room) setDir("DOWN");
  }, [layout, room, dir]);

  if (layout === "error") return <FlipCards items={nodes.map((n) => ({ label: n.label, detail: n.detail }))} />;

  const byId = Object.fromEntries(nodes.map((n, k) => [n.id, { ...n, k }]));
  const current = walk.i >= 0 ? order[walk.i] : null;
  const visited = new Set(walk.i >= 0 ? order.slice(0, walk.i + 1) : order);
  const step = (id) => order.indexOf(id) + 1;
  const curNode = current ? byId[current] : null;
  const caption = curNode
    ? `${step(current)}. ${curNode.label}${curNode.detail ? ` — ${curNode.detail}` : ""}`
    : `${nodes.length} parts. Press “Walk me through” to follow them in order, or click any box.`;

  const pad = 20;
  let svg = <div className="dg-loading">Drawing…</div>;
  if (layout) {
    const natural = layout.width + pad * 2;
    const fitW = room && natural > room ? Math.max(room, natural * 0.75) : natural;
    svg = (
      <svg
        className={`dg-graph ${walk.i >= 0 ? "walking" : ""}`}
        viewBox={`${-pad} ${-pad} ${layout.width + pad * 2} ${layout.height + pad * 2}`}
        width={fitW}
        height={(fitW * (layout.height + pad * 2)) / natural}
        role="img"
        aria-label={nodes.map((n) => n.label).join(", ")}
      >
        <defs>
          <marker id="dg-arrow" viewBox="0 0 10 10" refX="8.5" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M0,0 L10,5 L0,10 L2.5,5 z" className="dg-arrowhead" />
          </marker>
          <filter id="dg-shadow" x="-20%" y="-20%" width="140%" height="160%">
            <feDropShadow dx="0" dy="3" stdDeviation="4" floodColor="#1d2921" floodOpacity="0.14" />
          </filter>
        </defs>
        {layout.edges.map((e, k) => {
          const src = edges[k].from;
          const dst = edges[k].to;
          const active = current === dst && visited.has(src);
          const on = walk.i < 0 || (visited.has(src) && visited.has(dst));
          return (e.sections || []).map((s, j) => {
            const d = roundedPath([s.startPoint, ...(s.bendPoints || []), s.endPoint]);
            return (
              <g key={`${k}-${j}`} className={`dg-edge-g ${on ? "" : "dim"} ${active ? "active" : ""}`}>
                <path className="dg-edge" d={d} markerEnd="url(#dg-arrow)" />
                <path className="dg-edge-flow" d={d} />
                {active && !reduceMotion() && (
                  <circle r="5" className="dg-packet">
                    <animateMotion dur="1.1s" repeatCount="indefinite" path={d} />
                  </circle>
                )}
                {(e.labels || []).map((l, m) => (
                  <g key={m}>
                    <rect className="dg-edge-label-bg" x={l.x} y={l.y} width={l.width} height={l.height} rx="9" />
                    <text className="dg-edge-label" x={l.x + l.width / 2} y={l.y + 13} textAnchor="middle">
                      {l.text}
                    </text>
                  </g>
                ))}
              </g>
            );
          });
        })}
        {layout.children.map((c) => {
          const n = byId[c.id];
          const { lines } = boxSize(n.label);
          const tone = TONES[n.k % TONES.length];
          const state = current === c.id ? "current" : visited.has(c.id) ? "seen" : "later";
          return (
            <g
              key={c.id}
              className={`dg-node tone-${tone} ${state}`}
              style={{ "--d": `${n.k * 0.08}s`, transformOrigin: `${c.x + c.width / 2}px ${c.y + c.height / 2}px` }}
              onClick={() => walk.go(order.indexOf(c.id))}
              role="button"
              tabIndex={0}
              aria-label={`${n.label}${n.detail ? `: ${n.detail}` : ""}`}
              onKeyDown={(ev) => (ev.key === "Enter" || ev.key === " ") && walk.go(order.indexOf(c.id))}
            >
              {state === "current" && <rect className="dg-glow" x={c.x - 6} y={c.y - 6} width={c.width + 12} height={c.height + 12} rx="18" />}
              <rect className="dg-card" x={c.x} y={c.y} width={c.width} height={c.height} rx="14" filter="url(#dg-shadow)" />
              <rect className="dg-accent" x={c.x} y={c.y} width="6" height={c.height} rx="3" />
              <circle className="dg-badge" cx={c.x + 24} cy={c.y + c.height / 2} r="12" />
              <text className="dg-badge-n" x={c.x + 24} y={c.y + c.height / 2 + 4.5} textAnchor="middle">
                {step(c.id)}
              </text>
              {lines.map((line, m) => (
                <text key={m} className="dg-label" x={c.x + 44} y={c.y + c.height / 2 + (m - (lines.length - 1) / 2) * 18 + 5}>
                  {line}
                </text>
              ))}
            </g>
          );
        })}
      </svg>
    );
  }
  return (
    <div className="dg-graph-box" ref={box}>
      {svg}
      <WalkBar walk={walk} count={order.length} caption={caption} partName="step" />
    </div>
  );
}

function treeToGraph(spec) {
  const nodes = [{ id: "n0", label: spec.root }];
  const edges = [];
  let next = 1;
  const walk = (children, parent) => {
    for (const c of children || []) {
      const id = `n${next++}`;
      nodes.push({ id, label: c.label, detail: c.detail });
      edges.push({ from: parent, to: id });
      walk(c.children, id);
    }
  };
  walk(spec.children, "n0");
  return { nodes, edges };
}

// ---------------------------------------------------------------------------
// Timeline, layers, flip cards, comparison, query
// ---------------------------------------------------------------------------

function Timeline({ stages, autoPlay, onDone }) {
  const walk = useWalk(stages.length, 2400, autoPlay, onDone);
  const pct = walk.i < 0 ? 100 : (100 * walk.i) / Math.max(1, stages.length - 1);
  const cur = walk.i >= 0 ? stages[walk.i] : null;
  return (
    <div>
      <div className="tl" style={{ "--n": stages.length }}>
        <div className="tl-track" aria-hidden="true">
          <span className="tl-fill" style={{ width: `${pct}%` }} />
        </div>
        <ol className="tl-stages">
          {stages.map((s, k) => {
            const state = walk.i < 0 ? "" : k === walk.i ? "current" : k < walk.i ? "seen" : "later";
            return (
              <li key={k} className={`tl-stage tone-${TONES[k % TONES.length]} ${state}`} style={{ "--d": `${k * 0.1}s` }}>
                <button className="tl-dot" onClick={() => walk.go(k)} aria-label={`Stage ${k + 1}: ${s.label}`}>
                  {k + 1}
                </button>
                <span className="tl-label">{s.label}</span>
                {s.detail && <span className="tl-detail">{s.detail}</span>}
              </li>
            );
          })}
        </ol>
      </div>
      <WalkBar
        walk={walk}
        count={stages.length}
        partName="stage"
        caption={
          cur
            ? `Stage ${walk.i + 1} of ${stages.length}: ${cur.label}${cur.detail ? ` — ${cur.detail}` : ""}`
            : `${stages.length} stages, in order. Walk through them or click a number.`
        }
      />
    </div>
  );
}

function Layers({ layers, autoPlay, onDone }) {
  const walk = useWalk(layers.length, 2200, autoPlay, onDone);
  const cur = walk.i >= 0 ? layers[walk.i] : null;
  return (
    <div>
      <ol className="lyr">
        {layers.map((l, k) => {
          const state = walk.i < 0 ? "" : k === walk.i ? "current" : "dimmed";
          return (
            <li key={k} className={`lyr-item tone-${TONES[k % TONES.length]} ${state}`} style={{ "--k": k, "--d": `${k * 0.08}s` }}>
              <button onClick={() => walk.go(k)}>
                <span className="lyr-n">{k + 1}</span>
                <span className="lyr-label">{l.label}</span>
                {l.detail && <span className="lyr-detail">{l.detail}</span>}
              </button>
            </li>
          );
        })}
      </ol>
      <WalkBar
        walk={walk}
        count={layers.length}
        partName="layer"
        caption={cur ? `Layer ${walk.i + 1}: ${cur.label}${cur.detail ? ` — ${cur.detail}` : ""}` : "Layers from top to bottom. Walk through them or click one."}
      />
    </div>
  );
}

function FlipCards({ items, autoPlay, onDone }) {
  const walk = useWalk(items.length, 2000, autoPlay, onDone);
  const [flipped, setFlipped] = useState(() => new Set());
  const showBack = (k) => flipped.has(k) || (walk.i >= 0 && k <= walk.i);
  const hasDetails = items.some((it) => it.detail);
  return (
    <div>
      <ul className="flip-grid">
        {items.map((it, k) => (
          <li key={k} style={{ "--d": `${k * 0.07}s` }}>
            <button
              className={`flip tone-${TONES[k % TONES.length]} ${showBack(k) && it.detail ? "back" : ""} ${walk.i === k ? "current" : ""}`}
              onClick={() =>
                setFlipped((f) => {
                  const next = new Set(f);
                  if (next.has(k)) next.delete(k);
                  else next.add(k);
                  return next;
                })
              }
              aria-pressed={showBack(k)}
            >
              <span className="flip-inner">
                <span className="flip-face front">
                  <strong>{it.label}</strong>
                  {it.detail && <em>Click to see what it means</em>}
                </span>
                <span className="flip-face rear">
                  <strong>{it.label}</strong>
                  <span>{it.detail}</span>
                </span>
              </span>
            </button>
          </li>
        ))}
      </ul>
      {hasDetails && (
        <WalkBar
          walk={walk}
          count={items.length}
          partName="card"
          caption={walk.i >= 0 ? `${items[walk.i].label} — ${items[walk.i].detail || ""}` : "Each card flips to show its meaning. Walk through them or click one."}
        />
      )}
    </div>
  );
}

function Compare({ columns, rows, autoPlay, onDone }) {
  const walk = useWalk(rows.length, 2400, autoPlay, onDone);
  const [col, setCol] = useState(null);
  const cur = walk.i >= 0 ? rows[walk.i] : null;
  return (
    <div>
      <div className="dg-compare-wrap">
        <table className="dg-compare">
          <thead>
            <tr>
              <th />
              {columns.map((c, k) => (
                <th key={k} className={`tone-${TONES[k % TONES.length]} ${col === k ? "hot" : ""}`} onMouseEnter={() => setCol(k)} onMouseLeave={() => setCol(null)}>
                  {c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r, k) => (
              <tr key={k} className={walk.i < 0 ? "" : k === walk.i ? "current" : "dimmed"} onClick={() => walk.go(k)} style={{ "--d": `${k * 0.08}s` }}>
                <th scope="row">{r.label}</th>
                {r.cells.map((c, j) => (
                  <td key={j} className={col === j ? "hot" : ""}>
                    {c}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <WalkBar
        walk={walk}
        count={rows.length}
        partName="row"
        caption={cur ? `${cur.label}: ${cur.cells.map((c, j) => `${columns[j]} — ${c}`).join(";  ")}` : "Compare row by row, or hover a column to follow it."}
      />
    </div>
  );
}

function QueryWalk({ lines, autoPlay, onDone }) {
  const walk = useWalk(lines.length, 2600, autoPlay, onDone);
  const [copied, setCopied] = useState(false);
  const cur = walk.i >= 0 ? lines[walk.i] : null;
  async function copy() {
    try {
      await navigator.clipboard.writeText(lines.map((l) => l.code).join("\n"));
      setCopied(true);
      setTimeout(() => setCopied(false), 1400);
    } catch {
      /* clipboard blocked */
    }
  }
  return (
    <div>
      <div className="qw">
        <div className="qw-head">
          <span>Query</span>
          <button className="link" onClick={copy}>
            {copied ? "Copied" : "Copy"}
          </button>
        </div>
        <ol className="qw-lines">
          {lines.map((l, k) => (
            <li key={k} className={walk.i < 0 ? "" : k === walk.i ? "current" : k < walk.i ? "seen" : "later"} onClick={() => walk.go(k)}>
              <span className="qw-n">{k + 1}</span>
              <code>{l.code}</code>
            </li>
          ))}
        </ol>
      </div>
      <WalkBar walk={walk} count={lines.length} partName="line" caption={cur ? `Line ${walk.i + 1}: ${cur.explain}` : "Walk through the query to see what each line does."} />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Charts and verification (spreadsheet data)
// ---------------------------------------------------------------------------

function fmt(v) {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  if (Math.abs(v) >= 1e9) return `${+(v / 1e9).toFixed(2)}B`;
  if (Math.abs(v) >= 1e6) return `${+(v / 1e6).toFixed(2)}M`;
  return (+v.toFixed(2)).toLocaleString("en-US");
}

function Chart({ x, series, log: logDefault, x_label, y_label, autoPlay, onDone }) {
  const box = useRef(null);
  const width = Math.max(420, useWidth(box, 800));
  const [log, setLog] = useState(Boolean(logDefault));
  const [hover, setHover] = useState(null);
  const values = series[0].values;
  const walk = useWalk(values.length, values.length > 16 ? 650 : 1200, autoPlay, onDone);
  const active = walk.i >= 0 ? walk.i : hover;

  const H = 300;
  const m = { l: 64, r: 20, t: 28, b: 44 };
  const w = width - m.l - m.r;
  const h = H - m.t - m.b;
  const nums = values.filter((v) => v !== null && v !== undefined);
  const positives = nums.filter((v) => v > 0);
  const lo = log ? Math.min(...positives) : Math.min(0, ...nums);
  const hi = Math.max(...nums);
  const yOf = (v) => {
    if (v === null || v === undefined) return null;
    if (log) {
      const a = Math.log10(lo);
      const b = Math.log10(hi);
      return m.t + h - ((Math.log10(Math.max(v, lo)) - a) / Math.max(1e-9, b - a)) * h;
    }
    return m.t + h - ((v - lo) / Math.max(1e-9, hi - lo)) * h;
  };
  const xOf = (k) => m.l + (values.length === 1 ? w / 2 : (k * w) / (values.length - 1));
  const pts = values.map((v, k) => ({ x: xOf(k), y: yOf(v), v, k })).filter((p) => p.y !== null);
  const line = pts.map((p, k) => `${k ? "L" : "M"}${p.x},${p.y}`).join(" ");
  const area = pts.length ? `${line} L${pts[pts.length - 1].x},${m.t + h} L${pts[0].x},${m.t + h} Z` : "";
  const ticks = [];
  if (log) {
    const e0 = Math.floor(Math.log10(lo));
    const e1 = Math.ceil(Math.log10(hi));
    const stepE = Math.max(1, Math.ceil((e1 - e0) / 6));
    for (let e = e0; e <= e1; e += stepE) ticks.push(10 ** e);
  } else {
    for (let k = 0; k <= 4; k++) ticks.push(lo + ((hi - lo) * k) / 4);
  }
  const every = Math.ceil(values.length / Math.max(4, Math.floor(w / 46)));
  const a = active !== null && active !== undefined ? pts.find((p) => p.k === active) : null;
  const prev = a && a.k > 0 ? values[a.k - 1] : null;
  const ratio = a && prev ? a.v / prev : null;
  const ratioText = ratio ? (ratio === 0.5 ? "half the previous" : ratio === 2 ? "double the previous" : `${ratio.toFixed(2)}× the previous`) : "";
  const caption =
    a && walk.i >= 0
      ? `${x[a.k]} → ${a.v.toLocaleString("en-US")} ${y_label.toLowerCase()}${ratioText ? ` (${ratioText})` : ""}`
      : `${y_label} for each ${x_label}. Hover the chart, or walk through every value.`;

  return (
    <div ref={box} className="chart">
      <div className="chart-bar">
        <span className="chart-legend">
          <i /> {y_label}
        </span>
        <div className="points-bar" role="group" aria-label="Scale">
          <button className={log ? "seg on" : "seg"} onClick={() => setLog(true)} aria-pressed={log} disabled={!positives.length}>
            Log scale
          </button>
          <button className={!log ? "seg on" : "seg"} onClick={() => setLog(false)} aria-pressed={!log}>
            Linear
          </button>
        </div>
      </div>
      <svg width={width} height={H} className="chart-svg" role="img" aria-label={`${y_label} by ${x_label}`} onMouseLeave={() => setHover(null)}>
        <defs>
          <linearGradient id="chart-area" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" style={{ stopColor: "var(--violet)", stopOpacity: 0.32 }} />
            <stop offset="100%" style={{ stopColor: "var(--violet)", stopOpacity: 0 }} />
          </linearGradient>
        </defs>
        {ticks.map((t, k) => (
          <g key={k} className="chart-grid">
            <line x1={m.l} x2={m.l + w} y1={yOf(t)} y2={yOf(t)} />
            <text x={m.l - 8} y={yOf(t) + 4} textAnchor="end">
              {fmt(t)}
            </text>
          </g>
        ))}
        {x.map((lab, k) =>
          k % every === 0 || k === x.length - 1 ? (
            <text key={k} className="chart-x" x={xOf(k)} y={m.t + h + 18} textAnchor="middle">
              {lab}
            </text>
          ) : null
        )}
        <text className="chart-axis" x={m.l + w / 2} y={H - 4} textAnchor="middle">
          {x_label}
        </text>
        <path className="chart-area" d={area} key={`a${log}`} />
        <path className="chart-line" d={line} pathLength="1" key={`l${log}`} />
        {pts.map((p) => (
          <circle
            key={`${p.k}${log}`}
            className={`chart-dot ${a && a.k === p.k ? "on" : ""}`}
            cx={p.x}
            cy={p.y}
            r={a && a.k === p.k ? 6 : 3.2}
            style={{ "--d": `${0.6 + (p.k / pts.length) * 0.6}s` }}
          />
        ))}
        {a && (
          <g className="chart-tip">
            <line x1={a.x} x2={a.x} y1={m.t} y2={m.t + h} />
            <g transform={`translate(${Math.min(a.x + 10, m.l + w - 160)},${Math.max(m.t, a.y - 54)})`}>
              <rect width="150" height="44" rx="10" />
              <text x="10" y="18" className="tip-x">
                {x[a.k]}
              </text>
              <text x="10" y="35" className="tip-v">
                {fmt(a.v)}
                {ratio ? `  ·  ${ratio === 0.5 ? "÷2" : ratio === 2 ? "×2" : `×${ratio.toFixed(2)}`}` : ""}
              </text>
            </g>
          </g>
        )}
        {values.map((_, k) => (
          <rect key={k} className="chart-hit" x={xOf(k) - w / values.length / 2} y={m.t} width={Math.max(4, w / values.length)} height={h} onMouseEnter={() => setHover(k)} />
        ))}
      </svg>
      <WalkBar walk={walk} count={values.length} caption={caption} partName="value" />
    </div>
  );
}

function Verify({ rows, ok, wrong }) {
  const total = rows.length - 1;
  const pct = total ? ok / total : 0;
  const R = 34;
  const C = 2 * Math.PI * R;
  return (
    <div className="verify">
      <div className="verify-score">
        <svg width="92" height="92" viewBox="0 0 92 92" aria-hidden="true">
          <circle cx="46" cy="46" r={R} className="ring-bg" />
          <circle cx="46" cy="46" r={R} className={`ring ${wrong.length ? "warn" : ""}`} style={{ strokeDasharray: C, "--c": C, strokeDashoffset: C * (1 - pct) }} transform="rotate(-90 46 46)" />
        </svg>
        <div>
          <strong>
            {ok}/{total}
          </strong>
          <span>{wrong.length ? `check ${wrong.join(", ")}` : "every value matches"}</span>
        </div>
      </div>
      <div className="dg-sheet-wrap">
        <table className="dg-sheet verify-table">
          <thead>
            <tr>
              {rows[0].map((c, k) => (
                <th key={k}>{c}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.slice(1).map((r, k) => (
              <tr key={k} style={{ "--d": `${k * 0.035}s` }}>
                {r.map((c, j) => (
                  <td key={j} className={j === r.length - 1 ? (c === "✓" ? "tick" : "cross") : j > 0 ? "num" : "txt"}>
                    {c}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function SheetTable({ name, rows, patterns }) {
  const clean = rows.map((r) => r.map((c) => String(c ?? "").replace(/\s+/g, " ").trim()));
  const width = Math.max(0, ...clean.map((r) => r.length));
  const keepCols = Array.from({ length: width }, (_, j) => clean.some((r) => r[j])).flatMap((k, j) => (k ? [j] : []));
  const grid = clean.map((r) => keepCols.map((j) => r[j] ?? "")).filter((r) => r.some(Boolean));
  const isNum = (c) => c !== "" && !Number.isNaN(Number(c.replace(/,/g, "")));
  const filled = (r) => r.filter(Boolean);
  const headerFirst = grid.length > 1 && filled(grid[0]).length >= 2 && !filled(grid[0]).some(isNum);
  return (
    <div>
      <div className="dg-sheet-wrap">
        <table className="dg-sheet" aria-label={name}>
          <tbody>
            {grid.map((r, i) => {
              const cells = filled(r);
              if (cells.length === 1 && grid.length > 2) {
                return (
                  <tr key={i} className="band">
                    <th colSpan={keepCols.length} scope="colgroup">
                      {cells[0]}
                    </th>
                  </tr>
                );
              }
              return (
                <tr key={i} className={i === 0 && headerFirst ? "head" : ""}>
                  {r.map((c, j) => (
                    <td key={j} className={isNum(c) ? "num" : c ? "txt" : "empty"}>
                      {isNum(c) ? Number(c.replace(/,/g, "")).toLocaleString("en-US") : c}
                    </td>
                  ))}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {patterns?.length > 0 && (
        <div className="dg-patterns">
          <p className="dg-patterns-head">Patterns calculated from your data</p>
          <ul>
            {patterns.map((p, i) => (
              <li key={i}>{p}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// IPv4: bits explainer and Subnet Lab (all exact arithmetic)
// ---------------------------------------------------------------------------

const BITVAL = [128, 64, 32, 16, 8, 4, 2, 1];
const maskOf = (n) => (n === 0 ? 0 : (0xffffffff << (32 - n)) >>> 0);
const toIp = (v) => [24, 16, 8, 0].map((s) => (v >>> s) & 255).join(".");
function parseIp(s) {
  const p = String(s).trim().split(".");
  if (p.length !== 4 || p.some((x) => !/^\d{1,3}$/.test(x) || Number(x) > 255)) return null;
  return p.reduce((v, x) => ((v << 8) | Number(x)) >>> 0, 0);
}
const bitsOf = (v) => Array.from({ length: 32 }, (_, k) => (v >>> (31 - k)) & 1);

/** 32 bit cells in 4 octets, coloured network (first n) / host. */
function BitRow({ bits, n, label, reveal = 32, kind = "" }) {
  return (
    <div className={`bitrow ${kind}`}>
      <span className="bitrow-label">{label}</span>
      <div className="bitrow-octets">
        {[0, 1, 2, 3].map((o) => (
          <div key={o} className="bitrow-octet">
            {bits.slice(o * 8, o * 8 + 8).map((b, k) => {
              const idx = o * 8 + k;
              return (
                <span key={k} className={`bit ${idx < n ? "net" : "host"} ${idx < reveal ? "" : "hidden"} ${idx === reveal - 1 && reveal < 32 ? "just" : ""}`}>
                  {idx < reveal ? b : ""}
                </span>
              );
            })}
          </div>
        ))}
      </div>
    </div>
  );
}

function BitsExplainer({ autoPlay, onDone }) {
  const [n, setN] = useState(24);
  const [playing, setPlaying] = useState(false);
  const doneRef = useRef(onDone);
  doneRef.current = onDone;
  useEffect(() => {
    if (autoPlay) {
      setN(0);
      setPlaying(true);
    }
  }, [autoPlay]);
  useEffect(() => {
    if (!playing) return undefined;
    if (n >= 24) {
      setPlaying(false);
      const t = setTimeout(() => doneRef.current?.(), 1500);
      return () => clearTimeout(t);
    }
    const t = setTimeout(() => setN((x) => x + 1), reduceMotion() ? 0 : 140);
    return () => clearTimeout(t);
  }, [playing, n]);
  const mask = bitsOf(maskOf(n));
  const octets = [0, 1, 2, 3].map((o) => {
    const on = mask
      .slice(o * 8, o * 8 + 8)
      .map((b, k) => (b ? BITVAL[k] : 0))
      .filter(Boolean);
    const value = on.reduce((x, y) => x + y, 0);
    return { value, expr: on.length === 0 ? "no bits" : on.length === 8 ? "all 8 bits" : on.join(" + ") };
  });
  const total = 2 ** (32 - n);
  return (
    <div className="lab">
      <div className="lab-controls">
        <button
          className="walk-play"
          onClick={() => {
            if (playing) setPlaying(false);
            else {
              setN(0);
              setPlaying(true);
            }
          }}
        >
          <span className={`walk-icon ${playing ? "pause" : "play"}`} aria-hidden="true" /> {playing ? "Pause" : "Play: build a /24 mask"}
        </button>
        <label className="lab-slider">
          <span>Prefix</span>
          <input
            type="range"
            min="0"
            max="32"
            value={n}
            onChange={(e) => {
              setPlaying(false);
              setN(Number(e.target.value));
            }}
          />
          <strong>/{n}</strong>
        </label>
      </div>
      <div className="bitrow values" aria-hidden="true">
        <span className="bitrow-label">Bit value</span>
        <div className="bitrow-octets">
          {[0, 1, 2, 3].map((o) => (
            <div key={o} className="bitrow-octet">
              {BITVAL.map((v) => (
                <span key={v} className="bitval">
                  {v}
                </span>
              ))}
            </div>
          ))}
        </div>
      </div>
      <BitRow bits={mask} n={n} label="Mask" />
      <div className="bitrow sums">
        <span className="bitrow-label">Octet</span>
        <div className="bitrow-octets">
          {octets.map((o, k) => (
            <div key={k} className={`octet-sum ${o.value ? "on" : ""}`}>
              <strong>{o.value}</strong>
              <span>{o.expr}</span>
            </div>
          ))}
        </div>
      </div>
      <p className="lab-sentence" aria-live="polite">
        <strong>/{n}</strong> = {n} network bit{n === 1 ? "" : "s"} + {32 - n} host bit{32 - n === 1 ? "" : "s"} → mask <strong>{octets.map((o) => o.value).join(".")}</strong> → 2
        <sup>{32 - n}</sup> = <strong>{total.toLocaleString("en-US")}</strong> addresses
        {n <= 30 ? `, ${(total - 2).toLocaleString("en-US")} usable` : n === 31 ? " (point-to-point link: both usable)" : " (a single host)"}.
      </p>
    </div>
  );
}

function LabInputs({ ipText, setIpText, n, setN, onAnd, animating }) {
  return (
    <div className="lab-controls">
      <label className="lab-ip">
        <span>IP address</span>
        <input value={ipText} onChange={(e) => setIpText(e.target.value)} spellCheck={false} aria-label="IP address" />
      </label>
      <label className="lab-slider">
        <span>Prefix</span>
        <input type="range" min="0" max="32" value={n} onChange={(e) => setN(Number(e.target.value))} />
        <strong>/{n}</strong>
      </label>
      <button className="walk-play" onClick={onAnd} disabled={animating}>
        <span className="walk-icon play" aria-hidden="true" /> Show the AND
      </button>
    </div>
  );
}

function SubnetLab({ hosts = {}, autoPlay, onDone }) {
  const [ipText, setIpText] = useState("192.168.10.77");
  const [n, setN] = useState(26);
  const [reveal, setReveal] = useState(32);
  const doneRef = useRef(onDone);
  doneRef.current = onDone;
  const ip = parseIp(ipText);
  const animating = reveal < 32;

  function showAnd() {
    setReveal(reduceMotion() ? 32 : 0);
  }
  useEffect(() => {
    if (autoPlay) setReveal(0);
  }, [autoPlay]);
  useEffect(() => {
    if (reveal >= 32) return undefined;
    const t = setTimeout(() => {
      if (reveal === 31) setTimeout(() => doneRef.current?.(), 1800);
      setReveal((r) => r + 1);
    }, 85);
    return () => clearTimeout(t);
  }, [reveal]);

  if (ip === null) {
    return (
      <div className="lab">
        <LabInputs ipText={ipText} setIpText={setIpText} n={n} setN={setN} onAnd={showAnd} animating={animating} />
        <p className="notice error">Type an IPv4 address like 10.1.2.3 (four numbers 0–255).</p>
      </div>
    );
  }
  const mask = maskOf(n);
  const net = (ip & mask) >>> 0;
  const bcast = (net | (~mask >>> 0)) >>> 0;
  const total = 2 ** (32 - n);
  const usable = n === 32 ? 1 : n === 31 ? 2 : total - 2;
  const first = n >= 31 ? net : net + 1;
  const last = n >= 31 ? bcast : bcast - 1;
  const parent = n <= 8 ? 0 : n <= 16 ? 8 : n <= 24 ? 16 : 24;
  const blocks = 2 ** (n - parent);
  const parentNet = (ip & maskOf(parent)) >>> 0;
  const index = Math.floor((net - parentNet) / total);
  const a = ip >>> 24;
  const b = (ip >>> 16) & 255;
  const kind =
    a === 10 || (a === 172 && b >= 16 && b <= 31) || (a === 192 && b === 168)
      ? "Private address (RFC 1918) — used inside organisations, not routed on the internet."
      : a === 127
        ? "Loopback — the machine itself."
        : a === 169 && b === 254
          ? "Link-local (APIPA) — assigned when DHCP fails."
          : "Public address range.";
  const sheet = hosts[String(n)];
  const results = [
    ["Network", `${toIp(net)}/${n}`, "violet"],
    ["Broadcast", n >= 31 ? "none" : toIp(bcast), "coral"],
    ["Usable range", n === 32 ? toIp(net) : `${toIp(first)} – ${toIp(last)}`, "teal"],
    ["Usable hosts", usable.toLocaleString("en-US"), "teal"],
    ["Subnet mask", toIp(mask), "mustard"],
    ["Wildcard", toIp(~mask >>> 0), "mustard"],
  ];

  return (
    <div className="lab">
      <LabInputs ipText={ipText} setIpText={setIpText} n={n} setN={setN} onAnd={showAnd} animating={animating} />
      <div className="lab-bits">
        <BitRow bits={bitsOf(ip)} n={n} label="Address" />
        <BitRow bits={bitsOf(mask)} n={n} label="Mask" kind="mask" />
        <BitRow bits={bitsOf(net)} n={n} label="AND = network" kind="result" reveal={reveal} />
      </div>
      <p className="small muted lab-and">
        Network = address AND mask: a bit stays 1 only where both are 1, so every host bit (right of /{n}) becomes 0.
      </p>
      <div className="lab-results">
        {results.map(([k, v, tone], i) => (
          <div key={k} className={`lab-card tone-${tone}`} style={{ "--d": `${i * 0.05}s` }}>
            <span>{k}</span>
            <strong>{v}</strong>
          </div>
        ))}
      </div>
      {sheet !== undefined && (
        <p className="lab-sheet">
          Your sheet: /{n} → <strong>{Number(sheet).toLocaleString("en-US")}</strong> addresses{" "}
          {Number(sheet) === total ? "✓ matches 2^(32 − n)" : `✗ calculation says ${total.toLocaleString("en-US")}`}
        </p>
      )}
      <div className="lab-range">
        <p className="small">
          {blocks > 1
            ? `The /${parent} ${toIp(parentNet)} holds ${blocks.toLocaleString("en-US")} networks of size /${n}. Yours is number ${index + 1}:`
            : `/${n} lines up with an octet boundary — it is one whole block:`}
        </p>
        {blocks <= 64 ? (
          <div className="range-bar" style={{ "--n": blocks }}>
            {Array.from({ length: blocks }, (_, k) => (
              <span key={k} className={k === index ? "on" : ""} title={`${toIp(parentNet + k * total)}/${n}`}>
                {blocks <= 16 ? toIp(parentNet + k * total).split(".").slice(parent / 8).join(".") : ""}
              </span>
            ))}
          </div>
        ) : (
          <p className="small muted">({blocks.toLocaleString("en-US")} blocks — too many to draw.)</p>
        )}
      </div>
      <p className="small muted">{kind}</p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Picker
// ---------------------------------------------------------------------------

/** Draw a lesson visual. autoPlay starts its walk-through; onDone fires at the end. */
export default function Visual({ spec, autoPlay = false, onDone }) {
  if (!spec) return null;
  const p = { autoPlay, onDone };
  switch (spec.type) {
    case "flow":
      return <Graph nodes={spec.nodes} edges={spec.edges} direction={spec.nodes.length > 5 ? "DOWN" : "RIGHT"} {...p} />;
    case "tree": {
      const g = treeToGraph(spec);
      return <Graph nodes={g.nodes} edges={g.edges} direction="DOWN" {...p} />;
    }
    case "chain":
      return <Timeline stages={spec.stages} {...p} />;
    case "stack":
      return <Layers layers={spec.layers} {...p} />;
    case "cards":
      return <FlipCards items={spec.items} {...p} />;
    case "compare":
      return <Compare columns={spec.columns} rows={spec.rows} {...p} />;
    case "query":
      return <QueryWalk lines={spec.lines} {...p} />;
    case "chart":
      return <Chart x={spec.x} series={spec.series} log={spec.log} x_label={spec.x_label} y_label={spec.y_label} {...p} />;
    case "verify":
      return <Verify rows={spec.rows} ok={spec.ok} wrong={spec.wrong} />;
    case "bits":
      return <BitsExplainer {...p} />;
    case "subnetlab":
    case "ipcalc": // lessons made before v0.8
      return <SubnetLab hosts={spec.hosts} {...p} />;
    case "table":
      return <SheetTable name={spec.name} rows={spec.rows} patterns={spec.patterns} />;
    default:
      return null;
  }
}

/** Visual kinds that run a walk-through and call onDone (Lesson autoplay). */
export const WALKABLE = new Set(["flow", "tree", "chain", "stack", "cards", "compare", "query", "chart", "bits", "subnetlab", "ipcalc"]);
