/**
 * Updates.jsx — "AI updates" card on the Setup screen.
 *
 * WHAT:  A "Check for updates" button that asks the engine to compare:
 *          - the installed Ollama version with the latest official release
 *          - each AI model on this laptop with the version currently
 *            published (by exact fingerprint, not by date)
 *        Results show as a list with a status for each: Up to date /
 *        Update available / Couldn't check / Not downloaded, plus an Update
 *        button where needed. Model updates show download progress.
 * WHY:   The owner asked how he'd know whether the AI engine and models are
 *        old or new. This answers it in one click, without the app ever
 *        going online by itself.
 * WHEN:  Rendered by SetupScreen in App.jsx. The check runs only when the
 *        button is pressed; status refreshes every 2 s while visible (to
 *        follow download progress).
 * CONNECTED TO: bridge.js → engine POST /updates/check, GET /updates/status,
 *        POST /updates/model, POST /updates/ollama (server.py → updates.py).
 */
import { useState } from "react";
import Icon from "./icons.jsx";
import { kb, usePoll } from "./bridge.js";

const STATE_TEXT = {
  up_to_date: "Up to date",
  update_available: "Update available",
  unknown: "Couldn't check",
  not_installed: "Not downloaded",
};

export default function Updates() {
  const [status, reload] = usePoll("/updates/status", 2000);
  const [checking, setChecking] = useState(false);
  const [notice, setNotice] = useState("");

  async function check() {
    setChecking(true);
    setNotice("");
    const r = await kb.post("/updates/check", {});
    if (r.error) setNotice(r.error);
    await reload();
    setChecking(false);
  }

  async function act(path, body) {
    const r = await kb.post(path, body);
    setNotice(r.message || r.error || "");
    reload();
  }

  const downloading = status?.downloads?.state === "running";
  const result = status?.checked_at ? status : null;

  return (
    <section className="card updates" aria-label="AI updates">
      <div className="section-head">
        <div>
          <h2>AI updates</h2>
          <p className="muted small">
            {result ? `Last checked ${result.checked_at}.` : "Not checked yet."} Checking goes online and sends only
            model names, never your documents.
          </p>
        </div>
        <button className="secondary" onClick={check} disabled={checking}>
          <Icon name="refresh" size={16} />
          {checking ? "Checking…" : "Check for updates"}
        </button>
      </div>

      {result?.error && <p className="notice error">{result.error}</p>}
      {notice && <p className="notice ok">{notice}</p>}

      {result && !result.error && (
        <ul className="update-list">
          {result.ollama && (
            <li>
              <div>
                <p className="update-name">AI engine (Ollama)</p>
                <p className="small muted">
                  Installed {result.ollama.installed || "—"}
                  {result.ollama.latest ? `, latest ${result.ollama.latest}` : ""}
                </p>
              </div>
              <span className={`state state-${result.ollama.state}`}>{STATE_TEXT[result.ollama.state]}</span>
              {result.ollama.state === "update_available" && (
                <button onClick={() => act("/updates/ollama", {})}>Update</button>
              )}
            </li>
          )}
          {result.models.map((m) => (
            <li key={m.name}>
              <div>
                <p className="update-name">{m.name}</p>
                {m.local_digest && (
                  <p className="small muted">
                    Yours {m.local_digest}
                    {m.remote_digest && m.remote_digest !== m.local_digest ? `, newest ${m.remote_digest}` : ""}
                  </p>
                )}
              </div>
              <span className={`state state-${m.state}`}>{STATE_TEXT[m.state]}</span>
              {m.state === "update_available" && (
                <button onClick={() => act("/updates/model", { name: m.name })} disabled={downloading}>
                  Update
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
      {downloading && <p className="small muted">{status.downloads.message}</p>}
      <p className="small muted foot-note">
        Ollama on Windows can also update itself from its icon near the clock. Articles already written stay as
        they are after a model update.
      </p>
    </section>
  );
}
