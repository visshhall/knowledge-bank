/**
 * FlowMap.jsx — the Overview's interactive map of the bank: files → topics.
 *
 * WHAT:  A flow diagram (a "Sankey"): every file is a bar on the left,
 *        every topic a bar on the right, and a ribbon joins a file to each
 *        topic it feeds. Bar height = how many passages; ribbon width = how
 *        many passages from that file ended up in that topic.
 *        - Hover a file, topic or ribbon: its connections light up, the
 *          rest fade, and a note says exactly what flows where.
 *        - Click a topic (bar or name) to open it.
 *        - On first show the ribbons sweep in left to right, then a gentle
 *          stream of dots runs along them, showing knowledge flowing from
 *          your files into topics. "Reduce animations" in Windows turns all
 *          motion off.
 *        - Before topics exist, the files are shown with a dashed column
 *          saying where topics will appear.
 *        - Big libraries stay readable: past 24 files or 24 topics the
 *          smallest are combined into one "N more files/topics" bar.
 * WHY:   Replaces the v0.4 schematic (equal boxes and circles), which the
 *        owner found unpolished and which showed counts, not relationships.
 *        This shows real structure: which documents matter for which
 *        subjects. It is also the first piece of the Phase 4 Knowledge Map.
 * WHEN:  Rendered by Overview.jsx; data from GET /overview/flow, refreshed
 *        when the totals change.
 * CONNECTED TO: bridge.js (kb.get), server.py → distill.flow(); styles.css
 *        (.flow-*); Overview.jsx passes onOpenTopic(id) → App → Topics.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { formatCount, kb } from "./bridge.js";

const TONES = ["teal", "coral", "violet", "mustard"];
const MAX_NODES = 24;
const plural = (n, word) => `${formatCount(n)} ${word}${n === 1 ? "" : "s"}`;

/** Keep the biggest `max` items; fold the rest into one "N more" item. */
function cap(items, max, label, idKey = "id") {
  if (items.length <= max) return items;
  const sorted = [...items].sort((a, b) => b.passages - a.passages);
  const keep = sorted.slice(0, max - 1);
  const rest = sorted.slice(max - 1);
  return [
    ...keep,
    {
      [idKey]: "other",
      members: new Set(rest.map((r) => r.id)),
      name: `${rest.length} more ${label}`,
      title: `${rest.length} more ${label}`,
      passages: rest.reduce((n, r) => n + r.passages, 0),
      other: true,
    },
  ];
}

/** Stack nodes vertically: heights proportional to passages, fixed gaps. */
function stack(nodes, height, gap) {
  const total = nodes.reduce((n, x) => n + x.passages, 0) || 1;
  const usable = Math.max(40, height - gap * (nodes.length - 1));
  let y = 0;
  return nodes.map((n) => {
    const h = Math.max(4, (n.passages / total) * usable);
    const out = { ...n, y0: y, y1: y + h };
    y += h + gap;
    return out;
  });
}

function shorten(text, n) {
  const s = String(text);
  return s.length > n ? `${s.slice(0, n - 1)}…` : s;
}

