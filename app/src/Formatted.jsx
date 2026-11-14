/**
 * Formatted.jsx — shows PDF text and AI articles as readable, structured pages.
 *
 * WHAT:  Two components:
 *          <Formatted text="…" />   a source passage (raw PDF text, with the
 *                                   line structure kept by chunking.py):
 *                                   headings, bullet lists, numbered lists,
 *                                   query/code blocks and paragraphs, plus
 *                                   "Show more" for long passages.
 *          <Markdown text="…" onCite={fn} />  a written article (Phase 3):
 *                                   ## sections, bullets, numbered steps,
 *                                   ```code``` blocks, **bold**, `code`, and
 *                                   [n] citation markers as clickable chips.
 *        Both highlight MITRE ATT&CK IDs (T1574.002) and Windows event IDs
 *        ("Event ID 4625") as coloured tags, and give every code block a
 *        Copy button and light KQL/SPL colouring.
 * WHY:   Owner feedback (14 Nov 2026): raw passages appeared as one giant
 *        paragraph — "boring, nobody can read this". Structure, colour and
 *        short blocks make the bank scannable.
 *        Built by hand (no Markdown library) so it creates React elements
 *        only — no raw HTML is ever injected, so text from PDFs or from the
 *        AI can never run as code in the app.
 * WHEN:  Used by Topics.jsx (articles + source points) and Library.jsx
 *        (search results) whenever text is displayed.
 * CONNECTED TO: Topics.jsx, Library.jsx; styles.css (.fmt-*, .md-*).
 *        Mirrors the line rules in engine/kb_engine/chunking.py.
 */
import { useState } from "react";

const BULLET = /^\s*([•●▪◦‣∙\-*–])\s+/;
const NUMBERED = /^\s*(\d{1,2})[.)]\s+/;
const LETTERED = /^\s*([a-z])[.)]\s+/;
// Bullet level from its symbol (chunking.py v3 turns Word's "o" / "§"
// sub-bullets into ◦ / ▪): • level 1, ◦ level 2, ▪ level 3.
const LEVEL = { "◦": 2, "▪": 3 };
// Same rule as chunking.py: a table name only counts as code when it stands
// alone or is followed by a pipe ("Sysmon Event IDs:" is a normal sentence).
const CODE_LINE = /^\s*(\||let\s|union\s|search\s|index=|(SecurityEvent|SigninLogs|Device\w+Events|AuditLogs|Sysmon|Event)\s*(\||$))/i;
const KQL_WORDS = /\b(where|project|summarize|extend|join|order by|sort by|take|top|count|distinct|mv-expand|parse|union|render|let|by|bin|ago|has_any|has|contains|startswith|endswith|in~|in|and|or|not|stats|eval|table|dedup|rex|search)\b/gi;
const TOKEN = /(\bT\d{4}(?:\.\d{3})?\b|\bEvent ID\s*\d{1,5}\b|\bEventID\s*==\s*\d{1,5}\b)/g;

// Small joining words don't count against a title ("Containment and Response").
const SMALL_WORDS = new Set(["a", "an", "and", "as", "at", "by", "for", "from", "in", "into", "of", "on", "or", "the", "to", "vs", "via", "with"]);

