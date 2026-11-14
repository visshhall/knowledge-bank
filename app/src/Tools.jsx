/**
 * Tools.jsx — Phase 6 analyst tools.
 *
 * WHAT:  Four tabs:
 *          1. Extract IOCs — paste an alert, email or log; get every IP,
 *             domain, URL, email, hash, CVE and ATT&CK ID, de-duplicated,
 *             with private IPs marked. Switch between defanged (safe to
 *             paste into reports/chat) and live values; copy one group or
 *             everything. Look up a value on VirusTotal / NVD in your
 *             browser if you choose.
 *          2. IOCs in your bank — the same, across all your documents, with
 *             where each appears.
 *          3. MITRE ATT&CK — every technique your documents mention, with
 *             official names (bundled offline), tactics as a bar strip, how
 *             often it's mentioned, which topics cover it, and a link to its
 *             ATT&CK page.
 *          4. Query library — every KQL / SPL query in your documents,
 *             de-duplicated, filterable, with Copy and its source.
 *        Plus an optional web search box: opens your normal browser with
 *        only the words you typed (nothing is sent automatically).
 * WHY:   Daily SOC tasks, done offline against the owner's own material.
 * WHEN:  The "Tools" screen in the side rail.
 * CONNECTED TO: bridge.js → POST /tools/iocs, GET /tools/bank-iocs,
 *        /tools/mitre, /tools/queries (server.py → tools.py); kb.webOpen
 *        (main.cjs "web:open"); SourceChip.jsx; App.jsx (onOpenTopic).
 */
import { useEffect, useState } from "react";
import Icon from "./icons.jsx";
import SourceChip from "./SourceChip.jsx";
import { formatCount, kb } from "./bridge.js";

const TABS = [
  { id: "extract", label: "Extract IOCs" },
  { id: "bank", label: "IOCs in your bank" },
  { id: "mitre", label: "MITRE ATT&CK" },
  { id: "queries", label: "Query library" },
];

async function copy(text, setCopied, key) {
  try {
    await navigator.clipboard.writeText(text);
    setCopied(key);
    setTimeout(() => setCopied(null), 1400);
  } catch {
    /* clipboard blocked — nothing else to do */
  }
}

export default function Tools({ onOpenTopic }) {
  const [tab, setTab] = useState("extract");
  const [web, setWeb] = useState("");
  return (
    <div className="tools">
      <header className="page-head">
        <h1>Tools</h1>
        <p className="lede">Indicator extraction, ATT&CK coverage and your query library — all offline, from your own documents.</p>
      </header>

      <div className="tabs" role="tablist" aria-label="Tools">
        {TABS.map((t) => (
          <button key={t.id} role="tab" aria-selected={tab === t.id} className={tab === t.id ? "tab on" : "tab"} onClick={() => setTab(t.id)}>
            {t.label}
          </button>
        ))}
      </div>

      {tab === "extract" && <Extract />}
      {tab === "bank" && <BankIocs />}
      {tab === "mitre" && <Mitre onOpenTopic={onOpenTopic} />}
      {tab === "queries" && <Queries onOpenTopic={onOpenTopic} />}

      <form
        className="card web-box"
        onSubmit={(e) => {
          e.preventDefault();
          if (web.trim()) kb.webOpen("search", web.trim());
        }}
      >
        <Icon name="globe" size={20} />
        <input value={web} onChange={(e) => setWeb(e.target.value)} placeholder="Search the web for something not in your files" aria-label="Web search" />
        <button type="submit" className="secondary" disabled={!web.trim()}>
          Search in browser
        </button>
        <p className="small muted web-note">Opens your normal browser. Only the words you type here are sent; your documents never leave the laptop.</p>
      </form>
    </div>
  );
}

