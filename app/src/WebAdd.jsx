/**
 * WebAdd.jsx — v0.13 "Add from the web" and "Paste text" (a card on the Library screen).
 *
 * WHAT:  Two ways to put things in the bank that are not files on disk:
 *        1. A web address. The engine reads that page and, depending on the
 *           choice, the pages it links to on the same site ("This page only",
 *           "This page and the pages under it", "The whole site"), up to a page
 *           limit. While it reads, the card shows how many pages were read and
 *           added, the latest pages with what happened to each, and why some
 *           were skipped (robots.txt, no readable text, other site …). Stop keeps
 *           what was already read.
 *        2. Pasted text with an optional title (a note, an email, a product
 *           description — anything).
 *        Everything read goes through the normal import, so it is searchable and
 *        usable in Chat and Topics like any file.
 * WHY:   The owner wants the app to learn from anything, not only his PDFs.
 * WHEN:  Shown on the Library screen under the drop zone. Polls GET /crawl/status
 *        every 1.2 s while it is open (and keeps showing a running read if he
 *        leaves and comes back).
 * CONNECTED TO: bridge.js → engine /crawl/start, /crawl/status, /crawl/stop,
 *        /library/add-text (server.py → crawler.py, importer.add_text);
 *        Library.jsx (renders this and reloads its file list through onChanged).
 * NOTE:  The engine refuses addresses on this computer or the local network and
 *        only follows links on the same site. It cannot run JavaScript, so pages
 *        built entirely in the browser come back empty (counted as skipped).
 */
import { useEffect, useRef, useState } from "react";
import Icon from "./icons.jsx";
import { kb, usePoll } from "./bridge.js";

const SCOPES = [
  { id: "page", label: "This page only", pages: 1 },
  { id: "section", label: "This page and the pages under it", pages: 30 },
  { id: "site", label: "The whole site", pages: 100 },
];

export default function WebAdd({ onChanged }) {
  const [tab, setTab] = useState("web"); // "web" | "text"
  const [url, setUrl] = useState("");
  const [scope, setScope] = useState("section");
  const [maxPages, setMaxPages] = useState(30);
  const [message, setMessage] = useState(null); // { kind: "ok" | "error", text }
  const [title, setTitle] = useState("");
  const [text, setText] = useState("");
  const [job, reloadJob] = usePoll("/crawl/status", 1200);
  const running = job?.state === "running";

  function pickScope(id) {
    setScope(id);
    setMaxPages(SCOPES.find((s) => s.id === id).pages);
  }

  async function read() {
    setMessage(null);
    const r = await kb.post("/crawl/start", { url, scope, max_pages: Number(maxPages) || 30 });
    if (r.error || r.ok === false) {
      setMessage({ kind: "error", text: r.message || r.error });
      return;
    }
    reloadJob();
  }

  async function stop() {
    await kb.post("/crawl/stop", {});
    reloadJob();
  }

  async function addText() {
    setMessage(null);
    const r = await kb.post("/library/add-text", { title, text });
    if (r.error || r.ok === false) {
      setMessage({ kind: "error", text: r.message || r.error });
      return;
    }
    setMessage({ kind: r.added ? "ok" : "error", text: r.added ? "Added to the bank." : r.message });
    if (r.added) {
      setTitle("");
      setText("");
      onChanged?.();
    }
  }

  const skipped = Object.entries(job?.skipped ?? {});
  const hasJob = job && job.state && job.state !== "idle";

  // Tell the Library to reload its list whenever the number of added pages changes.
  const stored = job?.stored ?? 0;
  const lastStored = useRef(0);
  useEffect(() => {
    if (stored && stored !== lastStored.current) onChanged?.();
    lastStored.current = stored;
  }, [stored, onChanged]);

  return (
    <section className="card web-add" aria-label="Add from the web or paste text">
      <div className="web-tabs" role="tablist">
        <button role="tab" aria-selected={tab === "web"} className={`seg ${tab === "web" ? "on" : ""}`} onClick={() => setTab("web")}>
          <Icon name="globe" size={15} /> From the web
        </button>
        <button role="tab" aria-selected={tab === "text"} className={`seg ${tab === "text" ? "on" : ""}`} onClick={() => setTab("text")}>
          <Icon name="file" size={15} /> Paste text
        </button>
      </div>

      {tab === "web" ? (
        <form
          className="web-form"
          onSubmit={(e) => {
            e.preventDefault();
            if (!running) read();
          }}
        >
          <label>
            <span className="small">Web address</span>
            <input
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://example.com/guides/"
              inputMode="url"
              spellCheck={false}
              disabled={running}
            />
          </label>
          <fieldset className="web-scope" disabled={running}>
            <legend className="small">How much to read</legend>
            {SCOPES.map((s) => (
              <label key={s.id} className="radio">
                <input type="radio" name="scope" checked={scope === s.id} onChange={() => pickScope(s.id)} /> {s.label}
              </label>
            ))}
          </fieldset>
          {scope !== "page" && (
            <label className="web-limit">
              <span className="small">Read at most</span>
              <input
                type="number"
                min={1}
                max={500}
                value={maxPages}
                onChange={(e) => setMaxPages(e.target.value)}
                disabled={running}
              />
              <span className="small">pages (up to 500)</span>
            </label>
          )}
          <div className="web-actions">
            {running ? (
              <button type="button" className="secondary" onClick={stop}>
                Stop
              </button>
            ) : (
              <button type="submit" disabled={url.trim().length < 4}>
                <Icon name="globe" size={18} /> Read
              </button>
            )}
          </div>
          <p className="muted small">
            Pages are read one at a time with a pause between them, only on the same site, and the site's robots.txt is
            respected. Only read sites you may copy for your own use — the bank keeps a copy of the text. Pages that
            only show content with JavaScript can't be read.
          </p>
        </form>
      ) : (
        <form
          className="web-form"
          onSubmit={(e) => {
            e.preventDefault();
            addText();
          }}
        >
          <label>
            <span className="small">Title (optional)</span>
            <input value={title} onChange={(e) => setTitle(e.target.value)} maxLength={120} placeholder="What is this text?" />
          </label>
          <label>
            <span className="small">Text</span>
            <textarea rows={7} value={text} onChange={(e) => setText(e.target.value)} placeholder="Paste or type anything you want the bank to know…" />
          </label>
          <div className="web-actions">
            <button type="submit" disabled={text.trim().length < 20}>
              Add to the bank
            </button>
          </div>
        </form>
      )}

      {message && <p className={`notice ${message.kind}`}>{message.text}</p>}

      {tab === "web" && hasJob && (
        <div className="web-progress" aria-live="polite">
          <p>
            <strong>{job.stored ?? 0}</strong> page{job.stored === 1 ? "" : "s"} added · {job.fetched ?? 0} read
            {running && job.current ? <span className="muted small"> · {job.current}</span> : null}
          </p>
          {!running && job.message && <p className={`notice ${job.state === "error" ? "error" : "ok"}`}>{job.message}</p>}
          {job.recent?.length > 0 && (
            <ul className="web-recent small">
              {[...job.recent].reverse().map((r, i) => (
                <li key={`${r.url}-${i}`}>
                  <span className="muted">{r.result}</span> — {r.title || r.url}
                </li>
              ))}
            </ul>
          )}
          {skipped.length > 0 && (
            <ul className="web-skipped small muted">
              {skipped.map(([why, n]) => (
                <li key={why}>
                  {n} skipped: {why}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  );
}
