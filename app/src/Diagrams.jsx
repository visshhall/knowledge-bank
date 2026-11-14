/**
 * Diagrams.jsx — draws every lesson visual, cleanly, from data.
 *
 * WHAT:  One <Visual spec={...} /> that picks the right drawing for each
 *        kind on the lesson menu (engine/kb_engine/lessons.py):
 *          flow    → boxes + arrows, laid out automatically by ELK
 *          tree    → hierarchy, laid out automatically by ELK (top-down)
 *          chain   → numbered stages left→right with arrows (wraps)
 *          stack   → layers top→bottom, each a coloured band
 *          cards   → key terms/techniques as a grid of cards
 *          compare → side-by-side comparison grid
 *          query   → a query walked through line by line
 *          table   → the REAL spreadsheet grid + calculated patterns
 *          ipcalc  → interactive 32-bit / CIDR / mask / hosts calculator
 * WHY:   The owner asked for "proper diagrams, not random". The AI only
 *        supplies words and connections; positions, sizes, spacing and
 *        arrow routing are computed here, so diagrams are always aligned
 *        and never overlap. ELK ("Eclipse Layout Kernel") is a well-known
 *        professional graph layout engine; it runs inside the app, offline.
 *        Parts appear one after another (a "teacher drawing on the board"
 *        effect); Windows' "reduce animations" setting shows them at once.
 * WHEN:  Rendered by Lesson.jsx for each lesson step.
 * CONNECTED TO: Lesson.jsx (caller), styles.css (.dg-*), elkjs (layout).
 *        Standalone otherwise — no engine calls.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import ELK from "elkjs/lib/elk.bundled.js";

const elk = new ELK();
const TONES = ["teal", "coral", "violet", "mustard"];

/** Split a label into ≤2 lines of ≤22 characters (box text never overflows). */
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

/** Box size for a label: width from the longest line, height from line count. */
function boxSize(label) {
  const lines = wrap(label);
  const width = Math.max(110, Math.min(220, Math.max(...lines.map((l) => l.length)) * 8 + 32));
  return { width, height: lines.length === 1 ? 46 : 64, lines };
}

/**
 * Lay out a graph with ELK and draw it as SVG.
 * nodes: [{id, label}], edges: [{from, to, label?}], direction: "RIGHT"|"DOWN"
 *
 * Fitting the space: a left-to-right flow that is wider than the lesson
 * card is first scaled down a little (never below 75%, so text stays
 * readable); if even that is too wide it is laid out again top-to-bottom;
 * anything still too wide scrolls sideways. Nothing is ever cut off.
 */
