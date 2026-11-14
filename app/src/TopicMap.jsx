/**
 * TopicMap.jsx — Phase 4 Knowledge Map: your topics as a living network.
 *
 * WHAT:  Each topic is a circle (size = how many passages it holds; colour
 *        cycles through the four accents; a ring marks topics with a
 *        written article, a dot marks a ready lesson). Lines join related
 *        topics (topic_links from Build topics; thicker = more alike).
 *        - On opening, topics drift out from the centre and settle into
 *          groups: related subjects end up near each other (d3-force
 *          physics: links pull, circles push apart, nothing overlaps).
 *        - Hover a topic: it and its neighbours stay bright, the rest fade,
 *          and a note names the related topics.
 *        - Drag a topic to rearrange; click to open it.
 *        - Keyboard: Tab to a topic, Enter to open it.
 *        - "Reduce animations" in Windows: the layout is computed first and
 *          shown already settled.
 * WHY:   Phase 4 asked for an animated Knowledge Map so the owner can see the
 *        shape of everything he has read and jump between related subjects.
 * WHEN:  Topics screen → "Map" view.
 * CONNECTED TO: bridge.js → GET /topics/map (server.py → distill.topic_map);
 *        d3-force (layout); Topics.jsx (onOpen); styles.css (.tmap-*).
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { forceCenter, forceCollide, forceLink, forceManyBody, forceSimulation, forceX, forceY } from "d3-force";
import { kb } from "./bridge.js";

const TONES = ["teal", "coral", "violet", "mustard"];
const H = 560;

function shorten(s, n) {
  return s.length > n ? `${s.slice(0, n - 1)}…` : s;
}

export default function TopicMap({ onOpen }) {
  const [data, setData] = useState(null);
  const [width, setWidth] = useState(900);
  const [, setTick] = useState(0);
  const [hover, setHover] = useState(null);
  const box = useRef(null);
  const sim = useRef(null);
  const drag = useRef(null);

  useEffect(() => {
    kb.get("/topics/map").then((r) => !r.error && setData(r));
  }, []);

  useEffect(() => {
    const el = box.current;
    if (!el) return undefined;
    const ro = new ResizeObserver(([e]) => setWidth(Math.max(480, Math.floor(e.contentRect.width))));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // Build nodes/links once per data load (positions live in these objects).
  const graph = useMemo(() => {
    if (!data) return null;
    const max = Math.max(1, ...data.nodes.map((n) => n.passages));
    const nodes = data.nodes.map((n, i) => ({
      ...n,
      i,
      r: 14 + 30 * Math.sqrt(n.passages / max),
      x: (Math.random() - 0.5) * 40,
      y: (Math.random() - 0.5) * 40,
    }));
    const byId = new Map(nodes.map((n) => [n.id, n]));
    const links = data.links
      .filter((l) => byId.has(l.source) && byId.has(l.target))
      .map((l) => ({ ...l }));
    const neighbours = new Map(nodes.map((n) => [n.id, new Set()]));
    for (const l of links) {
      neighbours.get(l.source).add(l.target);
      neighbours.get(l.target).add(l.source);
    }
    return { nodes, links, neighbours };
  }, [data]);

  // Physics: links pull related topics together, bodies push apart.
  useEffect(() => {
    if (!graph) return undefined;
    const s = forceSimulation(graph.nodes)
      .force("link", forceLink(graph.links).id((d) => d.id).distance((l) => 140 - 80 * l.weight).strength(0.6))
      .force("charge", forceManyBody().strength(-420))
      .force("collide", forceCollide().radius((d) => d.r + 34).strength(0.9)) // room for the label below
      .force("x", forceX(0).strength(0.05))
      .force("y", forceY(0).strength(0.08))
      .force("center", forceCenter(0, 0));
    const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    if (reduce) {
      s.stop();
      for (let i = 0; i < 300; i++) s.tick();
      setTick((t) => t + 1);
    } else {
      s.alphaDecay(0.035).on("tick", () => setTick((t) => t + 1));
    }
    sim.current = s;
    return () => s.stop();
  }, [graph]);

  if (!data) return <div ref={box} className="tmap-box muted">Drawing the map…</div>;
  if (!data.nodes.length) {
    return (
      <div ref={box} className="tmap-box muted">
        Build topics first — they'll appear here as a network.
      </div>
    );
  }

  const { nodes, links, neighbours } = graph;
  // Keep everything inside the frame (map coordinates are centred on 0,0).
  const halfW = width / 2 - 10;
  const halfH = H / 2 - 10;
  for (const n of nodes) {
    n.x = Math.max(-halfW + n.r, Math.min(halfW - n.r, n.x));
    n.y = Math.max(-halfH + n.r, Math.min(halfH - n.r, n.y));
  }
  const near = hover ? neighbours.get(hover) : null;
  const on = (id) => !hover || id === hover || near.has(id);
  const hovered = hover ? nodes.find((n) => n.id === hover) : null;

  // Dragging: pin the node to the pointer, warm the physics up a little.
  function toMap(e) {
    const rect = box.current.querySelector("svg").getBoundingClientRect();
    return { x: e.clientX - rect.left - width / 2, y: e.clientY - rect.top - H / 2 };
  }
  function down(e, n) {
    e.preventDefault();
    drag.current = { n, moved: false };
    sim.current?.alphaTarget(0.2).restart();
    e.currentTarget.setPointerCapture?.(e.pointerId);
  }
  function move(e) {
    const d = drag.current;
    if (!d) return;
    const p = toMap(e);
    d.n.fx = p.x;
    d.n.fy = p.y;
    d.moved = true;
  }
  function up() {
    const d = drag.current;
    drag.current = null;
    if (!d) return;
    sim.current?.alphaTarget(0);
    d.n.fx = null;
    d.n.fy = null;
    if (!d.moved) onOpen?.(d.n.id);
  }

  return (
    <div ref={box} className="tmap-box">
      <p className="tmap-note" aria-live="polite">
        {hovered
          ? near.size
            ? `${hovered.title} — related: ${[...near].map((id) => nodes.find((n) => n.id === id).title).join(", ")}.`
            : `${hovered.title} — no closely related topics.`
          : "Related topics sit close together and are joined by lines. Drag to rearrange, click a topic to open it."}
      </p>
      <svg
        className="tmap-svg"
        viewBox={`${-width / 2} ${-H / 2} ${width} ${H}`}
        width="100%"
        height={H}
        onPointerMove={move}
        onPointerUp={up}
        role="img"
        aria-label={`Map of ${nodes.length} topics`}
      >
        {links.filter((l) => typeof l.source === "object").map((l, i) => (
          <line
            key={i}
            className={`tmap-link ${on(l.source.id) && on(l.target.id) ? (hover ? "lit" : "") : "dim"}`}
            x1={l.source.x}
            y1={l.source.y}
            x2={l.target.x}
            y2={l.target.y}
            strokeWidth={1 + 4 * l.weight}
          />
        ))}
        {nodes.map((n) => (
          <g
            key={n.id}
            className={`tmap-node tone-${TONES[n.i % TONES.length]} ${on(n.id) ? "" : "dim"} ${hover === n.id ? "hot" : ""}`}
            transform={`translate(${n.x},${n.y})`}
            onPointerEnter={() => setHover(n.id)}
            onPointerLeave={() => !drag.current && setHover(null)}
            onPointerDown={(e) => down(e, n)}
            tabIndex={0}
            role="button"
            aria-label={`Open topic ${n.title}, ${n.passages} passages`}
            onFocus={() => setHover(n.id)}
            onBlur={() => setHover(null)}
            onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && onOpen?.(n.id)}
          >
            {n.status === "written" && <circle className="tmap-ring" r={n.r + 5} />}
            <circle className="tmap-dot" r={n.r} />
            {Boolean(n.has_lesson) && <circle className="tmap-lesson" r="4" cx={n.r * 0.7} cy={-n.r * 0.7} />}
            {(n.r > 24 || hover === n.id || (near && near.has(n.id))) && (
              <text y={n.r + 16} textAnchor="middle">
                {shorten(n.title, 28)}
              </text>
            )}
          </g>
        ))}
      </svg>
      <ul className="tmap-legend">
        <li><span className="lg-ring" /> article written</li>
        <li><span className="lg-dot" /> lesson ready</li>
        <li>circle size = passages · line width = how closely related</li>
      </ul>
    </div>
  );
}
