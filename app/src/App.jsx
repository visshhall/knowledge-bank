/**
 * App.jsx — the Phase 0 interface: engine status + readiness dashboard.
 *
 * WHAT:  Shows, over the animated Constellation background:
 *          1. Engine status (starting → ready, or a clear error message)
 *          2. Knowledge bank totals (sources, pages, passages, topics,
 *             coverage %) — all zero until Phase 1 imports PDFs
 *          3. System readiness checks (GPU, RAM, disk, Ollama, models) with
 *             the exact fix for anything not OK
 * WHY:   Phase 0's goal is proving that every part connects: window →
 *        main process → Python engine → database/Ollama. This screen makes
 *        that visible and doubles as a troubleshooting page later.
 * WHEN:  Rendered once at launch (by main.jsx); reloads data when the engine
 *        becomes ready and when "Re-check" is pressed.
 * CONNECTED TO:
 *        - window.kb (electron/preload.cjs) → engine endpoints /stats, /system
 *        - Constellation.jsx (background), styles.css (look)
 *        Phases 4+ replace this screen's centre with the Knowledge Map; the
 *        readiness panel will move to a Settings/Diagnostics page.
 */
import { useCallback, useEffect, useState } from "react";
import Constellation from "./Constellation.jsx";

/** Labels for the totals row, in display order. Keys match engine db.stats(). */
const STAT_TILES = [
  ["sources", "Sources"],
  ["pages", "Pages"],
  ["passages", "Passages"],
  ["topics", "Topics"],
  ["coverage_percent", "Coverage %"],
];

/**
 * Safe access to the preload bridge. If the page is opened outside Electron
 * (e.g. in a normal browser during design work), window.kb doesn't exist —
 * return a stub so the screen still renders and explains why.
 */
const kb =
  window.kb ?? {
    get: async () => ({ error: "Not running inside the Knowledge Bank app" }),
    engineStatus: async () => ({ status: "error", detail: "Not running inside the app" }),
    onEngineStatus: () => () => {},
  };

export default function App() {
  const [engine, setEngine] = useState({ status: "starting", detail: "" });
  const [stats, setStats] = useState(null);
  const [system, setSystem] = useState(null);
  const [loading, setLoading] = useState(false);

  /** Fetch totals and readiness from the engine (both in parallel). */
  const refresh = useCallback(async () => {
    setLoading(true);
    const [s, sys] = await Promise.all([kb.get("/stats"), kb.get("/system")]);
    setStats(s);
    setSystem(sys);
    setLoading(false);
  }, []);

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
            <p className="muted">
              If this is the first run, open PowerShell in the project folder and run
              <code> setup\setup.ps1</code>.
            </p>
          </section>
        )}

        {engine.status === "ready" && (
          <>
            <section className="hero">
              <h1>Your knowledge bank is ready to be built.</h1>
              <p className="muted">
                Phase 0 foundation is running. Importing PDFs arrives in Phase 1 — then this
                space becomes your animated Knowledge Map.
              </p>
            </section>

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
