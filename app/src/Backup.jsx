/**
 * Backup.jsx — Setup card: password-encrypted backup and restore (Phase 7).
 *
 * WHAT:  - "Back up now": choose where to save (Windows save dialog), type a
 *          password twice, and the engine writes one encrypted .kbbackup file
 *          with everything in the bank (topics, articles, lessons, flashcard
 *          progress, answers, settings). Shows progress and the last backup.
 *        - "Restore": choose a .kbbackup file and its password; the engine
 *          decrypts and checks it, then "Restart now" switches to it. The
 *          bank it replaces is kept in the data folder, just in case.
 *        - Clear warnings: the password is never stored, so a lost password
 *          means a backup can't be opened; original PDFs and AI models are
 *          not inside the backup.
 * WHY:   Months of overnight writing and study progress shouldn't depend on
 *        one laptop; an encrypted file is safe on a USB drive or in the cloud.
 * WHEN:  Setup screen (App.jsx → SetupScreen).
 * CONNECTED TO: bridge.js (kb.saveBackupDialog, kb.pickBackupDialog,
 *        kb.restart; POST /backup/create, POST /backup/restore,
 *        GET /backup/status → backup.py); styles.css (.backup-*).
 */
import { useState } from "react";
import Icon from "./icons.jsx";
import { formatBytes, kb, usePoll } from "./bridge.js";

export default function Backup() {
  const [status, reload] = usePoll("/backup/status", 1200);
  const [mode, setMode] = useState(null); // null | {kind: "create"|"restore", path}
  const [pw, setPw] = useState("");
  const [pw2, setPw2] = useState("");
  const [notice, setNotice] = useState("");

  async function begin(kind) {
    setNotice("");
    const path = kind === "create" ? await kb.saveBackupDialog() : await kb.pickBackupDialog();
    if (path) {
      setPw("");
      setPw2("");
      setMode({ kind, path });
    }
  }

  async function go(e) {
    e.preventDefault();
    if (mode.kind === "create" && pw !== pw2) return setNotice("The two passwords don't match.");
    const r = await kb.post(mode.kind === "create" ? "/backup/create" : "/backup/restore", { path: mode.path, password: pw });
    if (r.error || r.ok === false) return setNotice(r.error || r.message);
    setMode(null);
    setPw("");
    setPw2("");
    reload();
  }

  const running = status?.state === "running";
  const last = status?.last_backup;

  return (
    <section className="card backup" aria-label="Backup and restore">
      <div className="section-head">
        <h2>
          <Icon name="lock" size={18} /> Backup &amp; restore
        </h2>
        <div className="backup-actions">
          <button onClick={() => begin("create")} disabled={running}>
            Back up now
          </button>
          <button className="secondary" onClick={() => begin("restore")} disabled={running}>
            Restore…
          </button>
        </div>
      </div>
      <p className="muted small">
        {last
          ? `Last backup ${last.at} · ${formatBytes(last.bytes)} · ${last.file}`
          : "No backup yet. One encrypted file holds your whole bank: topics, articles, lessons, flashcard progress and answers."}
      </p>

      {mode && (
        <form className="backup-form" onSubmit={go}>
          <p className="small">
            {mode.kind === "create" ? "Save to" : "Restore from"} <strong>{mode.path}</strong>
          </p>
          <label>
            Password
            <input type="password" value={pw} onChange={(e) => setPw(e.target.value)} autoFocus autoComplete="new-password" />
          </label>
          {mode.kind === "create" && (
            <label>
              Repeat password
              <input type="password" value={pw2} onChange={(e) => setPw2(e.target.value)} autoComplete="new-password" />
            </label>
          )}
          <p className="small backup-warn">
            {mode.kind === "create"
              ? "The password is never saved anywhere. Without it this backup can't be opened by anyone — including you. Your original PDFs and the AI models are not inside the backup."
              : "Your current bank will be set aside (kept in the data folder) and replaced by this backup after a restart."}
          </p>
          <div className="backup-actions">
            <button type="submit" disabled={pw.length < 8}>
              {mode.kind === "create" ? "Encrypt and save" : "Check and restore"}
            </button>
            <button type="button" className="ghost" onClick={() => setMode(null)}>
              Cancel
            </button>
          </div>
        </form>
      )}

      {running && (
        <div className="backup-run" aria-live="polite">
          <span className="qs-spin" aria-hidden="true" /> {status.stage}
        </div>
      )}
      {status?.state === "done" && status.message && <p className="notice ok">{status.message}</p>}
      {status?.state === "error" && <p className="notice error">{status.message}</p>}
      {status?.restore_pending && (
        <div className="notice restart-row">
          A checked backup is ready to switch to.
          <button onClick={() => kb.restart()}>Restart now</button>
        </div>
      )}
      {notice && <p className="notice error">{notice}</p>}
    </section>
  );
}
