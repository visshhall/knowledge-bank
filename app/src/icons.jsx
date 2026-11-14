/**
 * icons.jsx — the app's small line icons, drawn as inline SVG.
 *
 * WHAT:  One <Icon name="..." /> component with a fixed set of 24×24
 *        stroke icons: overview, library, topics, setup, search, upload,
 *        folder, eye, sparkle, arrow-left, file, check, alert, refresh,
 *        and (v0.7) answer, learn, tools, map, grid, open, lock, globe, copy.
 * WHY:   Icons make the side rail and buttons quicker to scan. Drawing them
 *        inline (instead of an icon font or image files) keeps them crisp at
 *        any size, lets them take the text colour (currentColor), and works
 *        fully offline with zero extra downloads.
 * WHEN:  Rendered wherever a screen shows an icon (App.jsx rail, Library,
 *        Topics, Overview).
 * CONNECTED TO: used by App.jsx, Overview.jsx, Library.jsx, Topics.jsx.
 *        Standalone otherwise — no data, no engine calls.
 */

/** Path data per icon (stroke-based, 24×24 grid, 1.8 px lines). */
const PATHS = {
  overview: ["M3 13h8V3H3z", "M13 21h8V11h-8z", "M13 3h8v6h-8z", "M3 21h8v-6H3z"],
  library: ["M4 19.5V5a2 2 0 0 1 2-2h12v18H6a2 2 0 0 1-2-1.5z", "M8 7h7", "M8 11h7"],
  topics: ["M12 3a3 3 0 1 0 0 6a3 3 0 1 0 0-6z", "M5 15a3 3 0 1 0 0 6a3 3 0 1 0 0-6z", "M19 15a3 3 0 1 0 0 6a3 3 0 1 0 0-6z", "M10.5 8.6 6.5 15.4", "M13.5 8.6l4 6.8", "M8 18h8"],
  setup: ["M12 15a3 3 0 1 0 0-6a3 3 0 0 0 0 6z", "M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"],
  search: ["M11 4a7 7 0 1 0 0 14a7 7 0 1 0 0-14z", "M20 20l-4-4"],
  upload: ["M12 16V4", "M7 9l5-5 5 5", "M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3"],
  folder: ["M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"],
  eye: ["M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z", "M12 9a3 3 0 1 0 0 6a3 3 0 1 0 0-6z"],
  sparkle: ["M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z", "M19 16l.8 2.2L22 19l-2.2.8L19 22l-.8-2.2L16 19l2.2-.8z"],
  "arrow-left": ["M19 12H5", "M11 6l-6 6 6 6"],
  // v0.7
  answer: ["M4 5h16v11H9l-5 4z", "M8 9h8", "M8 12.5h5"],
  learn: ["M3 7l9-4 9 4-9 4z", "M7 9.5v5c0 1.5 2.2 3 5 3s5-1.5 5-3v-5", "M21 7v6"],
  tools: ["M12 3l7 3v5c0 4.5-3 8-7 10-4-2-7-5.5-7-10V6z", "M9 12l2 2 4-4"],
  map: ["M5 5a2 2 0 1 0 0 4a2 2 0 1 0 0-4z", "M19 4a2 2 0 1 0 0 4a2 2 0 1 0 0-4z", "M12 16a2 2 0 1 0 0 4a2 2 0 1 0 0-4z", "M7 6.8l10-0.6", "M6.2 8.7l4.8 7.6", "M17.9 7.7l-4.9 8.5"],
  grid: ["M4 4h7v7H4z", "M13 4h7v7h-7z", "M4 13h7v7H4z", "M13 13h7v7h-7z"],
  open: ["M14 4h6v6", "M20 4l-9 9", "M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"],
  lock: ["M6 11h12v9H6z", "M8.5 11V8a3.5 3.5 0 0 1 7 0v3"],
  globe: ["M12 3a9 9 0 1 0 0.01 0z", "M3 12h18", "M12 3c2.5 2.5 3.5 5.5 3.5 9s-1 6.5-3.5 9c-2.5-2.5-3.5-5.5-3.5-9s1-6.5 3.5-9z"],
  copy: ["M9 9h11v11H9z", "M5 15H4V4h11v1"],
  file: ["M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z", "M14 3v5h5"],
  check: ["M5 12.5l4.5 4.5L19 7.5"],
  alert: ["M12 3l9.5 17h-19z", "M12 10v4", "M12 17.5v.5"],
  refresh: ["M20 11a8 8 0 0 0-14.6-4.5L4 8", "M4 4v4h4", "M4 13a8 8 0 0 0 14.6 4.5L20 16", "M20 20v-4h-4"],
};

/**
 * <Icon name="topics" size={18} />
 * Decorative by default (hidden from screen readers); pass `label` when the
 * icon is the only content of a control so it gets an accessible name.
 */
export default function Icon({ name, size = 20, label }) {
  const paths = PATHS[name] ?? [];
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden={label ? undefined : "true"}
      role={label ? "img" : undefined}
      aria-label={label}
      focusable="false"
    >
      {paths.map((d, i) => (
        <path key={i} d={d} />
      ))}
    </svg>
  );
}
