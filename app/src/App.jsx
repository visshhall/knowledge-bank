/**
 * App.jsx — the home screen: engine status, setup wizard, totals, readiness.
 *
 * WHAT:  Shows, over the animated Constellation background:
 *          1. Engine status (starting → ready, or a clear error message)
 *          2. Setup wizard (AI engine, models, benchmark) — see SetupWizard.jsx
 *          3. Knowledge bank totals (sources, pages, passages, topics,
 *             coverage %) — all zero until Phase 1 imports PDFs
 *          4. System readiness checks (GPU, RAM, disk, Ollama, models) with
 *             the exact fix for anything not OK
 * WHY:   Phase 0's goal is proving every part connects (window → main
 *        process → Python engine → database/Ollama) and letting the owner
 *        finish setup entirely inside the app.
 * WHEN:  Rendered once at launch (by main.jsx); reloads data when the engine
 *        becomes ready, when "Re-check" is pressed, and when the wizard
 *        reports that setup just completed.
 * CONNECTED TO:
 *        - bridge.js (window.kb) → engine endpoints /stats, /system
 *        - SetupWizard.jsx, Constellation.jsx, styles.css
 *        In Phase 4 this screen's centre becomes the Knowledge Map; the
 *        wizard and readiness panel move to a Settings/Diagnostics page.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import Constellation from "./Constellation.jsx";
import SetupWizard from "./SetupWizard.jsx";
import { kb } from "./bridge.js";

/** Labels for the totals row, in display order. Keys match engine db.stats(). */
const STAT_TILES = [
  ["sources", "Sources"],
  ["pages", "Pages"],
  ["passages", "Passages"],
  ["topics", "Topics"],
  ["coverage_percent", "Coverage %"],
];

export default function App() {
  const [engine, setEngine] = useState({ status: "starting", detail: "" });
  const [stats, setStats] = useState(null);
  const [system, setSystem] = useState(null);
  const [loading, setLoading] = useState(false);
  const lastSetup = useRef(null); // last known {complete, ollamaRunning} from the wizard

  /** Fetch totals and readiness from the engine (both in parallel). */
  const refresh = useCallback(async () => {
    setLoading(true);
    const [s, sys] = await Promise.all([kb.get("/stats"), kb.get("/system")]);
    setStats(s);
    setSystem(sys);
    setLoading(false);
  }, []);

  /**
   * Called by the wizard on every poll. Refreshes the readiness list
   * automatically whenever something it reports changes:
   *   - the AI engine (Ollama) starts or stops, or
   *   - setup flips from incomplete to complete (last model downloaded).
   * Fix in v0.2.1: before, only the second case refreshed, so the list could
   * still say "Ollama not answering" after the wizard showed it running.
   */
  const handleSetupStatus = useCallback(
    (s) => {
      const now = { complete: s.setup_complete, ollamaRunning: s.ollama.running };
      const prev = lastSetup.current;
      if (prev && (prev.ollamaRunning !== now.ollamaRunning || (!prev.complete && now.complete))) {
        refresh();
      }
      lastSetup.current = now;
    },
    [refresh]
  );

  // On mount: read the current engine status and subscribe to changes.
  useEffect(() => {
    kb.engineStatus().then(setEngine);
    return kb.onEngineStatus(setEngine); // returns the unsubscribe function
  }, []);

  // Whenever the engine becomes ready, load the dashboard data.
  useEffect(() => {
    if (engine.status === "ready") refresh();
  }, [engine.status, refresh]);

  return (
    <div className="app">
      <Constellation />

      <header className="topbar">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true" />
          <span>Knowledge Bank</span>
        </div>
        <EngineBadge engine={engine} />
      </header>

      <main className="content">
        {engine.status === "starting" && (
          <section className="center-card">
            <div className="orb" aria-hidden="true" />
            <h1>Starting the engine…</h1>
            <p className="muted">Preparing the database and checking your system.</p>
          </section>
        )}

        {engine.status === "error" && (
          <section className="center-card error">
            <h1>Engine problem</h1>
            <p>{engine.detail}</p>
            <p className="muted">Close and reopen the app. If it persists, reinstall it.</p>
          </section>
        )}

        {engine.status === "ready" && (
          <>
            <section className="hero">
              <h1>Your knowledge bank is ready to be built.</h1>
              <p className="muted">
                Finish the setup below. Importing PDFs arrives in the next update — then this
                space becomes your animated Knowledge Map.
              </p>
            </section>

            <SetupWizard onStatus={handleSetupStatus} />

            <section className="tiles" aria-label="Knowledge bank totals">
              {STAT_TILES.map(([key, label]) => (
                <div className="tile" key={key}>
                  <div className="tile-value">{stats && !stats.error ? stats[key] : "—"}</div>
                  <div className="tile-label">{label}</div>
                </div>
              ))}
            </section>

            <section className="panel">
              <div className="panel-head">
                <h2>System readiness</h2>
                <button onClick={refresh} disabled={loading}>
                  {loading ? "Checking…" : "Re-check"}
                </button>
              </div>
              {system?.error && <p className="error-text">{system.error}</p>}
              {system?.checks && (
                <ul className="checks">
                  {system.checks.map((c) => (
                    <li key={c.name} className={c.ok ? "ok" : "fix"}>
                      <span className="dot" aria-hidden="true" />
                      <div>
                        <div className="check-name">
                          {c.name} <span className="muted">— {c.detail}</span>
                        </div>
                        {c.fix && <div className="check-fix">{c.fix}</div>}
                      </div>
                    </li>
                  ))}
                </ul>
              )}
              {system?.data_dir && (
                <p className="muted small">Data folder: {system.data_dir}</p>
              )}
            </section>
          </>
        )}
      </main>
    </div>
  );
}

/** Small pill in the top bar: green "ready", amber "starting", red "error". */
function EngineBadge({ engine }) {
  const label = { starting: "Starting", ready: "Engine ready", error: "Engine error" }[
    engine.status
  ];
  return (
    <span className={`badge badge-${engine.status}`} title={engine.detail}>
      <span className="badge-dot" aria-hidden="true" />
      {label}
    </span>
  );
}
