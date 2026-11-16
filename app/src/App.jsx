/**
 * App.jsx — the app's frame: sidebar, engine status, and the screens.
 *
 * v0.15: the app is now CHAT-FIRST. It opens on Chat (a new, empty chat), and the left
 *        side is a ChatGPT/Claude-style sidebar (Sidebar.jsx): New chat, your saved chats
 *        grouped by day, and a collapsible "Knowledge" section holding the library screens
 *        (Overview, Library, Topics, Answers, Learn, Tools) plus Setup. This file owns the
 *        state both sides share: which chat is open, a counter that refreshes the chat list,
 *        whether the sidebar is collapsed, and the keyboard shortcuts.
 *
 * WHAT:  - Sidebar (collapsible) + the chosen screen once the engine is ready; a "starting"
 *          or "problem" panel before that
 *        - Shortcuts: Ctrl+K quick search, Ctrl+Shift+O new chat, Ctrl+B show/hide sidebar
 *        - The chat screen is shown edge to edge (no page margins) like a chat app; every
 *          other screen keeps its normal padded page
 *        - SetupScreen (below): the setup wizard + system readiness checks
 * WHY:   The owner asked for the whole app to feel like a chat app, "not just models".
 *        Chat is the front door; the library is what the chat draws on.
 * WHEN:  Rendered once at launch by main.jsx; lives for the whole session.
 * CONNECTED TO: Sidebar.jsx, Chat.jsx, Learning.jsx (v0.16), Overview.jsx, Library.jsx, Topics.jsx, SetupWizard.jsx,
 *        Updates.jsx, GpuCard.jsx, StorageCard.jsx, AppUpdate.jsx, ModelCard.jsx, QuickSearch.jsx,
 *        icons.jsx, bridge.js (engine status, /system), styles.css.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import Overview from "./Overview.jsx";
import QuickSearch from "./QuickSearch.jsx";
import Answers from "./Answers.jsx";
import Chat from "./Chat.jsx";
import Learning from "./Learning.jsx";
import Sidebar from "./Sidebar.jsx";
import ModelCard from "./ModelCard.jsx";
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

export default function App() {
  const [engine, setEngine] = useState({ status: "starting", detail: "" });
  const [screen, setScreen] = useState("chat"); // chat-first: the app opens on a new chat
  const [activeChat, setActiveChat] = useState(null); // the open chat's id (null = a new, empty one)
  const [newChatTick, setNewChatTick] = useState(0); // bumped by "New chat" so Chat resets and focuses its box
  const [listVersion, setListVersion] = useState(0); // bumped whenever the chat list may have changed
  const [collapsed, setCollapsed] = useState(() => {
    try {
      return localStorage.getItem("kb.sideCollapsed") === "1";
    } catch {
      return false;
    }
  });
  const bumpList = useCallback(() => setListVersion((v) => v + 1), []);
  const newChat = useCallback(() => {
    setActiveChat(null);
    setNewChatTick((t) => t + 1);
    setScreen("chat");
  }, []);
  const toggleSide = useCallback(() => {
    setCollapsed((c) => {
      try {
        localStorage.setItem("kb.sideCollapsed", c ? "0" : "1");
      } catch {
        /* not remembered, still works */
      }
      return !c;
    });
  }, []);
  // A topic to open when switching to Topics (from the Overview map or quick
  // search). A fresh object each time, so the same topic can be reopened.
  const [focus, setFocus] = useState(null);
  const [searching, setSearching] = useState(false);

  // Shortcuts on any screen: Ctrl+K quick search, Ctrl+Shift+O new chat, Ctrl+B sidebar (Cmd on a Mac).
  useEffect(() => {
    function onKey(e) {
      if (!(e.ctrlKey || e.metaKey)) return;
      const k = e.key.toLowerCase();
      if (k === "k") {
        e.preventDefault();
        setSearching(true);
      } else if (k === "o" && e.shiftKey) {
        e.preventDefault();
        newChat();
      } else if (k === "b" && !e.shiftKey) {
        e.preventDefault();
        toggleSide();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [newChat, toggleSide]);

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
    <div className={`shell ${collapsed ? "side-closed" : ""}`}>
      <Sidebar
        screen={screen}
        onScreen={setScreen}
        engine={engine}
        activeChat={activeChat}
        onSelectChat={(id) => {
          setActiveChat(id);
          setScreen("chat");
        }}
        onNewChat={newChat}
        onChatGone={() => setActiveChat(null)}
        listVersion={listVersion}
        onListChanged={bumpList}
        collapsed={collapsed}
        onToggle={toggleSide}
        onSearch={() => setSearching(true)}
      />

      <QuickSearch
        open={searching && engine.status === "ready"}
        onClose={() => setSearching(false)}
        onOpenTopic={(id, pointId) => navigate("topics", { topicId: id, pointId })}
        onAsk={(question) => navigate("answers", { question })}
      />

      <main className={`stage ${screen === "chat" && engine.status === "ready" ? "chat-stage" : ""}`}>
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
            {screen === "chat" && (
              <Chat
                activeId={activeChat}
                onActiveChange={setActiveChat}
                newChatTick={newChatTick}
                onListChanged={bumpList}
                onOpenTopic={(id, pointId) => navigate("topics", { topicId: id, pointId })}
                onOpenSetup={() => setScreen("setup")}
              />
            )}
            {screen === "learning" && <Learning />}
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

      <ModelCard />

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
