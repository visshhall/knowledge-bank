/**
 * Sidebar.jsx — v0.15 the left side of the chat-first app (like the sidebar of ChatGPT or Claude).
 *
 * WHAT:  - Wordmark and a "collapse sidebar" button.
 *        - "New chat" (also Ctrl+Shift+O) and a box that searches your saved chats by title or text.
 *        - Your chats, newest first, grouped Today / Yesterday / Previous 7 days / Older. Hover a chat
 *          to rename it (pencil) or delete it (bin; the first click asks "Delete?", the second deletes).
 *        - A "Knowledge" section (closed by default so the chat list gets the room; remembers if you open it) with the screens that
 *          hold the library: Overview, Library, Topics, Learning (v0.16), Live learning (v0.21), Insights (v0.20), Answers, Learn, Tools.
 *        - At the foot: Setup, quick search (Ctrl+K) and the engine status.
 *        When collapsed, only a thin strip with the toggle, New chat and the screen icons remains.
 * WHY:   The owner asked for the whole app to feel like a chat app, not a library with a chat tab.
 *        Chat is now the home screen; the library is one click away but no longer the front door.
 * WHEN:  Always shown by App.jsx. Polls GET /chat/list when the list changes (App.jsx bumps `version`
 *        after a message is sent, a chat is renamed or deleted) and when the search text changes.
 * CONNECTED TO: App.jsx (state and navigation), bridge.js → engine /chat/list, /chat/rename,
 *        /chat/delete (server.py → chat.py), icons.jsx, styles.css (.side-*).
 */
import { useEffect, useMemo, useState } from "react";
import Icon from "./icons.jsx";
import { kb, usePoll } from "./bridge.js";

/** The library screens, in the "Knowledge" section. `tone` colours the small icon tile. */
const KNOWLEDGE = [
  { id: "overview", label: "Overview", icon: "overview", tone: "forest" },
  { id: "library", label: "Library", icon: "library", tone: "coral" },
  { id: "topics", label: "Topics", icon: "topics", tone: "violet" },
  { id: "learning", label: "Learning", icon: "sparkle", tone: "mustard" },
  { id: "brain", label: "Live learning", icon: "pulse", tone: "coral" },
  { id: "insights", label: "Insights", icon: "map", tone: "teal" },
  { id: "answers", label: "Answers", icon: "answer", tone: "teal" },
  { id: "learn", label: "Learn", icon: "learn", tone: "coral" },
  { id: "tools", label: "Tools", icon: "tools", tone: "violet" },
];

const GROUPS = ["Today", "Yesterday", "Previous 7 days", "Older"];

/** Which group a chat belongs to, from its saved time (the engine stores UTC "YYYY-MM-DD HH:MM:SS"). */
export function groupOf(updatedAt, now = new Date()) {
  const t = new Date(String(updatedAt).replace(" ", "T") + "Z");
  if (Number.isNaN(t.getTime())) return "Older";
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const day = 86400000;
  if (t.getTime() >= startOfToday) return "Today";
  if (t.getTime() >= startOfToday - day) return "Yesterday";
  if (t.getTime() >= startOfToday - 7 * day) return "Previous 7 days";
  return "Older";
}