export default function FlowMap({ version, onOpenTopic }) {
  const [data, setData] = useState(null);
  const [width, setWidth] = useState(900);
  const [hover, setHover] = useState(null); // {kind: "file"|"topic"|"link", id}
  const box = useRef(null);

  // Load (and reload whenever the bank's totals change).
  useEffect(() => {
    let alive = true;
    kb.get("/overview/flow").then((r) => alive && !r.error && setData(r));
    return () => {
      alive = false;
    };
  }, [version]);

  // Follow the card's width so the map always fits the window.
  useEffect(() => {
    const el = box.current;
    if (!el) return undefined;
    const ro = new ResizeObserver(([e]) => setWidth(Math.max(560, Math.floor(e.contentRect.width))));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const layout = useMemo(() => {
    if (!data) return null;
    const files = cap(data.files, MAX_NODES, "files");
    const topics = cap(data.topics, MAX_NODES, "topics");
    const fileOf = (id) => files.find((f) => f.id === id || (f.other && f.members.has(id)));
    const topicOf = (id) => topics.find((t) => t.id === id || (t.other && t.members.has(id)));
    // Merge links into the (possibly folded) nodes.
    const merged = new Map();
    for (const l of data.links) {
      const f = fileOf(l.file);
      const t = topicOf(l.topic);
      if (!f || !t) continue;
      const k = `${f.id}|${t.id}`;
      merged.set(k, { file: f.id, topic: t.id, passages: (merged.get(k)?.passages ?? 0) + l.passages });
    }
    const rows = Math.max(files.length, topics.length || 1);
    const height = Math.min(620, Math.max(300, rows * 30));
    const L = stack(files, height, files.length > 14 ? 4 : 8);
    const R = topics.length ? stack(topics, height, topics.length > 14 ? 4 : 8) : [];
    const barW = 12;
    const labelW = Math.min(230, width * 0.24);
    const x0 = labelW + 8;
    const x1 = width - labelW - 8 - barW;
    // Allocate each link a band inside its file bar and its topic bar.
    const fileScale = Object.fromEntries(L.map((n) => [n.id, (n.y1 - n.y0) / (n.passages || 1)]));
    const topicScale = Object.fromEntries(R.map((n) => [n.id, (n.y1 - n.y0) / (n.passages || 1)]));
    const fOff = Object.fromEntries(L.map((n) => [n.id, n.y0]));
    const tOff = Object.fromEntries(R.map((n) => [n.id, n.y0]));
    const tIndex = Object.fromEntries(R.map((n, i) => [n.id, i]));
    const fIndex = Object.fromEntries(L.map((n, i) => [n.id, i]));
    const links = [...merged.values()]
      .sort((a, b) => fIndex[a.file] - fIndex[b.file] || tIndex[a.topic] - tIndex[b.topic])
      .map((l) => {
        const hs = l.passages * fileScale[l.file];
        const s0 = fOff[l.file];
        fOff[l.file] += hs;
        return { ...l, s0, s1: s0 + hs };
      })
      .sort((a, b) => tIndex[a.topic] - tIndex[b.topic] || fIndex[a.file] - fIndex[b.file])
      .map((l) => {
        const ht = l.passages * topicScale[l.topic];
        const t0 = tOff[l.topic];
        tOff[l.topic] += ht;
        return { ...l, t0, t1: t0 + ht };
      });
    return { L, R, links, height, barW, x0, x1, labelW, tIndex };
  }, [data, width]);

  if (!data) return <div ref={box} className="flow-box flow-loading">Drawing your map…</div>;
  if (!data.files.length) {
    return (
      <div ref={box} className="flow-box flow-empty">
        <p>Your map appears here once files are imported.</p>
      </div>
    );
  }

  const { L, R, links, height, barW, x0, x1, labelW, tIndex } = layout;
  const pad = 14;
  const xm = (x0 + barW + x1) / 2;
  const toneOf = (topicId) => TONES[(tIndex[topicId] ?? 0) % TONES.length];

  const active = (l) =>
    !hover ||
    (hover.kind === "file" && l.file === hover.id) ||
    (hover.kind === "topic" && l.topic === hover.id) ||
    (hover.kind === "link" && hover.id === `${l.file}|${l.topic}`);
  const nodeActive = (kind, id) =>
    !hover ||
    (hover.kind === kind && hover.id === id) ||
    links.some((l) => active(l) && (kind === "file" ? l.file === id : l.topic === id));

  // Plain-language note for whatever is hovered.
  let note = R.length
    ? `${plural(data.files.length, "file")} feed ${plural(data.topics.length, "topic")}. Hover anything to trace it; click a topic to open it.`
    : `${plural(data.files.length, "file")} imported. Build topics to see where their knowledge goes.`;
  if (hover?.kind === "file") {
    const f = L.find((n) => n.id === hover.id);
    const n = links.filter((l) => l.file === hover.id).length;
    note = `${f.name}: ${plural(f.passages, "passage")}, spread over ${plural(n, "topic")}.`;
  } else if (hover?.kind === "topic") {
    const t = R.find((n) => n.id === hover.id);
    const n = links.filter((l) => l.topic === hover.id).length;
    note = `${t.title}: ${plural(t.passages, "passage")} from ${plural(n, "file")}.${t.other ? "" : " Click to open."}`;
  } else if (hover?.kind === "link") {
    const l = links.find((x) => `${x.file}|${x.topic}` === hover.id);
    note = `${plural(l.passages, "passage")} from ${L.find((n) => n.id === l.file).name} → ${R.find((n) => n.id === l.topic).title}.`;
  }

  const open = (t) => !t.other && onOpenTopic?.(t.id);

  return (
    <div ref={box} className="flow-box">
      <p className="flow-note" aria-live="polite">
        {note}
      </p>
      <svg
        className="flow-svg"
        viewBox={`0 ${-pad} ${width} ${height + pad * 2}`}
        width="100%"
        preserveAspectRatio="xMidYMid meet"
        role="img"
        aria-label={`Map of ${data.files.length} files feeding ${data.topics.length} topics`}
        onMouseLeave={() => setHover(null)}
      >
        <defs>
          <clipPath id="flow-reveal">
            <rect className="flow-reveal-rect" x="0" y={-pad} width={width} height={height + pad * 2} />
          </clipPath>
        </defs>

        <g clipPath="url(#flow-reveal)">
          {links.map((l) => {
            const a = x0 + barW;
            const path =
              `M${a},${l.s0} C${xm},${l.s0} ${xm},${l.t0} ${x1},${l.t0} ` +
              `L${x1},${l.t1} C${xm},${l.t1} ${xm},${l.s1} ${a},${l.s1} Z`;
            const ys = (l.s0 + l.s1) / 2;
            const yt = (l.t0 + l.t1) / 2;
            const id = `${l.file}|${l.topic}`;
            const on = active(l);
            return (
              <g
                key={id}
                className={`flow-link tone-${toneOf(l.topic)} ${on ? "" : "dim"} ${hover && on ? "lit" : ""}`}
                onMouseEnter={() => setHover({ kind: "link", id })}
              >
                <path className="flow-ribbon" d={path} />
                <path
                  className="flow-stream"
                  d={`M${a},${ys} C${xm},${ys} ${xm},${yt} ${x1},${yt}`}
                  style={{ animationDelay: `${(l.s0 % 7) * -0.4}s` }}
                />
              </g>
            );
          })}
        </g>

        {L.map((n) => (
          <g
            key={`f${n.id}`}
            className={`flow-node file ${nodeActive("file", n.id) ? "" : "dim"}`}
            onMouseEnter={() => setHover({ kind: "file", id: n.id })}
          >
            <rect x={x0} y={n.y0} width={barW} height={n.y1 - n.y0} rx="3" />
            <text x={x0 - 10} y={(n.y0 + n.y1) / 2} dy="0.35em" textAnchor="end">
              {shorten(n.name, Math.floor(labelW / 7.2))}
            </text>
          </g>
        ))}

        {R.length > 0 ? (
          R.map((n, i) => (
            <g
              key={`t${n.id}`}
              className={`flow-node topic tone-${TONES[i % TONES.length]} ${nodeActive("topic", n.id) ? "" : "dim"} ${n.other ? "" : "clickable"}`}
              onMouseEnter={() => setHover({ kind: "topic", id: n.id })}
              onClick={() => open(n)}
              tabIndex={n.other ? undefined : 0}
              role={n.other ? undefined : "button"}
              aria-label={n.other ? undefined : `Open topic ${n.title}`}
              onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && open(n)}
              onFocus={() => setHover({ kind: "topic", id: n.id })}
            >
              <rect x={x1} y={n.y0} width={barW} height={n.y1 - n.y0} rx="3" />
              <text x={x1 + barW + 10} y={(n.y0 + n.y1) / 2} dy="0.35em">
                {shorten(n.title, Math.floor(labelW / 7.2))}
              </text>
            </g>
          ))
        ) : (
          <g className="flow-placeholder">
            <rect x={x1} y={0} width={barW} height={height} rx="3" />
            <text x={x1 - 14} y={height / 2} dy="0.35em" textAnchor="end">
              Topics appear here after Build topics
            </text>
          </g>
        )}
      </svg>
    </div>
  );
}
