/**
 * StorageCard.jsx — "Storage" card on the Setup screen (v0.9).
 *
 * WHAT:  How much disk space the knowledge bank uses and what is inside it
 *        (files, pages, passages, topics; text vs. meaning-vectors), how much
 *        a clean-up would free, and a "Clean up" button.
 * WHY:   Owner chose "built to stay fast with a big library — show how much
 *        disk space the bank uses, with a clean-up button" (15 Nov 2026).
 *        The bank file never shrinks by itself after files are removed or set
 *        aside; the clean-up compacts it (engine storage.py).
 * WHEN:  Rendered by SetupScreen in App.jsx; refreshes every 5 s (every
 *        second while a clean-up runs).
 * CONNECTED TO: bridge.js → engine GET /storage, POST /storage/cleanup
 *        (server.py → storage.py).
 */
import { useEffect, useState } from "react";
import Icon from "./icons.jsx";
import { formatCount, kb, usePoll } from "./bridge.js";

const mb = (v) => (v >= 1024 ? `${(v / 1024).toFixed(1)} GB` : `${v} MB`);

export default function StorageCard() {
  const [running, setRunning] = useState(false);
  const [data, reload] = usePoll("/storage", running ? 1000 : 5000);
  const [notice, setNotice] = useState("");
  const job = data?.job;
  const busy = running || job?.state === "running";
  useEffect(() => {
    if (running && job && job.state !== "running") setRunning(false);
  }, [running, job]);

  async function clean() {
    const r = await kb.post("/storage/cleanup", {});
    setNotice(r.ok ? "" : r.message || r.error || "");
    if (r.ok) setRunning(true);
    reload();
  }

  return (
    <section className="card updates storage-card" aria-label="Storage">
      <div className="section-head">
        <div>
          <h2>Storage</h2>
          <p className="muted small">
            {data ? `The bank uses ${mb(data.total_mb)} in ${data.folder}.` : "Measuring…"} Your original documents
            are not counted and never touched.
          </p>
        </div>
        <button className="secondary" onClick={clean} disabled={busy || !data}>
          <Icon name="refresh" size={16} />
          {busy ? "Cleaning up…" : "Clean up"}
        </button>
      </div>
      {notice && <p className="notice error">{notice}</p>}
      {job?.message && <p className={`notice ${job.state === "error" ? "error" : "ok"}`}>{job.message}</p>}
      {data && (
        <ul className="update-list">
          <li>
            <div>
              <p className="update-name">What's inside</p>
              <p className="small muted">
                {formatCount(data.counts.files)} files · {formatCount(data.counts.pages)} pages ·{" "}
                {formatCount(data.counts.passages)} passages · {formatCount(data.counts.topics)} topics
                {data.counts.set_aside ? ` · ${formatCount(data.counts.set_aside)} set aside` : ""}
              </p>
            </div>
          </li>
          <li>
            <div>
              <p className="update-name">Where the space goes</p>
              <p className="small muted">
                Meaning search {mb(data.parts_mb.meaning_vectors)} · passages {mb(data.parts_mb.passages)} · page
                text {mb(data.parts_mb.page_text)} · articles {mb(data.parts_mb.articles)}
                {data.files_mb.restore_copies ? ` · copies kept by restores ${mb(data.files_mb.restore_copies)}` : ""}
                {data.files_mb.reports ? ` · reports ${mb(data.files_mb.reports)}` : ""}
              </p>
            </div>
          </li>
          <li>
            <div>
              <p className="update-name">Clean-up would free about {mb(data.reclaimable_mb)}</p>
              <p className="small muted">
                Compacts the bank, tidies the search index and removes leftovers, restore copies and reports older
                than 30 days. Nothing you use is removed.
              </p>
            </div>
          </li>
        </ul>
      )}
    </section>
  );
}