/** One IOC group (e.g. "Domains") with copy buttons and look-ups. */
function IocGroup({ g, defanged, withWhere }) {
  const [copied, setCopied] = useState(null);
  const vals = g.items.map((i) => (defanged ? i.defanged : i.value));
  const lookup = { ipv4: "virustotal", domain: "virustotal", url: "virustotal", sha256: "virustotal", sha1: "virustotal", md5: "virustotal", cve: "cve", mitre: "mitre" }[g.type];
  return (
    <section className="card ioc-group">
      <div className="section-head">
        <h2>
          {g.label} <span className="count">{g.items.length}</span>
        </h2>
        <button className="secondary small-btn" onClick={() => copy(vals.join("\n"), setCopied, "all")}>
          <Icon name="copy" size={14} /> {copied === "all" ? "Copied" : "Copy all"}
        </button>
      </div>
      <ul className="ioc-list">
        {g.items.map((i, k) => (
          <li key={i.value} style={{ animationDelay: `${Math.min(k, 20) * 0.02}s` }}>
            <code>{defanged ? i.defanged : i.value}</code>
            {i.note && <span className={`ioc-note ${i.note.startsWith("private") ? "private" : ""}`}>{i.note}</span>}
            {i.count > 1 && <span className="small muted">×{i.count}</span>}
            <span className="ioc-actions">
              <button className="link small" onClick={() => copy(defanged ? i.defanged : i.value, setCopied, i.value)}>
                {copied === i.value ? "Copied" : "Copy"}
              </button>
              {lookup && !i.note.startsWith("private") && (
                <button className="link small" onClick={() => kb.webOpen(lookup, i.value)} title="Opens your browser with only this value">
                  Look up <Icon name="open" size={11} />
                </button>
              )}
            </span>
            {withWhere && i.where?.length > 0 && (
              <ul className="point-sources ioc-where">
                {i.where.map((w, j) => (
                  <SourceChip key={j} sourceId={w.source_id} fileName={w.file_name} page={w.page} />
                ))}
              </ul>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}

function DefangSwitch({ defanged, setDefanged }) {
  return (
    <div className="points-bar" role="group" aria-label="Value format">
      <button className={defanged ? "seg on" : "seg"} onClick={() => setDefanged(true)} aria-pressed={defanged}>
        Defanged (safe to share)
      </button>
      <button className={!defanged ? "seg on" : "seg"} onClick={() => setDefanged(false)} aria-pressed={!defanged}>
        Live values
      </button>
    </div>
  );
}

function Extract() {
  const [text, setText] = useState("");
  const [res, setRes] = useState(null);
  const [defanged, setDefanged] = useState(true);
  useEffect(() => {
    if (!text.trim()) return setRes(null);
    const t = setTimeout(() => kb.post("/tools/iocs", { text }).then((r) => !r.error && setRes(r)), 250);
    return () => clearTimeout(t);
  }, [text]);
  return (
    <div className="tool-pane">
      <textarea
        className="card ioc-input"
        spellCheck={false}
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="Paste an alert, email, log or report. Defanged values like hxxp:// and 1[.]2[.]3[.]4 are understood."
        aria-label="Text to extract indicators from"
      />
      {res && (
        <>
          <div className="tool-bar">
            <p className="muted">{res.total ? `${formatCount(res.total)} indicators found` : "No indicators found."}</p>
            {res.total > 0 && <DefangSwitch defanged={defanged} setDefanged={setDefanged} />}
          </div>
          {res.groups.map((g) => (
            <IocGroup key={g.type} g={g} defanged={defanged} />
          ))}
        </>
      )}
    </div>
  );
}

function BankIocs() {
  const [res, setRes] = useState(null);
  const [defanged, setDefanged] = useState(true);
  useEffect(() => {
    kb.get("/tools/bank-iocs").then((r) => setRes(r.error ? { groups: [], total: 0 } : r));
  }, []);
  if (!res) return <p className="muted">Scanning every passage…</p>;
  return (
    <div className="tool-pane">
      <div className="tool-bar">
        <p className="muted">{formatCount(res.total)} distinct indicators across your documents.</p>
        {res.total > 0 && <DefangSwitch defanged={defanged} setDefanged={setDefanged} />}
      </div>
      {res.groups.map((g) => (
        <IocGroup key={g.type} g={g} defanged={defanged} withWhere />
      ))}
    </div>
  );
}

function Mitre({ onOpenTopic }) {
  const [res, setRes] = useState(null);
  const [tactic, setTactic] = useState(null);
  useEffect(() => {
    kb.get("/tools/mitre").then((r) => setRes(r.error ? { techniques: [], tactics: [] } : r));
  }, []);
  if (!res) return <p className="muted">Reading techniques…</p>;
  if (!res.techniques.length) return <p className="card muted">No ATT&CK technique IDs (like T1059) appear in your documents yet.</p>;
  const max = Math.max(...res.tactics.map((t) => t.count));
  const list = tactic ? res.techniques.filter((t) => (t.tactics.length ? t.tactics : ["unknown"]).includes(tactic)) : res.techniques;
  return (
    <div className="tool-pane">
      <section className="card">
        <h2>Coverage by tactic</h2>
        <p className="small muted">How many distinct techniques your documents mention in each ATT&CK tactic. Click a tactic to filter.</p>
        <div className="tactic-strip">
          {res.tactics.map((t, i) => (
            <button
              key={t.tactic}
              className={`tactic ${tactic === t.tactic ? "on" : ""}`}
              onClick={() => setTactic(tactic === t.tactic ? null : t.tactic)}
              aria-pressed={tactic === t.tactic}
            >
              <span className="tactic-bar">
                <span style={{ height: `${(100 * t.count) / max}%`, animationDelay: `${i * 0.04}s` }} />
              </span>
              <strong>{t.count}</strong>
              <span>{t.tactic.replace(/-/g, " ")}</span>
            </button>
          ))}
        </div>
      </section>
      <ul className="tech-list">
        {list.map((t) => (
          <li key={t.id} className="card">
            <div className="tech-top">
              <span className="tag tag-mitre">{t.id}</span>
              <strong>{t.name || "Unknown technique ID"}</strong>
              <span className="small muted">mentioned {t.count}×</span>
              <button className="link small tech-link" onClick={() => kb.webOpen("mitre", t.id)} title="Opens attack.mitre.org in your browser">
                ATT&CK page <Icon name="open" size={11} />
              </button>
            </div>
            {t.tactics.length > 0 && <p className="small muted">{t.tactics.map((x) => x.replace(/-/g, " ")).join(" · ")}</p>}
            <ul className="point-sources">
              {t.topics.map((tp) => (
                <li key={tp.id}>
                  <button className="chip-open topic-chip" onClick={() => onOpenTopic(tp.id)}>
                    <Icon name="topics" size={13} /> {tp.title}
                  </button>
                </li>
              ))}
              {t.where.slice(0, 3).map((w, j) => (
                <SourceChip key={j} sourceId={w.source_id} fileName={w.file_name} page={w.page} />
              ))}
            </ul>
          </li>
        ))}
      </ul>
    </div>
  );
}

function Queries({ onOpenTopic }) {
  const [res, setRes] = useState(null);
  const [filter, setFilter] = useState("");
  const [copied, setCopied] = useState(null);
  useEffect(() => {
    kb.get("/tools/queries").then((r) => setRes(r.error ? { queries: [], total: 0 } : r));
  }, []);
  if (!res) return <p className="muted">Collecting queries…</p>;
  if (!res.total) return <p className="card muted">No KQL or SPL queries were found in your documents yet.</p>;
  const f = filter.trim().toLowerCase();
  const list = f ? res.queries.filter((q) => `${q.query} ${q.table} ${q.topic_title ?? ""} ${q.section ?? ""}`.toLowerCase().includes(f)) : res.queries;
  return (
    <div className="tool-pane">
      <div className="tool-bar">
        <input className="filter-input" value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Filter: table, keyword, event ID…" aria-label="Filter queries" />
        <p className="muted">
          {formatCount(list.length)} of {formatCount(res.total)} queries
        </p>
      </div>
      <ul className="query-list">
        {list.map((q, i) => (
          <li key={i} className="card">
            <div className="tech-top">
              <span className={`tag ${q.lang === "SPL" ? "tag-event" : "tag-mitre"}`}>{q.lang}</span>
              {q.table && <strong>{q.table}</strong>}
              {q.section && <span className="small muted">{q.section}</span>}
              <button className="link small tech-link" onClick={() => copy(q.query, setCopied, i)}>
                <Icon name="copy" size={13} /> {copied === i ? "Copied" : "Copy"}
              </button>
            </div>
            <pre className="query-code">
              <code>{q.query}</code>
            </pre>
            <ul className="point-sources">
              {q.topic_id && (
                <li>
                  <button className="chip-open topic-chip" onClick={() => onOpenTopic(q.topic_id, q.point_id)}>
                    <Icon name="topics" size={13} /> {q.topic_title}
                  </button>
                </li>
              )}
              <SourceChip sourceId={q.source_id} fileName={q.file_name} page={q.page} />
              {q.also > 0 && <li className="small muted">also in {q.also} other place{q.also === 1 ? "" : "s"}</li>}
            </ul>
          </li>
        ))}
      </ul>
    </div>
  );
}
