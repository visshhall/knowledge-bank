/**
 * Library.jsx — Phase 1 screen: add files, watch folders, search, manage.
 *
 * WHAT:  1. Drop zone + "Add files" / "Add folder" buttons
 *        2. Live import progress (file, page x of y, files left)
 *        3. Instant search across every imported passage, with the file and
 *           page of each match and the matched words highlighted
 *        4. Watched folders: new files appearing there import automatically
 *        5. The file list: status, pages, passages, OCR'd pages, pictures,
 *           duplicate copies found; remove a file; retry failed ones
 * WHY:   Import is the foundation of the bank; the owner needs to see what
 *        went in, what was skipped as a duplicate, what failed and why —
 *        and to find things straight away.
 * WHEN:  When the owner opens "Library" in the side rail. Polls import
 *        progress every 1.5 s and the file list every 4 s while visible.
 * CONNECTED TO: bridge.js → engine /library, /library/add, /library/remove,
 *        /library/retry, /import/status, /settings/watch, /search
 *        (server.py → importer.py, search.py). ImportProgress is also used
 *        by Overview.jsx. icons.jsx for button and drop-zone icons.
 */
import { useEffect, useState } from "react";
import Icon from "./icons.jsx";
import { formatBytes, formatCount, kb, percent, usePoll } from "./bridge.js";

/** Human wording for each source status (matches db.py's allowed values). */
const STATUS_TEXT = {
  pending: "Waiting",
  extracting: "Reading…",
  extracted: "In the bank",
  failed: "Failed",
  set_aside: "Not cybersecurity", // v0.8.2: set aside by the relevance check
};

