/**
 * App.jsx — the app's frame: side rail, engine status, and the screens.
 *
 * WHAT:  - Side rail with the screens that exist so far: Overview, Library,
 *          Setup (more appear as phases are built: Map, Learn…)
 *        - Engine status at the foot of the rail (starting / ready / problem)
 *        - Shows the chosen screen once the engine is ready; a "starting"
 *          or "problem" panel before that
 *        - SetupScreen (below): the setup wizard + system readiness checks
 * WHY:   Phase 1 added a second real screen (Library), so the app needs
 *        simple navigation. A side rail keeps every screen one click away
 *        and leaves the full width for content like tables and search.
 * WHEN:  Rendered once at launch by main.jsx; lives for the whole session.
 * CONNECTED TO: Overview.jsx, Library.jsx, SetupWizard.jsx, bridge.js
 *        (engine status, /system), styles.css.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import Overview from "./Overview.jsx";
import Library from "./Library.jsx";
import SetupWizard from "./SetupWizard.jsx";
import { kb } from "./bridge.js";

/** Screens in the side rail, in order. `id` is used for navigation. */
const SCREENS = [
  { id: "overview", label: "Overview" },
  { id: "library", label: "Library" },
  { id: "setup", label: "Setup" },
];

export default function App() {
  const [engine, setEngine] = useState({ status: "starting", detail: "" });
  const [screen, setScreen] = useState("overview");

  // On mount: read the current engine status and subscribe to changes.
  useEffect(() => {
    kb.engineStatus().then(setEngine);
    return kb.onEngineStatus(setEngine); // returns the unsubscribe function
  }, []);

  return (
    <div className="shell">
      <nav className="rail" aria-label="Screens">
        <div className="wordmark" aria-label="Knowledge Bank">
          <span className="wm-mark" aria-hidden="true" />
          <span>
            Knowledge
            <br />
            Bank
          </span>
        </div>
        <ul>
          {SCREENS.map((s) => (
            <li key={s.id}>
              <button
                className={`rail-item ${screen === s.id ? "current" : ""}`}
                aria-current={screen === s.id ? "page" : undefined}
                onClick={() => setScreen(s.id)}
                disabled={engine.status !== "ready"}
              >
                {s.label}
              </button>
            </li>
          ))}
        </ul>
        <EngineBadge engine={engine} />
      </nav>

      <main className="stage">
        {engine.status === "starting" && (
          <section className="frame center-note">
            <div className="pulse" aria-hidden="true" />
            <h1>Starting the engine</h1>
            <p className="muted">Opening the database and checking your laptop.</p>
          </section>
        )}

        {engine.status === "error" && (
          <section className="frame center-note problem">
            <h1>The engine didn't start</h1>
            <p>{engine.detail}</p>
            <p className="muted">Close the app and open it again. If this keeps happening, reinstall it.</p>
          </section>
        )}

        {engine.status === "ready" && (
          <>
            {screen === "overview" && <Overview onNavigate={setScreen} />}
            {screen === "library" && <Library />}
            {screen === "setup" && <SetupScreen />}
          </>
        )}
      </main>
    </div>
  );
}

/**
 * Setup screen: the three-step wizard plus the readiness checklist.
 * The checklist refreshes by itself when Ollama starts/stops or setup
 * completes (fix from v0.2.1: it used to stay on "not answering").
 */
function SetupScreen() {
  const [system, setSystem] = useState(null);
  const [loading, setLoading] = useState(false);
  const lastSetup = useRef(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setSystem(await kb.get("/system"));
    setLoading(false);
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

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

  return (
    <div className="setup">
      <header className="page-head">
        <h1>Setup</h1>
        <p className="lede">
          The AI runs entirely on this laptop. Install it, download the models, then let the app
          test which models suit your graphics card best.
        </p>
      </header>

      <SetupWizard onStatus={handleSetupStatus} />

      <section className="frame readiness" aria-label="System readiness">
        <div className="section-head">
          <h2>System readiness</h2>
          <button className="secondary" onClick={refresh} disabled={loading}>
            {loading ? "Checking…" : "Check again"}
          </button>
        </div>
        {system?.error && <p className="notice error">{system.error}</p>}
        {system?.checks && (
          <ul className="checks">
            {system.checks.map((c) => (
              <li key={c.name} className={c.ok ? "ok" : "fix"}>
                <span className="dot" aria-hidden="true" />
                <div>
                  <p className="check-name">
                    {c.name} <span className="muted">{c.detail}</span>
                  </p>
                  {c.fix && <p className="check-fix">{c.fix}</p>}
                </div>
              </li>
            ))}
          </ul>
        )}
        {system?.data_dir && <p className="muted small">Your bank is stored in {system.data_dir}</p>}
      </section>
    </div>
  );
}

/** Engine status at the foot of the rail. */
function EngineBadge({ engine }) {
  const label = { starting: "Engine starting", ready: "Engine ready", error: "Engine problem" }[
    engine.status
  ];
  return (
    <p className={`engine engine-${engine.status}`} title={engine.detail}>
      <span className="engine-dot" aria-hidden="true" />
      {label}
    </p>
  );
}
