/**
 * App.jsx — the app's frame: side rail, engine status, and the screens.
 *
 * WHAT:  - Side rail with the screens that exist so far: Overview, Library,
 *          Topics, Setup — each with its own icon and colour (more appear
 *          as phases are built: Map, Learn…)
 *        - Engine status at the foot of the rail (starting / ready / problem)
 *        - Shows the chosen screen once the engine is ready; a "starting"
 *          or "problem" panel before that
 *        - SetupScreen (below): the setup wizard + system readiness checks
 * WHY:   Phase 1 added a second real screen (Library), so the app needs
 *        simple navigation. A side rail keeps every screen one click away
 *        and leaves the full width for content like tables and search.
 * WHEN:  Rendered once at launch by main.jsx; lives for the whole session.
 * CONNECTED TO: Overview.jsx, Library.jsx, Topics.jsx, SetupWizard.jsx,
 *        Updates.jsx, GpuCard.jsx (v0.8.2), StorageCard.jsx, AppUpdate.jsx (v0.9), icons.jsx, bridge.js (engine status, /system), styles.css.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import Overview from "./Overview.jsx";
import QuickSearch from "./QuickSearch.jsx";
import Answers from "./Answers.jsx";
import Learn from "./Learn.jsx";
import Tools from "./Tools.jsx";
import Backup from "./Backup.jsx";
import GpuCard from "./GpuCard.jsx";
import StorageCard from "./StorageCard.jsx";
import { UpdateBanner, UpdateCard } from "./AppUpdate.jsx";
import Library from "./Library.jsx";
import Topics from "./Topics.jsx";
import SetupWizard from "./SetupWizard.jsx";
import Updates from "./Updates.jsx";
import Icon from "./icons.jsx";
import { kb } from "./bridge.js";

/**
 * Screens in the side rail, in order. `id` is used for navigation, `tone`
 * picks the screen's colour (its icon tile in the rail), `icon` its icon.
 */
const SCREENS = [
  { id: "overview", label: "Overview", icon: "overview", tone: "forest" },
  { id: "library", label: "Library", icon: "library", tone: "coral" },
  { id: "topics", label: "Topics", icon: "topics", tone: "violet" },
  { id: "answers", label: "Answers", icon: "answer", tone: "teal" },
  { id: "learn", label: "Learn", icon: "learn", tone: "coral" },
  { id: "tools", label: "Tools", icon: "tools", tone: "violet" },
  { id: "setup", label: "Setup", icon: "setup", tone: "mustard" },
];

export default function App() {
  const [engine, setEngine] = useState({ status: "starting", detail: "" });
  const [screen, setScreen] = useState("overview");
  // A topic to open when switching to Topics (from the Overview map or quick
  // search). A fresh object each time, so the same topic can be reopened.
  const [focus, setFocus] = useState(null);
  const [searching, setSearching] = useState(false);

  // Ctrl+K (or Cmd+K) opens quick search on any screen once the engine is up.
  useEffect(() => {
    function onKey(e) {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setSearching(true);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const navigate = (to, opts) => {
    setFocus(opts ? { ...opts, at: Date.now() } : null);
    setScreen(to);
  };
  const [version, setVersion] = useState("");

  // The running version, shown in the top-right corner (owner's request).
  useEffect(() => {
    kb.appVersion?.().then((v) => setVersion(v || ""));
  }, []);

  // On mount: read the current engine status and subscribe to changes.
  useEffect(() => {
    kb.engineStatus().then(setEngine);
    return kb.onEngineStatus(setEngine); // returns the unsubscribe function
  }, []);

  return (
    <div className="shell">
      <nav className="rail" aria-label="Screens">
        <div className="wordmark">
          <span className="wm-mark" aria-hidden="true">
            <i />
            <i />
            <i />
            <i />
          </span>
          <span>Knowledge Bank</span>
        </div>
        <ul>
          {SCREENS.map((s) => (
            <li key={s.id}>
              <button
                className={`rail-item tone-${s.tone} ${screen === s.id ? "current" : ""}`}
                aria-current={screen === s.id ? "page" : undefined}
                onClick={() => setScreen(s.id)}
                disabled={engine.status !== "ready"}
              >
                <span className="rail-icon">
                  <Icon name={s.icon} size={18} />
                </span>
                {s.label}
              </button>
            </li>
          ))}
        </ul>
        <button className="rail-search" onClick={() => setSearching(true)} disabled={engine.status !== "ready"}>
          <Icon name="search" size={16} />
          <span>Search</span>
          <kbd>Ctrl K</kbd>
        </button>
        <EngineBadge engine={engine} />
      </nav>

      <QuickSearch
        open={searching && engine.status === "ready"}
        onClose={() => setSearching(false)}
        onOpenTopic={(id, pointId) => navigate("topics", { topicId: id, pointId })}
        onAsk={(question) => navigate("answers", { question })}
      />

      <main className="stage">
        {version && (
          <p className="version-badge" title="Installed version of Knowledge Bank">
            v{version}
          </p>
        )}
        <UpdateBanner />
        {engine.status === "starting" && (
          <section className="card center-note">
            <div className="pulse" aria-hidden="true" />
            <h1>Starting the engine</h1>
            <p className="muted">Opening the database and checking your laptop.</p>
          </section>
        )}

        {engine.status === "error" && (
          <section className="card center-note problem">
            <h1>The engine didn't start</h1>
            <p>{engine.detail}</p>
            <p className="muted">Close the app and open it again. If this keeps happening, reinstall it.</p>
          </section>
        )}

        {engine.status === "ready" && (
          <>
            {screen === "overview" && <Overview onNavigate={navigate} />}
            {screen === "library" && <Library />}
            {screen === "topics" && <Topics focus={focus} />}
            {screen === "answers" && (
              <Answers
                initial={focus?.question ? focus : null}
                onOpenTopic={(id, pointId) => navigate("topics", { topicId: id, pointId })}
              />
            )}
            {screen === "learn" && <Learn onOpenTopic={(id) => navigate("topics", { topicId: id })} />}
            {screen === "tools" && <Tools onOpenTopic={(id, pointId) => navigate("topics", { topicId: id, pointId })} />}
            {screen === "setup" && <SetupScreen />}
          </>
        )}
      </main>
    </div>
  );
}

/**
 * Setup screen: the three-step wizard, AI updates, and the readiness checklist.
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

      <GpuCard />

      <UpdateCard />

      <Updates />

      <Backup />

      <StorageCard />

      <section className="card readiness" aria-label="System readiness">
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
