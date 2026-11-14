/**
 * Schematic.jsx — the Overview's signature drawing: how the bank is built.
 *
 * WHAT:  An engineering-style diagram drawn in SVG:
 *          your files  ──┐
 *          your files  ──┼──▶  [ the bank: passages ]  ──┬──▶ topic
 *          your files  ──┘                               └──▶ topic
 *        Node counts and labels come from real totals (sources, passages,
 *        topics). Anything not built yet is drawn dashed, like a planned
 *        part on a blueprint.
 * WHY:   It replaces the old floating-dots background (too close to the
 *        owner's other app, LumenSutra). The blueprint look suits a tool
 *        that maps knowledge, and the drawing explains the app's whole idea
 *        — many files in, one organised bank out — at a glance.
 * WHEN:  Shown at the top of the Overview screen. It draws itself once,
 *        line by line, when the screen opens (the app's single deliberate
 *        animation), then stays still. Windows' "reduce animations" setting
 *        shows it fully drawn immediately (see styles.css).
 * CONNECTED TO: Overview.jsx (passes the totals), styles.css (.schematic*).
 *        Phase 4 grows this into the interactive Knowledge Map.
 */

const MAX_NODES = 7; // more files than this are summarised as "+N"

/**
 * Build the vertical positions for `n` nodes centred on `mid`, `gap` apart.
 */
function column(n, mid, gap) {
  const top = mid - ((n - 1) * gap) / 2;
  return Array.from({ length: n }, (_, i) => top + i * gap);
}

export default function Schematic({ sources = 0, passages = 0, topics = 0 }) {
  const W = 680;
  const H = 300;
  const MID = 150;

  const srcShown = Math.min(Math.max(sources, 0), MAX_NODES);
  const srcPlanned = sources === 0;
  const srcYs = column(srcPlanned ? 3 : srcShown, MID, 32);

  const topicShown = Math.min(topics, 5);
  const topicPlanned = topics === 0;
  const topicYs = column(topicPlanned ? 3 : topicShown, MID, 40);

  // Bank box geometry.
  const bank = { x: 280, y: MID - 46, w: 150, h: 92 };
  let step = 0; // animation order: each line/node waits for the previous

  return (
    <svg
      className="schematic"
      viewBox={`0 0 ${W} ${H}`}
      role="img"
      aria-label={`${sources} files, ${passages} passages, ${topics} topics`}
    >
      {/* ---- Sources (left) ---- */}
      <text className="sch-label" x={36} y={28}>
        Your files
      </text>
      <text className="sch-value" x={36} y={52}>
        {sources}
      </text>
      {srcYs.map((y, i) => (
        <g key={`s${i}`} className={srcPlanned ? "planned" : ""}>
          <path
            className="sch-line"
            pathLength="1"
            style={{ animationDelay: `${0.08 * step++}s` }}
            d={`M 62 ${y} H 200 V ${MID} H ${bank.x}`}
          />
          <rect
            className="sch-node"
            x={36}
            y={y - 9}
            width={26}
            height={18}
            style={{ animationDelay: `${0.08 * step}s` }}
          />
        </g>
      ))}
      {sources > MAX_NODES && (
        <text className="sch-small" x={36} y={srcYs[srcYs.length - 1] + 30}>
          +{sources - MAX_NODES} more
        </text>
      )}

      {/* ---- The bank (centre) ---- */}
      <rect
        className={`sch-bank ${passages === 0 ? "planned" : ""}`}
        x={bank.x}
        y={bank.y}
        width={bank.w}
        height={bank.h}
        style={{ animationDelay: `${0.08 * step++ + 0.2}s` }}
      />
      <text className="sch-value" x={bank.x + 16} y={bank.y + 40}>
        {passages.toLocaleString("en-US")}
      </text>
      <text className="sch-label" x={bank.x + 16} y={bank.y + 64}>
        passages in the bank
      </text>

      {/* ---- Topics (right) ---- */}
      <text className="sch-label" x={560} y={28}>
        Topics
      </text>
      <text className="sch-value" x={560} y={52}>
        {topics}
      </text>
      {topicYs.map((y, i) => (
        <g key={`t${i}`} className={topicPlanned ? "planned" : ""}>
          <path
            className="sch-line"
            pathLength="1"
            style={{ animationDelay: `${0.08 * step++ + 0.4}s` }}
            d={`M ${bank.x + bank.w} ${MID} H 500 V ${y} H 560`}
          />
          <circle
            className="sch-node"
            cx={572}
            cy={y}
            r={11}
            style={{ animationDelay: `${0.08 * step + 0.4}s` }}
          />
        </g>
      ))}
      {topicPlanned && (
        <text className="sch-small" x={540} y={topicYs[2] + 36}>
          written in a later update
        </text>
      )}
    </svg>
  );
}