export default function Library() {
  const [lib, reloadLib] = usePoll("/library", 4000);
  const [imp, reloadImp] = usePoll("/import/status", 1500);
  const [notice, setNotice] = useState(null); // {kind: "ok"|"error", text}
  const [dragging, setDragging] = useState(false);

  /**
   * Send chosen/dropped paths to the engine and explain the outcome in one
   * sentence (added / duplicates / already in / unsupported / errors).
   */
  async function addPaths(paths) {
    if (!paths?.length) return;
    setNotice({ kind: "ok", text: "Checking files…" });
    const r = await kb.post("/library/add", { paths });
    if (r.error) {
      setNotice({ kind: "error", text: r.error });
      return;
    }
    const parts = [];
    parts.push(`${r.added} new file${r.added === 1 ? "" : "s"} added`);
    if (r.duplicates) parts.push(`${r.duplicates} exact cop${r.duplicates === 1 ? "y" : "ies"} skipped`);
    if (r.already_in_bank) parts.push(`${r.already_in_bank} already in the bank`);
    if (r.removed_before)
      parts.push(
        `${r.removed_before} you removed before (skipped — pick the file itself with Add files to bring it back)`
      );
    if (r.unsupported) parts.push(`${r.unsupported} not a PDF, image or spreadsheet (ignored)`);
    if (r.errors?.length) parts.push(`${r.errors.length} couldn't be opened: ${r.errors.slice(0, 2).join("; ")}`);
    setNotice({ kind: r.errors?.length ? "error" : "ok", text: parts.join(" · ") + "." });
    reloadLib();
    reloadImp();
  }

  /** Drag-and-drop: turn dropped File objects into disk paths via the bridge. */
  function onDrop(e) {
    e.preventDefault();
    setDragging(false);
    const paths = [...e.dataTransfer.files].map((f) => kb.pathForFile(f)).filter(Boolean);
    addPaths(paths);
  }

  async function removeSource(source) {
    const r = await kb.post("/library/remove", { source_id: source.id });
    setNotice({ kind: r.ok ? "ok" : "error", text: r.message || r.error });
    reloadLib();
  }

  /** v0.8.2: import a file the relevance check set aside. */
  async function keepAnyway(source) {
    const r = await kb.post("/library/keep", { source_id: source.id });
    setNotice({ kind: r.ok ? "ok" : "error", text: r.ok ? `${source.file_name}: ${r.message}` : r.message || r.error });
    reloadLib();
    reloadImp();
  }

  async function retryFailed() {
    const r = await kb.post("/library/retry", {});
    setNotice({ kind: r.error ? "error" : "ok", text: r.message || r.error });
    reloadLib();
  }

  const sources = lib?.sources ?? [];
  const failed = sources.filter((s) => s.status === "failed").length;
  const setAside = sources.filter((s) => s.status === "set_aside").length;

  return (
    <div className="library">
      <header className="page-head">
        <h1>Library</h1>
        <p className="lede">
          Add PDFs, screenshots, diagrams and spreadsheets (Excel or CSV). Your original files are only read — never moved,
          changed or copied.
        </p>
      </header>

      <section
        className={`card dropzone ${dragging ? "dragging" : ""}`}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        aria-label="Add files"
      >
        <span className="drop-icon" aria-hidden="true">
          <Icon name="upload" size={26} />
        </span>
        <p className="drop-title">Drop PDFs, images, spreadsheets or whole folders here</p>
        <div className="actions">
          <button className="primary" onClick={async () => addPaths(await kb.pickFiles())}>
            <Icon name="file" size={18} />
            Add files
          </button>
          <button
            className="secondary"
            onClick={async () => {
              const folder = await kb.pickFolder("import");
              if (folder) addPaths([folder]);
            }}
          >
            <Icon name="folder" size={18} />
            Add a folder
          </button>
        </div>
        {notice && <p className={`notice ${notice.kind}`}>{notice.text}</p>}
      </section>

      {imp?.state === "running" && <ImportProgress status={imp} />}
      {imp?.last_error && imp.state !== "running" && (
        <p className="notice error">Last problem: {imp.last_error}</p>
      )}
      {imp?.ocr_error && (
        <p className="notice error">
          Scanned pages and pictures can't be read right now ({imp.ocr_error}). Normal PDF text
          is still imported.
        </p>
      )}

      <SearchPanel hasData={sources.some((s) => s.passages > 0)} />

      <WatchedFolders />

      <section className="card file-list" aria-label="Files in the bank">
        <div className="section-head">
          <h2>
            Files <span className="count">{formatCount(sources.length)}</span>
          </h2>
          <RelevanceSwitch setAside={setAside} />
          {failed > 0 && (
            <button className="secondary" onClick={retryFailed}>
              <Icon name="refresh" size={16} />
              Retry {failed} failed
            </button>
          )}
        </div>
        {sources.length === 0 ? (
          <p className="muted">No files yet. Add some above to start building the bank.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>File</th>
                <th>Status</th>
                <th className="num">Pages</th>
                <th className="num">Passages</th>
                <th className="num">Scanned</th>
                <th className="num">Pictures</th>
                <th className="num">Copies skipped</th>
                <th aria-label="Actions" />
              </tr>
            </thead>
            <tbody>
              {sources.map((s) => (
                <tr key={s.id} className={`st-${s.status}`}>
                  <td className="file-cell" title={s.original_path}>
                    <span className="file-name">{s.file_name}</span>
                    <span className="file-meta">{formatBytes(s.size_bytes)}</span>
                    {s.error && <span className="file-error">{s.error}</span>}
                    {s.status === "failed" && /password/i.test(s.error ?? "") && <Unlock source={s} />}
                    {s.status === "set_aside" && (
                      <span className="aside-note">
                        Set aside: {s.relevance?.reason ?? "not about cybersecurity"}.{" "}
                        <button className="link" onClick={() => keepAnyway(s)}>
                          Keep anyway
                        </button>
                      </span>
                    )}
                  </td>
                  <td>
                    <span className={`status status-${s.status}`}>{STATUS_TEXT[s.status]}</span>
                  </td>
                  <td className="num">{s.page_count ?? "—"}</td>
                  <td className="num">{formatCount(s.passages)}</td>
                  <td className="num">{s.ocr_pages || "—"}</td>
                  <td className="num">
                    {s.images || "—"}
                    {s.pictures_waiting > 0 && (
                      <span className="file-meta" title="Pictures waiting to be read">
                        {" "}· {s.pictures_waiting} to read
                      </span>
                    )}
                  </td>
                  <td className="num">{s.duplicate_copies || "—"}</td>
                  <td>
                    <button
                      className="link"
                      onClick={() => removeSource(s)}
                      disabled={s.status === "extracting"}
                      title="Remove from the bank (the original file stays where it is)"
                    >
                      Remove
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}

/**
 * v0.8.2 switch: "Only keep cybersecurity files". When on (the default),
 * each new file is checked on a sample of its text BEFORE the slow work, and
 * files not about security are set aside (shown in the list with the reason
 * and a "Keep anyway" button). Turning it off only affects new files.
 */
function RelevanceSwitch({ setAside }) {
  const [on, setOn] = useState(null);
  useEffect(() => {
    kb.get("/library/filter").then((r) => !r.error && setOn(r.on));
  }, []);
  if (on === null) return null;
  async function toggle() {
    const r = await kb.post("/library/filter", { on: !on });
    if (!r.error) setOn(r.on);
  }
  return (
    <label className="relevance-switch" title="Files that aren't about cybersecurity are set aside, not deleted">
      <input type="checkbox" checked={on} onChange={toggle} />
      <span>
        Only keep cybersecurity files
        {setAside > 0 && <span className="muted"> · {setAside} set aside</span>}
      </span>
    </label>
  );
}

/**
 * Live progress of the running import. Exported so the Overview screen
 * shows the same panel.
 * v0.8.1: two phases. "Reading files" (text — each file is usable as soon
 * as it finishes) and then "Reading pictures" (diagrams and screenshots
 * inside the files, added to the same pages afterwards). Also says whether
 * OCR runs on the graphics card or the processor.
 */
export function ImportProgress({ status }) {
  const pictures = status.phase === "pictures";
  const done = status.pictures_done || 0;
  const total = done + (status.pictures_left || 0);
  const pageText = pictures
    ? `picture on page ${formatCount(status.current_page)}`
    : status.page_count
      ? `page ${formatCount(status.current_page)} of ${formatCount(status.page_count)}`
      : "starting";
  const device =
    status.ocr_device === "graphics card" || status.ocr_device === "processor"
      ? `Scans and pictures are read on the ${status.ocr_device}.`
      : null;
  return (
    <section className="card import-progress" aria-live="polite">
      <div className="section-head">
        <h2>{pictures ? "Reading pictures" : "Reading files"}</h2>
        <span className="muted">
          {pictures
            ? `${formatCount(status.pictures_left)} picture${status.pictures_left === 1 ? "" : "s"} left`
            : `${status.files_queued} file${status.files_queued === 1 ? "" : "s"} left`}
        </span>
      </div>
      <p className="current-file">
        {status.current_file} <span className="muted">— {pageText}</span>
      </p>
      <div className="progress-track">
        <div
          className="progress-fill"
          style={{ width: `${pictures ? percent(done, total) : percent(status.current_page, status.page_count)}%` }}
        />
      </div>
      <p className="small muted">
        {pictures
          ? "Your files are already searchable. Text found in their diagrams and screenshots is being added now."
          : "Each file can be searched as soon as its text is in. Pictures inside the files are read afterwards."}
        {device ? ` ${device}` : ""}
      </p>
    </section>
  );
}

/**
 * Search box + results. Waits 250 ms after the last keystroke before
 * searching (no request per letter). Matches are highlighted using the
 * engine's marker characters, split into <mark> elements — no raw HTML.
 */
function SearchPanel({ hasData }) {
  const [q, setQ] = useState("");
  const [res, setRes] = useState(null);

  useEffect(() => {
    if (!q.trim()) {
      setRes(null);
      return undefined;
    }
    const id = setTimeout(async () => {
      const r = await kb.get("/search", { q });
      if (!r.error) setRes(r);
    }, 250);
    return () => clearTimeout(id);
  }, [q]);

  return (
    <section className="card search" aria-label="Search">
      <label className="search-label" htmlFor="kb-search">
        Search every page
      </label>
      <div className="search-field">
        <Icon name="search" size={20} />
        <input
          id="kb-search"
          type="search"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder={hasData ? "Try 4625, SigninLogs, lateral movement…" : "Search becomes available once files are imported"}
          disabled={!hasData}
          autoComplete="off"
          spellCheck="false"
        />
      </div>
      {res && (
        <div className="results">
          <p className="muted small">
            {res.total === 0
              ? "No passage contains all of these words."
              : `${formatCount(res.total)} passage${res.total === 1 ? "" : "s"} — showing the best ${res.results.length}`}
          </p>
          <ol>
            {res.results.map((r) => (
              <li key={r.passage_id}>
                <p className="where">
                  {r.file_name} <span className="muted">· page {r.page_number}</span>
                </p>
                <p className="snippet">
                  <Highlighted text={r.snippet} />
                </p>
              </li>
            ))}
          </ol>
        </div>
      )}
    </section>
  );
}

/** Turn "\u0002match\u0003" markers from search.py into <mark> elements. */
function Highlighted({ text }) {
  const parts = text.split(/(\u0002[^\u0003]*\u0003)/g);
  return parts.map((part, i) =>
    part.startsWith("\u0002") ? <mark key={i}>{part.slice(1, -1)}</mark> : <span key={i}>{part}</span>
  );
}

/** Watched folders: list, add (folder dialog), stop watching. */
function WatchedFolders() {
  const [data, reload] = usePoll("/settings/watch", 0);
  const [msg, setMsg] = useState("");
  const folders = data?.folders ?? [];

  async function save(next) {
    const r = await kb.post("/settings/watch", { folders: next });
    setMsg(r.message || r.error || "");
    reload();
  }

  return (
    <section className="card watched" aria-label="Watched folders">
      <div className="section-head">
        <h2>Watched folders</h2>
        <button
          className="secondary"
          onClick={async () => {
            const f = await kb.pickFolder("watch");
            if (f) save([...folders, f]);
          }}
        >
          <Icon name="eye" size={16} />
          Watch a folder
        </button>
      </div>
      <p className="muted small">
        New PDFs, images and spreadsheets saved in these folders are imported automatically every few minutes.
      </p>
      {folders.length > 0 && (
        <ul className="folder-list">
          {folders.map((f) => (
            <li key={f}>
              <span>{f}</span>
              <button className="link" onClick={() => save(folders.filter((x) => x !== f))}>
                Stop watching
              </button>
            </li>
          ))}
        </ul>
      )}
      {msg && <p className="notice ok">{msg}</p>}
    </section>
  );
}

/**
 * "Enter password" for a password-protected PDF (v0.7). The password goes
 * to the engine once (POST /library/password), is used to read that file,
 * then forgotten — it is never saved.
 */
function Unlock({ source }) {
  const [open, setOpen] = useState(false);
  const [pw, setPw] = useState("");
  const [msg, setMsg] = useState("");
  async function submit(e) {
    e.preventDefault();
    const r = await kb.post("/library/password", { source_id: source.id, password: pw });
    setMsg(r.message || r.error || "");
    if (r.ok) {
      setPw("");
      setOpen(false);
    }
  }
  if (!open) {
    return (
      <button className="link small unlock-link" onClick={() => setOpen(true)}>
        <Icon name="lock" size={13} /> Enter password
      </button>
    );
  }
  return (
    <form className="unlock-form" onSubmit={submit}>
      <input type="password" value={pw} onChange={(e) => setPw(e.target.value)} placeholder="PDF password" autoFocus aria-label={`Password for ${source.file_name}`} />
      <button type="submit" className="small-btn" disabled={!pw}>
        Open
      </button>
      <button type="button" className="ghost small-btn" onClick={() => setOpen(false)}>
        Cancel
      </button>
      {msg && <span className="small muted">{msg}</span>}
      <span className="small muted">Used once to read this file; never saved.</span>
    </form>
  );
}