/** Is a short line a heading? Same rule as chunking.py: mostly capitalised, no end punctuation. */
function isHeading(line) {
  const s = line.trim();
  if (s.length < 3 || s.length > 70 || /[.,;]$/.test(s) || s.includes(" · ")) return false;
  if (!s.includes(" ") && /\d/.test(s)) return false; // "WINRDP01", "4624" are data
  const words = (s.match(/[A-Za-z][A-Za-z'-]*/g) || []).filter((w) => !SMALL_WORDS.has(w.toLowerCase()));
  if (!words.length) return false;
  return words.filter((w) => w[0] === w[0].toUpperCase()).length / words.length >= 0.7;
}

/** Wrap MITRE technique IDs and event IDs in coloured tags inside a string. */
function withTags(text, keyBase = "t") {
  const parts = String(text).split(TOKEN);
  return parts.map((p, i) => {
    if (/^T\d{4}/.test(p)) return <span key={`${keyBase}${i}`} className="tag tag-mitre">{p}</span>;
    if (/^Event/i.test(p)) return <span key={`${keyBase}${i}`} className="tag tag-event">{p}</span>;
    return <span key={`${keyBase}${i}`}>{p}</span>;
  });
}

/** Code block with KQL/SPL keywords coloured and a Copy button. */
function CodeBlock({ code, lang }) {
  const [copied, setCopied] = useState(false);
  async function copy() {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard blocked: nothing to do */
    }
  }
  return (
    <div className="code-block">
      <div className="code-head">
        <span>{lang ? lang.toUpperCase() : "Query"}</span>
        <button className="link" onClick={copy}>
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <pre>
        <code>
          {code.split("\n").map((line, i) => (
            <span key={i} className="code-line">
              {line.split(KQL_WORDS).map((part, j) =>
                j % 2 === 1 ? (
                  <span key={j} className="kw">
                    {part}
                  </span>
                ) : (
                  <span key={j}>{withTags(part, `c${i}-${j}-`)}</span>
                )
              )}
              {"\n"}
            </span>
          ))}
        </code>
      </pre>
    </div>
  );
}

/**
 * Turn a source passage into blocks: heading / list / code / paragraph.
 * RETURNS [{type, lines}] in reading order.
 */
function toBlocks(text) {
  const blocks = [];
  const push = (type, line) => {
    const last = blocks[blocks.length - 1];
    if (last && last.type === type && type !== "heading" && type !== "para") last.lines.push(line);
    else blocks.push({ type, lines: [line] });
  };
  for (const raw of String(text).split("\n")) {
    const line = raw.trim();
    if (!line) continue;
    if (line.includes(" · ")) push("table", line.split(" · ").map((c) => (c === "—" ? "" : c)));
    else if (CODE_LINE.test(line)) push("code", line);
    else if (BULLET.test(line)) {
      const sym = line.match(BULLET)[1];
      push("list", { marker: null, level: LEVEL[sym] ?? 1, text: line.replace(BULLET, "") });
    } else if (NUMBERED.test(line)) {
      // Keep the document's own number ("3."), never renumber from 1.
      push("list", { marker: `${line.match(NUMBERED)[1]}.`, level: 1, text: line.replace(NUMBERED, "") });
    } else if (LETTERED.test(line)) {
      push("list", { marker: `${line.match(LETTERED)[1]})`, level: 2, text: line.replace(LETTERED, "") });
    }
    else if (isHeading(line)) push("heading", line);
    else push("para", line);
  }
  return blocks;
}

/**
 * Table rows (cells joined by " · " — from PDF tables, scanned tables and
 * spreadsheets) drawn as a real table. The first row is a header when all
 * its cells are short words without digits ("Step | Action").
 */
function RowTable({ rows }) {
  const width = Math.max(...rows.map((r) => r.length));
  const head = rows.length > 1 && rows[0].every((c) => c && c.length <= 30 && !/\d/.test(c));
  const body = head ? rows.slice(1) : rows;
  const pad = (r) => [...r, ...Array(width - r.length).fill("")];
  return (
    <div className="fmt-table-wrap">
      <table className="fmt-table">
        {head && (
          <thead>
            <tr>
              {pad(rows[0]).map((c, j) => (
                <th key={j}>{c}</th>
              ))}
            </tr>
          </thead>
        )}
        <tbody>
          {body.map((r, i) => (
            <tr key={i}>
              {pad(r).map((c, j) => (
                <td key={j}>{withTags(c, `r${i}-${j}-`)}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** A source passage, structured, with Show more/less beyond `collapseAt` blocks. */
export function Formatted({ text, collapseAt = 6 }) {
  const [open, setOpen] = useState(false);
  const blocks = toBlocks(text);
  const shown = open ? blocks : blocks.slice(0, collapseAt);
  return (
    <div className="fmt">
      {shown.map((b, i) => {
        if (b.type === "heading") return <p key={i} className="fmt-heading">{withTags(b.lines[0])}</p>;
        if (b.type === "code") return <CodeBlock key={i} code={b.lines.join("\n")} />;
        // A single stray row is shown as a sentence; 2+ rows are a table.
        if (b.type === "table" && b.lines.length === 1)
          return <p key={i} className="fmt-para">{withTags(b.lines[0].filter(Boolean).join(" · "))}</p>;
        if (b.type === "table") return <RowTable key={i} rows={b.lines} />;
        if (b.type === "list")
          return (
            // One list for numbered items and nested bullets together, so
            // sub-points sit indented under their item, as in the document.
            <ul key={i} className="fmt-tree">
              {b.lines.map((it, j) => (
                <li key={j} className={`lvl-${it.level}`}>
                  <span className={it.marker ? "mk num" : "mk"} aria-hidden={it.marker ? undefined : "true"}>
                    {it.marker ?? ""}
                  </span>
                  <span>{withTags(it.text)}</span>
                </li>
              ))}
            </ul>
          );
        return <p key={i} className="fmt-para">{withTags(b.lines[0])}</p>;
      })}
      {blocks.length > collapseAt && (
        <button className="link more" onClick={() => setOpen(!open)}>
          {open ? "Show less" : `Show ${blocks.length - collapseAt} more`}
        </button>
      )}
    </div>
  );
}

/** Inline Markdown: **bold**, `code`, [n] citations, MITRE/event tags. */
function inline(text, onCite, keyBase) {
  const parts = String(text).split(/(\*\*[^*]+\*\*|`[^`]+`|\[\d+\])/g);
  return parts.map((p, i) => {
    const k = `${keyBase}-${i}`;
    if (/^\*\*[^*]+\*\*$/.test(p)) return <strong key={k}>{withTags(p.slice(2, -2), k)}</strong>;
    if (/^`[^`]+`$/.test(p)) return <code key={k} className="inline-code">{p.slice(1, -1)}</code>;
    if (/^\[\d+\]$/.test(p)) {
      const n = p.slice(1, -1);
      return (
        <button key={k} className="cite" onClick={() => onCite?.(n)} aria-label={`Show source ${n}`}>
          {n}
        </button>
      );
    }
    return <span key={k}>{withTags(p, k)}</span>;
  });
}

/** Section colours cycle so each part of an article is easy to spot. */
const SECTION_TONES = ["teal", "coral", "violet", "mustard"];

/**
 * A written article (Markdown subset produced by writer.py).
 * onCite(n) is called when a citation chip is clicked.
 */
/**
 * Article Markdown. `figures` (v0.8) is an optional map of section number →
 * element, placed at the end of that section (Topics.jsx puts the lesson's
 * diagrams next to the part of the article they explain).
 */
export function Markdown({ text, onCite, figures }) {
  const lines = String(text).split("\n");
  const out = [];
  let i = 0;
  let section = -1;
  while (i < lines.length) {
    const line = lines[i];
    if (/^```/.test(line.trim())) {
      const lang = line.trim().slice(3).trim();
      const code = [];
      i += 1;
      while (i < lines.length && !/^```/.test(lines[i].trim())) code.push(lines[i++]);
      i += 1;
      out.push(<CodeBlock key={`c${i}`} code={code.join("\n")} lang={lang} />);
      continue;
    }
    if (/^#{2,3}\s+/.test(line)) {
      if (section >= 0 && figures?.[section]) out.push(<div key={`f${section}`}>{figures[section]}</div>);
      section += 1;
      out.push(
        <h2 key={`h${i}`} className={`md-h tone-${SECTION_TONES[section % SECTION_TONES.length]}`}>
          <span className="md-h-mark" aria-hidden="true" />
          {line.replace(/^#{2,3}\s+/, "")}
        </h2>
      );
      i += 1;
      continue;
    }
    if (/^\s*[-*]\s+/.test(line)) {
      const items = [];
      while (i < lines.length && /^\s*[-*]\s+/.test(lines[i])) items.push(lines[i++].replace(/^\s*[-*]\s+/, ""));
      out.push(
        <ul key={`u${i}`} className="md-list">
          {items.map((t, j) => <li key={j}>{inline(t, onCite, `u${i}-${j}`)}</li>)}
        </ul>
      );
      continue;
    }
    if (/^\s*\d+[.)]\s+/.test(line)) {
      const items = [];
      while (i < lines.length && /^\s*\d+[.)]\s+/.test(lines[i])) items.push(lines[i++].replace(/^\s*\d+[.)]\s+/, ""));
      out.push(
        <ol key={`o${i}`} className="md-steps">
          {items.map((t, j) => <li key={j}>{inline(t, onCite, `o${i}-${j}`)}</li>)}
        </ol>
      );
      continue;
    }
    if (line.trim()) {
      out.push(<p key={`p${i}`} className="md-p">{inline(line, onCite, `p${i}`)}</p>);
    }
    i += 1;
  }
  if (section >= 0 && figures?.[section]) out.push(<div key={`f${section}`}>{figures[section]}</div>);
  return <div className="md">{out}</div>;
}
