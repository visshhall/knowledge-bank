/**
 * SetupWizard.jsx — first-time setup inside the app, with buttons and live progress.
 *
 * WHAT:  Three step cards:
 *          1. AI engine  — install (downloads Ollama's official installer and
 *                          opens it) or start Ollama
 *          2. AI models  — download all models, one progress bar per model
 *          3. Benchmark  — pick a folder of PDFs, run, open the report
 * WHY:   The owner wants a normal Windows app: no PowerShell, no commands.
 *        Each step unlocks when the previous one is done.
 * WHEN:  Shown on the Setup screen (SetupScreen in App.jsx), always
 *        reachable from the side rail (e.g. to re-run the benchmark).
 *        While visible it polls GET /setup/status every 1.5 s.
 * CONNECTED TO:
 *        - bridge.js (window.kb) → engine endpoints /setup/* (server.py →
 *          setup_manager.py), the folder dialog, and "open reports folder"
 *        - App.jsx (parent): onStatus(status) on every poll, so the
 *          readiness list can refresh when Ollama starts or setup completes
 */
import { useCallback, useEffect, useState } from "react";
import { formatBytes, kb, percent } from "./bridge.js";

const POLL_MS = 1500;

export default function SetupWizard({ onStatus }) {
  const [status, setStatus] = useState(null);
  const [notice, setNotice] = useState(""); // short message from the last button press
  const [includeExtras, setIncludeExtras] = useState(true);

  /** Load the latest job states from the engine. */
  const poll = useCallback(async () => {
    const s = await kb.get("/setup/status");
    if (!s.error) {
      setStatus(s);
      onStatus?.(s);
    }
  }, [onStatus]);

  // Poll for the whole time the wizard is on screen; stop when it unmounts.
  useEffect(() => {
    poll();
    const id = setInterval(poll, POLL_MS);
    return () => clearInterval(id);
  }, [poll]);

  /** Press a wizard button: POST to the engine, show its reply, refresh. */
  async function act(path, body) {
    setNotice("");
    const r = await kb.post(path, body);
    if (r.error || r.ok === false) setNotice(r.error || r.message);
    poll();
  }

  /** Step 3 button: choose a folder, then start the benchmark on it. */
  async function runBenchmark() {
    const folder = await kb.pickFolder("benchmark");
    if (folder) act("/setup/benchmark/start", { folder });
  }

  if (!status) {
    return <section className="card wizard">Loading setup status…</section>;
  }

  const { ollama, models, benchmark } = status;
  const ollamaJob = ollama.job;
  const modelsJob = models.job;
  const benchJob = benchmark.job;
  const allModelsPresent = models.list.every((m) => m.present);
  const requiredPresent = models.list.filter((m) => m.required).every((m) => m.present);

  return (
    <section className="card wizard" aria-label="Setup steps">
      <div className="section-head">
        <h2>Three steps, once</h2>
        {status.setup_complete && <span className="pill-ok">Ready to use</span>}
      </div>
      {notice && <p className="error-text">{notice}</p>}

      <div className="steps">
        {/* ---------------- Step 1: AI engine ---------------- */}
        <article className={`step ${ollama.running ? "done" : "active"}`}>
          <div className="step-num">1</div>
          <h3>AI engine</h3>
          <p className="muted">
            Ollama runs the AI models privately on your laptop. Nothing is sent online.
          </p>
          {ollama.running ? (
            <p className="ok-text">✓ Running</p>
          ) : ollama.installed ? (
            <button onClick={() => act("/setup/ollama/start")}>Start AI engine</button>
          ) : ["downloading", "installing"].includes(ollamaJob.state) ? (
            <>
              <Progress
                value={percent(ollamaJob.downloaded, ollamaJob.total)}
                label={
                  ollamaJob.state === "downloading"
                    ? `${formatBytes(ollamaJob.downloaded)} of ${formatBytes(ollamaJob.total)}`
                    : "Waiting for the installer to finish"
                }
              />
              <p className="small muted">{ollamaJob.message}</p>
            </>
          ) : (
            <>
              <button onClick={() => act("/setup/ollama/install")}>Install AI engine</button>
              {ollamaJob.state === "error" && <p className="error-text small">{ollamaJob.message}</p>}
            </>
          )}
        </article>

        {/* ---------------- Step 2: models ---------------- */}
        <article
          className={`step ${allModelsPresent ? "done" : ollama.running ? "active" : "locked"}`}
        >
          <div className="step-num">2</div>
          <h3>AI models</h3>
          <ul className="model-list">
            {models.list.map((m) => (
              <li key={m.name}>
                <div className="model-row">
                  <span>
                    {m.name}
                    {!m.required && <span className="muted small"> (comparison)</span>}
                  </span>
                  <span className={m.present ? "ok-text" : "muted"}>
                    {m.present
                      ? "✓"
                      : m.total
                        ? `${percent(m.completed, m.total)}%`
                        : "—"}
                  </span>
                </div>
                {!m.present && m.total > 0 && (
                  <Progress value={percent(m.completed, m.total)} compact />
                )}
              </li>
            ))}
          </ul>
          {!allModelsPresent && ollama.running && modelsJob.state !== "running" && (
            <>
              <label className="check-row">
                <input
                  type="checkbox"
                  checked={includeExtras}
                  onChange={(e) => setIncludeExtras(e.target.checked)}
                />
                Include comparison models for the benchmark (~15 GB total, else ~8 GB)
              </label>
              <button
                onClick={() =>
                  act("/setup/models/pull", { include_benchmark_extras: includeExtras })
                }
              >
                Download AI models
              </button>
            </>
          )}
          {modelsJob.state === "running" && <p className="small muted">{modelsJob.message}</p>}
          {modelsJob.state === "error" && <p className="error-text small">{modelsJob.message}</p>}
        </article>

        {/* ---------------- Step 3: benchmark ---------------- */}
        <article
          className={`step ${benchJob.state === "done" ? "done" : requiredPresent ? "active" : "locked"}`}
        >
          <div className="step-num">3</div>
          <h3>Benchmark</h3>
          <p className="muted">
            Put 5–10 typical PDFs in a folder. The app tests each model on them to pick the
            best ones for your laptop. Your files are only read, never changed.
          </p>
          {benchJob.state === "running" ? (
            <>
              <Progress indeterminate label="Running. This takes 10–40 minutes." />
              <p className="small muted">{benchJob.message}</p>
            </>
          ) : (
            <button onClick={runBenchmark} disabled={!requiredPresent || !ollama.running}>
              {benchJob.state === "done" ? "Run again" : "Choose PDF folder & run"}
            </button>
          )}
          {benchJob.state === "done" && (
            <>
              <p className="ok-text small">{benchJob.message}</p>
              <button className="secondary" onClick={() => kb.openReports()}>
                Open report folder
              </button>
            </>
          )}
          {benchJob.state === "error" && <p className="error-text small">{benchJob.message}</p>}
        </article>
      </div>
    </section>
  );
}

/**
 * Animated progress bar.
 *  value          0–100 (ignored when indeterminate)
 *  indeterminate  sliding animation when the end isn't known
 *  compact        thin variant used inside the model list
 */
function Progress({ value = 0, label, indeterminate = false, compact = false }) {
  return (
    <div className={`progress ${compact ? "compact" : ""}`}>
      <div className="progress-track">
        <div
          className={`progress-fill ${indeterminate ? "indeterminate" : ""}`}
          style={indeterminate ? undefined : { width: `${value}%` }}
        />
      </div>
      {label && <div className="progress-label small muted">{label}</div>}
    </div>
  );
}
