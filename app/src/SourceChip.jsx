/**
 * SourceChip.jsx — a file + page reference you can click to open.
 *
 * WHAT:  Shows "file.pdf p.12". Clicking opens the ORIGINAL file at that
 *        page in a viewer window (kb.openFile → main.cjs "file:open").
 *        If the original was moved or deleted, a short note says so.
 * WHY:   Phase 4 "open the original PDF at the cited page": every citation
 *        in topics, lessons and answers can be checked against the real
 *        page in one click.
 * WHEN:  Used wherever a source is listed (Topics.jsx, Answers.jsx).
 * CONNECTED TO: bridge.js (kb.openFile), electron/main.cjs, icons.jsx,
 *        styles.css (.point-sources, .chip-open).
 */
import { useState } from "react";
import Icon from "./icons.jsx";
import { kb } from "./bridge.js";

export default function SourceChip({ sourceId, fileName, page, label }) {
  const [problem, setProblem] = useState("");
  async function open() {
    setProblem("");
    const r = await kb.openFile(sourceId, page);
    if (r?.error) setProblem(r.error);
  }
  return (
    <li>
      <button className="chip-open" onClick={open} disabled={!sourceId} title="Open the original at this page">
        <Icon name="file" size={14} />
        {fileName} <span>{label ?? `p.${page}`}</span>
        <Icon name="open" size={12} />
      </button>
      {problem && <span className="chip-problem">{problem}</span>}
    </li>
  );
}