export default function Sidebar({
  screen,
  onScreen,
  engine,
  activeChat,
  onSelectChat,
  onNewChat,
  onChatGone,
  listVersion,
  onListChanged,
  collapsed,
  onToggle,
  onSearch,
}) {
  const ready = engine.status === "ready";
  const [q, setQ] = useState("");
  const [renaming, setRenaming] = useState(null); // { id, value }
  const [confirm, setConfirm] = useState(null); // chat id waiting for the second click
  const [knowledgeOpen, setKnowledgeOpen] = useState(() => {
    try {
      return localStorage.getItem("kb.knowledgeOpen") === "1"; // closed by default: the chat list gets the room
    } catch {
      return false;
    }
  });
  // listVersion is only here to make usePoll fetch again when the app says the list changed.
  const [list] = usePoll("/chat/list", 0, { q, v: listVersion });

  useEffect(() => {
    try {
      localStorage.setItem("kb.knowledgeOpen", knowledgeOpen ? "1" : "0");
    } catch {
      /* private mode etc. — the preference just isn't remembered */
    }
  }, [knowledgeOpen]);

  const grouped = useMemo(() => {
    const out = new Map(GROUPS.map((g) => [g, []]));
    for (const c of list?.chats ?? []) out.get(groupOf(c.updated_at)).push(c);
    return GROUPS.map((g) => [g, out.get(g)]).filter(([, items]) => items.length);
  }, [list]);

  async function saveRename() {
    if (!renaming) return;
    await kb.post("/chat/rename", { id: renaming.id, title: renaming.value });
    setRenaming(null);
    onListChanged();
  }

  async function remove(id) {
    if (confirm !== id) {
      setConfirm(id); // first click asks, second deletes
      return;
    }
    setConfirm(null);
    await kb.post("/chat/delete", { id });
    if (id === activeChat) onChatGone();
    onListChanged();
  }

  if (collapsed) {
    return (
      <nav className="side side-collapsed" aria-label="Chats and screens">
        <button className="side-icon-btn" onClick={onToggle} aria-label="Open sidebar" title="Open sidebar (Ctrl+B)">
          <Icon name="panel" size={18} />
        </button>
        <button className="side-icon-btn" onClick={onNewChat} disabled={!ready} aria-label="New chat" title="New chat (Ctrl+Shift+O)">
          <Icon name="edit" size={18} />
        </button>
        <button className="side-icon-btn" onClick={onSearch} disabled={!ready} aria-label="Search" title="Search (Ctrl+K)">
          <Icon name="search" size={18} />
        </button>
        <span className="side-sep" aria-hidden="true" />
        {KNOWLEDGE.map((s) => (
          <button
            key={s.id}
            className={`side-icon-btn ${screen === s.id ? "current" : ""}`}
            onClick={() => onScreen(s.id)}
            disabled={!ready}
            aria-label={s.label}
            title={s.label}
          >
            <Icon name={s.icon} size={18} />
          </button>
        ))}
        <button
          className={`side-icon-btn side-bottom ${screen === "setup" ? "current" : ""}`}
          onClick={() => onScreen("setup")}
          disabled={!ready}
          aria-label="Setup"
          title="Setup"
        >
          <Icon name="setup" size={18} />
        </button>
        <span className={`engine-dot-only engine-${engine.status}`} title={engine.detail || engine.status} />
      </nav>
    );
  }

  const statusLabel = { starting: "Engine starting", ready: "Engine ready", error: "Engine problem" }[engine.status];

  return (
    <nav className="side" aria-label="Chats and screens">
      <div className="side-top">
        <div className="wordmark">
          <span className="wm-mark" aria-hidden="true">
            <i />
            <i />
            <i />
            <i />
          </span>
          <span>Knowledge Bank</span>
        </div>
        <button className="side-icon-btn" onClick={onToggle} aria-label="Close sidebar" title="Close sidebar (Ctrl+B)">
          <Icon name="panel" size={18} />
        </button>
      </div>

      <button className="side-new" onClick={onNewChat} disabled={!ready}>
        <Icon name="edit" size={16} /> New chat <kbd>Ctrl Shift O</kbd>
      </button>

      <input
        className="side-search"
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder="Search your chats"
        aria-label="Search your chats"
        disabled={!ready}
      />

      <div className="side-chats">
        {grouped.map(([group, items]) => (
          <section key={group} aria-label={group}>
            <h3 className="side-group">{group}</h3>
            <ul>
              {items.map((c) => (
                <li key={c.id} className={`side-chat ${screen === "chat" && c.id === activeChat ? "on" : ""}`}>
                  {renaming?.id === c.id ? (
                    <form
                      className="side-rename"
                      onSubmit={(e) => {
                        e.preventDefault();
                        saveRename();
                      }}
                    >
                      <input
                        autoFocus
                        value={renaming.value}
                        onChange={(e) => setRenaming({ ...renaming, value: e.target.value })}
                        onBlur={saveRename}
                        onKeyDown={(e) => e.key === "Escape" && setRenaming(null)}
                        aria-label="Chat name"
                        maxLength={120}
                      />
                    </form>
                  ) : (
                    <>
                      <button className="side-chat-title" onClick={() => onSelectChat(c.id)} title={c.title}>
                        {c.title}
                      </button>
                      <span className="side-chat-actions">
                        <button
                          className="side-mini"
                          onClick={() => setRenaming({ id: c.id, value: c.title })}
                          aria-label={`Rename "${c.title}"`}
                          title="Rename"
                        >
                          <Icon name="edit" size={14} />
                        </button>
                        <button
                          className={`side-mini ${confirm === c.id ? "ask" : ""}`}
                          onClick={() => remove(c.id)}
                          onBlur={() => confirm === c.id && setConfirm(null)}
                          aria-label={`Delete "${c.title}"`}
                          title={confirm === c.id ? "Click again to delete" : "Delete"}
                        >
                          {confirm === c.id ? "Delete?" : <Icon name="trash" size={14} />}
                        </button>
                      </span>
                    </>
                  )}
                </li>
              ))}
            </ul>
          </section>
        ))}
        {!grouped.length && (
          <p className="muted small side-empty">{q ? "No chat matches that." : "Your chats are saved here."}</p>
        )}
      </div>

      <div className="side-knowledge">
        <button className="side-fold" onClick={() => setKnowledgeOpen(!knowledgeOpen)} aria-expanded={knowledgeOpen}>
          <Icon name="down" size={14} />
          <span>Knowledge</span>
        </button>
        {knowledgeOpen && (
          <ul>
            {KNOWLEDGE.map((s) => (
              <li key={s.id}>
                <button
                  className={`rail-item tone-${s.tone} ${screen === s.id ? "current" : ""}`}
                  aria-current={screen === s.id ? "page" : undefined}
                  onClick={() => onScreen(s.id)}
                  disabled={!ready}
                >
                  <span className="rail-icon">
                    <Icon name={s.icon} size={16} />
                  </span>
                  {s.label}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="side-foot">
        <button
          className={`rail-item tone-mustard ${screen === "setup" ? "current" : ""}`}
          aria-current={screen === "setup" ? "page" : undefined}
          onClick={() => onScreen("setup")}
          disabled={!ready}
        >
          <span className="rail-icon">
            <Icon name="setup" size={16} />
          </span>
          Setup
        </button>
        <button className="rail-search" onClick={onSearch} disabled={!ready}>
          <Icon name="search" size={16} />
          <span>Search everything</span>
          <kbd>Ctrl K</kbd>
        </button>
        <p className={`engine engine-${engine.status}`} title={engine.detail}>
          <span className="engine-dot" aria-hidden="true" />
          {statusLabel}
        </p>
      </div>
    </nav>
  );
}
