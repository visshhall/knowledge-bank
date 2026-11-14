/**
 * QuickSearch.jsx — the Ctrl+K search box, available on every screen.
 *
 * WHAT:  A search panel that opens over the app with Ctrl+K (or the Search
 *        button in the side rail). As you type, it asks the engine for the
 *        best passages by MEANING and by exact WORDS (GET /search/quick) and
 *        shows each with its topic, document part (section), file and page.
 *        - ↑ / ↓ to move, Enter to open the topic, Esc to close.
 *        - A small label says how each result matched ("meaning", "words").
 *        - If the AI engine isn't running, it still works with words only
 *          and says so.
 * WHY:   Phase 4 ("hotkey search"). The owner asks questions the way he
 *        thinks of them; meaning search finds the right passage even when
 *        no word matches, and every result goes straight to its topic.
 * WHEN:  Mounted once by App.jsx; opens on Ctrl+K / the rail button.
 * CONNECTED TO: bridge.js → GET /search/quick (server.py → meaning.py);
 *        App.jsx (onOpenTopic → Topics screen); styles.css (.qs-*).
 */
import { useEffect, useRef, useState } from "react";
import Icon from "./icons.jsx";
import { kb } from "./bridge.js";

/** Highlight exact-word matches marked by the engine (\u0002 … \u0003). */
function Snippet({ text }) {
  const parts = String(text).split(/(\u0002[^\u0003]*\u0003)/g);
  return (
    <span>
      {parts.map((p, i) =>
        p.startsWith("\u0002") ? <mark key={i}>{p.slice(1, -1)}</mark> : <span key={i}>{p}</span>
      )}
    </span>
  );
}

export default function QuickSearch({ open, onClose, onOpenTopic }) {
  const [q, setQ] = useState("");
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(false);
  const [sel, setSel] = useState(0);
  const input = useRef(null);
  const latest = useRef("");

  // Focus the box each time it opens.
  useEffect(() => {
    if (open) setTimeout(() => input.current?.focus(), 10);
  }, [open]);

  // Search 220 ms after typing stops; ignore answers to older queries.
  useEffect(() => {
    if (!open) return undefined;
    const query = q.trim();
    latest.current = query;
    if (query.length < 2) {
      setData(null);
      return undefined;
    }
    setBusy(true);
    const t = setTimeout(async () => {
      const r = await kb.get("/search/quick", { q: query });
      if (latest.current === query) {
        setData(r.error ? { results: [], error: r.error } : r);
        setSel(0);
        setBusy(false);
      }
    }, 220);
    return () => clearTimeout(t);
  }, [q, open]);

  if (!open) return null;
  const results = data?.results ?? [];

  function choose(r) {
    if (r?.topic_id) {
      onOpenTopic(r.topic_id, r.point_id);
      onClose();
    }
  }

  function onKey(e) {
    if (e.key === "Escape") onClose();
    else if (e.key === "ArrowDown") {
      e.preventDefault();
      setSel((s) => Math.min(s + 1, results.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setSel((s) => Math.max(s - 1, 0));
    } else if (e.key === "Enter") choose(results[sel]);
  }

  return (
    <div className="qs-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="qs-panel" role="dialog" aria-modal="true" aria-label="Quick search" onKeyDown={onKey}>
        <div className="qs-input">
          <Icon name="search" size={20} />
          <input
            ref={input}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Ask or search: how to contain a hacked RDP account, 4625, DLL sideloading…"
            aria-label="Search the knowledge bank"
          />
          {busy && <span className="qs-spin" aria-hidden="true" />}
          <kbd>Esc</kbd>
        </div>

        {data?.mode === "words" && results.length > 0 && (
          <p className="qs-mode">Matching exact words only — start the AI engine in Setup to also search by meaning.</p>
        )}

        {q.trim().length < 2 ? (
          <p className="qs-hint">Type a question or any words. Results open their topic. ↑ ↓ to move, Enter to open.</p>
        ) : data && !results.length ? (
          <p className="qs-hint">{data.error ? data.error : "Nothing found. Try other words, or describe what you mean."}</p>
        ) : (
          <ul className="qs-results" role="listbox" aria-label="Results">
            {results.map((r, i) => (
              <li
                key={r.passage_id}
                role="option"
                aria-selected={i === sel}
                className={i === sel ? "on" : ""}
                style={{ animationDelay: `${i * 0.03}s` }}
                onMouseEnter={() => setSel(i)}
                onClick={() => choose(r)}
              >
                <div className="qs-top">
                  <span className="qs-topic">{r.topic_title || "Not in a topic yet"}</span>
                  {r.section && <span className="qs-section">{r.section}</span>}
                  <span className="qs-how">
                    {r.matched.map((m) => (
                      <span key={m} className={`qs-tag ${m}`}>{m}</span>
                    ))}
                  </span>
                </div>
                <p className="qs-snippet">
                  <Snippet text={r.snippet} />
                </p>
                <p className="qs-file">
                  <Icon name="file" size={13} /> {r.file_name} · p.{r.page_number}
                </p>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