function Graph({ nodes, edges, direction }) {
  const [layout, setLayout] = useState(null);
  const [dir, setDir] = useState(direction);
  const [room, setRoom] = useState(0);
  const box = useRef(null);
  const key = JSON.stringify({ nodes, edges, dir });

  // Track the width available to the diagram (changes with window size).
  useEffect(() => {
    const el = box.current;
    if (!el) return undefined;
    const ro = new ResizeObserver(([e]) => setRoom(e.contentRect.width));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // A new diagram starts from the direction it asked for.
  const shape = JSON.stringify({ nodes, edges });
  useEffect(() => setDir(direction), [direction, shape]);

  useEffect(() => {
    let alive = true;
    const graph = {
      id: "root",
      layoutOptions: {
        "elk.algorithm": "layered",
        "elk.direction": dir,
        "elk.edgeRouting": "ORTHOGONAL",
        "elk.layered.spacing.nodeNodeBetweenLayers": "56",
        "elk.spacing.nodeNode": "28",
        "elk.spacing.edgeLabel": "6",
        "elk.layered.nodePlacement.strategy": "BRANDES_KOEPF",
      },
      children: nodes.map((n) => {
        const s = boxSize(n.label);
        return { id: n.id, width: s.width, height: s.height };
      }),
      edges: edges.map((e, i) => ({
        id: `e${i}`,
        sources: [e.from],
        targets: [e.to],
        labels: e.label ? [{ text: e.label, width: e.label.length * 6.5 + 8, height: 16 }] : [],
      })),
    };
    elk.layout(graph).then((g) => alive && setLayout(g)).catch(() => alive && setLayout("error"));
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  // Too wide sideways even at 75%? Re-lay it out top-to-bottom.
  useEffect(() => {
    if (layout && layout !== "error" && room && dir === "RIGHT" && (layout.width + 32) * 0.75 > room) setDir("DOWN");
  }, [layout, room, dir]);

  return <div ref={box} className="dg-graph-box">{renderGraph(layout, nodes, room)}</div>;
}

function renderGraph(layout, nodes, room) {
  if (layout === "error") return <CardsFallback items={nodes.map((n) => ({ label: n.label }))} />;
  if (!layout) return <div className="dg-loading">Drawing…</div>;

  const byId = Object.fromEntries(nodes.map((n, i) => [n.id, { ...n, i }]));
  const pad = 16;
  const natural = layout.width + pad * 2;
  const fitW = room && natural > room ? Math.max(room, natural * 0.75) : natural;
  return (
    <svg
      className="dg-graph"
      viewBox={`${-pad} ${-pad} ${layout.width + pad * 2} ${layout.height + pad * 2}`}
      // Natural size, or scaled down at most to 75% to fit (see Graph).
      width={fitW}
      height={(fitW * (layout.height + pad * 2)) / (layout.width + pad * 2)}
      role="img"
      aria-label={nodes.map((n) => n.label).join(", ")}
    >
      <defs>
        <marker id="dg-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M0,0 L10,5 L0,10 z" className="dg-arrowhead" />
        </marker>
      </defs>
      {layout.edges.map((e, i) =>
        (e.sections || []).map((s, j) => {
          const pts = [s.startPoint, ...(s.bendPoints || []), s.endPoint];
          return (
            <g key={`${i}-${j}`} className="dg-appear" style={{ animationDelay: `${0.25 + i * 0.12}s` }}>
              <polyline className="dg-edge" points={pts.map((p) => `${p.x},${p.y}`).join(" ")} markerEnd="url(#dg-arrow)" />
              {(e.labels || []).map((l, k) => (
                <text key={k} className="dg-edge-label" x={l.x + l.width / 2} y={l.y + 12} textAnchor="middle">
                  {l.text}
                </text>
              ))}
            </g>
          );
        })
      )}
      {layout.children.map((c) => {
        const n = byId[c.id];
        const { lines } = boxSize(n.label);
        return (
          <g key={c.id} className={`dg-node tone-${TONES[n.i % TONES.length]} dg-appear`} style={{ animationDelay: `${n.i * 0.12}s` }}>
            <rect x={c.x} y={c.y} width={c.width} height={c.height} rx="12" />
            {lines.map((line, k) => (
              <text
                key={k}
                x={c.x + c.width / 2}
                y={c.y + c.height / 2 + (k - (lines.length - 1) / 2) * 17 + 5}
                textAnchor="middle"
              >
                {line}
              </text>
            ))}
          </g>
        );
      })}
    </svg>
  );
}

/** Tree spec → nodes/edges for the top-down Graph. */
function treeToGraph(spec) {
  const nodes = [{ id: "n0", label: spec.root }];
  const edges = [];
  let next = 1;
  const walk = (children, parent) => {
    for (const c of children || []) {
      const id = `n${next++}`;
      nodes.push({ id, label: c.label });
      edges.push({ from: parent, to: id });
      walk(c.children, id);
    }
  };
  walk(spec.children, "n0");
  return { nodes, edges };
}

function Chain({ stages }) {
  return (
    <ol className="dg-chain">
      {stages.map((s, i) => (
        <li key={i} className={`dg-appear tone-${TONES[i % TONES.length]}`} style={{ animationDelay: `${i * 0.15}s` }}>
          <span className="dg-chain-num">{i + 1}</span>
          <span className="dg-chain-label">{s.label}</span>
          {s.detail && <span className="dg-chain-detail">{s.detail}</span>}
        </li>
      ))}
    </ol>
  );
}

function Stack({ layers }) {
  return (
    <ol className="dg-stack">
      {layers.map((l, i) => (
        <li key={i} className={`dg-appear tone-${TONES[i % TONES.length]}`} style={{ animationDelay: `${i * 0.12}s` }}>
          <span className="dg-stack-label">{l.label}</span>
          {l.detail && <span className="dg-stack-detail">{l.detail}</span>}
        </li>
      ))}
    </ol>
  );
}

function CardsFallback({ items }) {
  return (
    <ul className="dg-cards">
      {items.map((it, i) => (
        <li key={i} className={`dg-appear tone-${TONES[i % TONES.length]}`} style={{ animationDelay: `${i * 0.1}s` }}>
          <span className="dg-card-label">{it.label}</span>
          {it.detail && <span className="dg-card-detail">{it.detail}</span>}
        </li>
      ))}
    </ul>
  );
}

function Compare({ columns, rows }) {
  return (
    <div className="dg-compare-wrap">
      <table className="dg-compare">
        <thead>
          <tr>
            <th />
            {columns.map((c, i) => (
              <th key={i} className={`tone-${TONES[i % TONES.length]}`}>{c}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="dg-appear" style={{ animationDelay: `${i * 0.1}s` }}>
              <th scope="row">{r.label}</th>
              {r.cells.map((c, j) => (
                <td key={j}>{c}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Query({ lines }) {
  return (
    <ol className="dg-query">
      {lines.map((l, i) => (
        <li key={i} className="dg-appear" style={{ animationDelay: `${i * 0.15}s` }}>
          <code>{l.code}</code>
          <span className="dg-query-explain">
            <span className="dg-query-num">{i + 1}</span>
            {l.explain}
          </span>
        </li>
      ))}
    </ol>
  );
}

/**
 * The real spreadsheet grid, tidied for reading (values never change):
 *  - fully empty rows and columns are dropped (layout gaps in the sheet);
 *  - a row with a single filled cell (a title or section name such as
 *    "Subnet 255.255.x.0") becomes a heading band across the whole table;
 *  - the first row is styled as a header only when it really is one
 *    (two or more filled, non-numeric cells);
 *  - numbers are right-aligned with thousands separators.
 */
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
                    <th colSpan={keepCols.length} scope="colgroup">{cells[0]}</th>
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

/** Interactive 32-bit / CIDR calculator. Everything is computed, nothing typed by AI. */
function IpCalc() {
  const [cidr, setCidr] = useState(24);
  const octets = useMemo(
    () =>
      [0, 1, 2, 3].map((o) => {
        const bits = Array.from({ length: 8 }, (_, b) => o * 8 + b < cidr);
        return { bits, value: bits.reduce((v, on, b) => v + (on ? 128 >> b : 0), 0) };
      }),
    [cidr]
  );
  const total = 2 ** (32 - cidr);
  return (
    <div className="dg-ip">
      <label className="dg-ip-slider">
        <span>CIDR</span>
        <input type="range" min="1" max="32" step="1" value={cidr} onChange={(e) => setCidr(Number(e.target.value))} />
        <strong>/{cidr}</strong>
      </label>
      <div className="dg-ip-octets">
        {octets.map((o, i) => (
          <div key={i} className="dg-ip-octet">
            <div className="dg-ip-bits">
              {o.bits.map((on, b) => (
                <span key={b} className={on ? "bit net" : "bit host"} title={`worth ${128 >> b}`}>
                  {on ? 1 : 0}
                </span>
              ))}
            </div>
            <span className="dg-ip-value">{o.value}</span>
          </div>
        ))}
      </div>
      <p className="dg-ip-legend">
        <span className="bit net">1</span> network part <span className="bit host">0</span> host part · bit values 128 64 32 16 8 4 2 1
      </p>
      <div className="dg-ip-results">
        <div className="tone-violet">
          <span>Subnet mask</span>
          <strong>{octets.map((o) => o.value).join(".")}</strong>
        </div>
        <div className="tone-coral">
          <span>Addresses (2^{32 - cidr})</span>
          <strong>{total.toLocaleString("en-US")}</strong>
        </div>
        <div className="tone-teal">
          <span>Usable hosts (−2)</span>
          <strong>{cidr >= 31 ? "special case" : (total - 2).toLocaleString("en-US")}</strong>
        </div>
      </div>
    </div>
  );
}

/** Pick the drawing for a lesson visual spec. Unknown kinds render nothing. */
export default function Visual({ spec }) {
  if (!spec) return null;
  switch (spec.type) {
    case "flow":
      return <Graph nodes={spec.nodes} edges={spec.edges} direction={spec.nodes.length > 5 ? "DOWN" : "RIGHT"} />;
    case "tree": {
      const g = treeToGraph(spec);
      return <Graph nodes={g.nodes} edges={g.edges} direction="DOWN" />;
    }
    case "chain":
      return <Chain stages={spec.stages} />;
    case "stack":
      return <Stack layers={spec.layers} />;
    case "cards":
      return <CardsFallback items={spec.items} />;
    case "compare":
      return <Compare columns={spec.columns} rows={spec.rows} />;
    case "query":
      return <Query lines={spec.lines} />;
    case "table":
      return <SheetTable name={spec.name} rows={spec.rows} patterns={spec.patterns} />;
    case "ipcalc":
      return <IpCalc />;
    default:
      return null;
  }
}
