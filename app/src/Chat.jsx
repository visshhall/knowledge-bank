/**
 * Chat.jsx — v0.11/v0.12 "Chat": talk to your library, or freely to the model, in saved conversations.
 *
 * v0.14: a "Memory" button opens a list of short facts about you (MemoryPanel.jsx) that Free chat
 *        uses; "Remember" under each of your messages pre-fills a new fact from that message.
 *
 * v0.12: a three-way switch above the message box chooses how a chat answers —
 *        "My files" (library only, cited and checked), "Files + general" (files
 *        first, then a labelled general-knowledge part) or "Free chat" (no files,
 *        like any AI chat). The choice is saved with each chat. In Free chat a
 *        PERSONA shapes the answers: pick one of the built-ins (Assistant, Ākāra
 *        copywriter, Coding helper, Tutor, Security analyst) or write your own in
 *        "Edit personas". Free replies are labelled "not from your files".
 *
 * WHAT:  - Left: your saved chats (newest first), a box to search them by
 *          title or text, "New chat", rename and delete.
 *        - Top bar: which AI model answers (choose any model installed on
 *          this laptop) and a reminder that answers come from your files.
 *        - The conversation: your messages and the answers. Each answer is
 *          written only from passages of your own files, cited [1]…[n], and
 *          fact-checked (numbers, technique IDs, commands must be in the
 *          cited sources). "Sources" under an answer lists the passages with
 *          an "Open page" chip (the original PDF at that page) and "Open
 *          topic". Clicking a [n] chip opens and highlights that source.
 *        - "Also use general knowledge" (off by default, per message): when
 *          your files don't cover a question, the model may answer from what
 *          it knows. That part is shown in a separate, clearly labelled box
 *          ("From general knowledge (not from your files)") and is NOT
 *          fact-checked.
 *        - Answers stream in as they are written; Stop ends the reply and
 *          keeps what was written. Enter sends, Shift+Enter adds a line.
 * WHY:   The owner asked to turn the Knowledge Bank itself into the chat app,
 *        since it already holds the enriched data of ~200 PDFs. Everything
 *        runs on this laptop; nothing is sent anywhere.
 * WHEN:  The "Chat" screen in the side rail (App.jsx).
 * CONNECTED TO: bridge.js → engine /chat/list, /chat/get, /chat/new,
 *        /chat/rename, /chat/delete, /chat/send, /chat/status, /chat/stop,
 *        /chat/personas, /chat/persona/save, /chat/persona/delete,
 *        /models/choices, /models/select (server.py → chat.py,
 *        modelpick.py); Formatted.jsx (Markdown, Formatted); SourceChip.jsx;
 *        App.jsx (onOpenTopic, onOpenSetup).
 */
import { useCallback, useEffect, useRef, useState } from "react";
import Icon from "./icons.jsx";
import SourceChip from "./SourceChip.jsx";
import MemoryPanel from "./MemoryPanel.jsx";
import { Formatted, Markdown } from "./Formatted.jsx";
import { kb, usePoll } from "./bridge.js";

/** The line chat.py puts in front of everything that is NOT from the files. */
const GENERAL_MARK = "From general knowledge (not from your files):";

/** The three ways a chat can answer (saved per chat; the names match chat.py). */
const MODES = [
  { id: "library", label: "My files", hint: "Answers only from your PDFs, with every source cited and fact-checked." },
  { id: "both", label: "Files + general", hint: "Your files first; anything from the model's own knowledge is added in a labelled box." },
  { id: "free", label: "Free chat", hint: "No files. Talk to the model about anything, like any AI chat. Not cited, not fact-checked." },
];

const FREE_STARTERS = [
  "Explain how a heat pump works in simple words.",
  "Write a polite follow-up email to a customer who hasn't replied for a week.",
  "Help me plan my week as a small-business owner.",
];

const STARTERS = [
  "How do I detect and contain an RDP brute force that ended in a successful login?",
  "Explain Kerberoasting step by step and which Windows events show it.",
  "Which KQL queries in my files help find lateral movement?",
];

/** Splits an answer into the part from the files and the general-knowledge part. */
function splitGeneral(text) {
  const at = text.indexOf(GENERAL_MARK);
  if (at < 0) return [text, ""];
  return [text.slice(0, at).trim(), text.slice(at + GENERAL_MARK.length).trim()];
}

export default function Chat({ onOpenTopic, onOpenSetup }) {
  const [activeId, setActiveId] = useState(null); // the open chat (null = a new, empty one)
  const [chat, setChat] = useState(null); // the open chat's messages
  const [search, setSearch] = useState("");
  const [draft, setDraft] = useState("");
  const [mode, setMode] = useState("library"); // how the next message is answered: library | both | free
  const [personaId, setPersonaId] = useState(null); // who answers in Free chat (null = the Assistant)
  const [editing, setEditing] = useState(null); // the persona being written: { id, name, prompt, builtin }
  const [showPersonas, setShowPersonas] = useState(false);
  const [showMemory, setShowMemory] = useState(false); // the Memory panel (v0.14)
  const [prefill, setPrefill] = useState(""); // text for a new memory fact, from "Remember" under a message
  const clearPrefill = useCallback(() => setPrefill(""), []);
  const [notice, setNotice] = useState("");
  const [renaming, setRenaming] = useState(null); // { id, value }
  const [confirmDelete, setConfirmDelete] = useState(null); // chat id waiting for a second click
  const [openSources, setOpenSources] = useState(() => new Set()); // message ids with Sources open
  const [lit, setLit] = useState(null); // "messageId:n" of the highlighted source
  const [pendingUser, setPendingUser] = useState(null); // text shown at once while the engine stores it
  const [job] = usePoll("/chat/status", 700);
  const [list, reloadList] = usePoll("/chat/list", 0, { q: search });
  const [models, reloadModels] = usePoll("/models/choices", 0);
  const [personaData, reloadPersonas] = usePoll("/chat/personas", 0);
  const personas = personaData?.personas ?? [];
  const awaiting = useRef(null); // chat id we are waiting on a reply for
  const sentAt = useRef(0); // when we pressed Send (seconds); ignores a stale "done" from the previous reply
  const threadRef = useRef(null);
  const boxRef = useRef(null);

  const loadChat = useCallback(async (id) => {
    if (!id) {
      setChat(null);
      return;
    }
    const r = await kb.get("/chat/get", { id });
    if (!r.error) {
      setChat(r);
      setMode(r.mode || "library"); // a chat opens the way it was last used
      setPersonaId(r.persona_id ?? null);
    }
  }, []);

  useEffect(() => {
    loadChat(activeId);
    setOpenSources(new Set());
    setLit(null);
  }, [activeId, loadChat]);

  // Returning to Chat while a reply is still being written: show it again.
  useEffect(() => {
    if (job?.state === "running" && job.chat_id && !awaiting.current) {
      awaiting.current = job.chat_id;
      setActiveId((cur) => cur ?? job.chat_id);
    }
  }, [job]);

  // When the reply is finished, load the saved conversation.
  useEffect(() => {
    if (!awaiting.current || !job) return;
    if (job.started_at && job.started_at < sentAt.current - 1) return; // still the previous reply's status
    if (job.state === "done" || job.state === "error") {
      const id = awaiting.current;
      awaiting.current = null;
      setPendingUser(null);
      if (job.state === "error") setNotice(job.message || "The reply could not be written.");
      loadChat(id);
      reloadList();
    }
  }, [job, loadChat, reloadList]);

  // Keep the newest text in view while the reply is written.
  const running = job?.state === "running";
  const liveHere = running && job.chat_id === activeId;
  useEffect(() => {
    const el = threadRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [chat, job?.live, pendingUser]);

  async function send(text) {
    const body = (text ?? draft).trim();
    if (body.length < 2 || running) return;
    setNotice("");
    sentAt.current = Date.now() / 1000;
    const r = await kb.post("/chat/send", {
      chat_id: activeId,
      text: body,
      mode,
      persona_id: mode === "free" ? personaId : null,
    });
    if (r.error || r.ok === false) {
      setNotice(r.error || r.message);
      return;
    }
    awaiting.current = r.chat_id;
    setDraft("");
    setPendingUser(body);
    if (r.chat_id !== activeId) setActiveId(r.chat_id);
    else loadChat(r.chat_id);
    reloadList();
  }

  async function startNew() {
    setActiveId(null);
    setChat(null);
    setNotice("");
    boxRef.current?.focus();
  }

  async function saveRename() {
    if (!renaming) return;
    const r = await kb.post("/chat/rename", { id: renaming.id, title: renaming.value });
    if (r.ok === false) setNotice(r.message);
    setRenaming(null);
    reloadList();
    if (renaming.id === activeId) loadChat(activeId);
  }

  async function remove(id) {
    if (confirmDelete !== id) {
      setConfirmDelete(id); // first click asks; second click deletes
      return;
    }
    setConfirmDelete(null);
    await kb.post("/chat/delete", { id });
    if (id === activeId) {
      setActiveId(null);
      setChat(null);
    }
    reloadList();
  }

  async function pickModel(name) {
    const r = await kb.post("/models/select", { model: name });
    setNotice(r.ok ? "" : r.message || r.error || "");
    reloadModels();
  }

  /** Save the persona being edited (new, or one of the owner's own). */
  async function savePersona() {
    if (!editing) return;
    const r = await kb.post("/chat/persona/save", {
      id: editing.builtin ? null : editing.id,
      name: editing.name,
      prompt: editing.prompt,
    });
    if (r.ok === false || r.error) {
      setNotice(r.message || r.error);
      return;
    }
    setNotice("");
    setPersonaId(r.id);
    setEditing(null);
    reloadPersonas();
  }

  async function removePersona(id) {
    await kb.post("/chat/persona/delete", { id });
    if (personaId === id) setPersonaId(null);
    setEditing(null);
    reloadPersonas();
  }

  function toggleSources(id) {
    setOpenSources((cur) => {
      const next = new Set(cur);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }

  function cite(messageId, n) {
    setOpenSources((cur) => new Set(cur).add(messageId));
    setLit(`${messageId}:${n}`);
    setTimeout(() => {
      document.querySelector(`[data-src="${messageId}:${n}"]`)?.scrollIntoView({ behavior: "smooth", block: "center" });
    }, 60);
  }

  const messages = chat?.messages ?? [];
  const installed = models?.installed ?? [];
  const empty = !messages.length && !pendingUser && !liveHere;
  const free = mode === "free";
  const persona = personas.find((p) => p.id === personaId) ?? personas[0];

  return (
    <div className="chat">
      <header className="page-head">
        <h1>Chat</h1>
        <p className="lede">
          Talk to your library, or switch to Free chat and talk to the model about anything. In “My files” every
          answer is cited and fact-checked; follow-ups remember the conversation. Everything stays on this laptop.
        </p>
      </header>

      <div className="chat-layout">
        <aside className="card chat-list" aria-label="Saved chats">
          <button className="chat-new" onClick={startNew}>
            <Icon name="chat" size={16} /> New chat
          </button>
          <input
            className="chat-search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search your chats"
            aria-label="Search your chats"
          />
          {list?.chats?.length ? (
            <ul>
              {list.chats.map((c) => (
                <li key={c.id} className={c.id === activeId ? "on" : ""}>
                  {renaming?.id === c.id ? (
                    <form
                      className="chat-rename"
                      onSubmit={(e) => {
                        e.preventDefault();
                        saveRename();
                      }}
                    >
                      <input
                        autoFocus
                        value={renaming.value}
                        onChange={(e) => setRenaming({ ...renaming, value: e.target.value })}
                        aria-label="Chat name"
                      />
                      <button type="submit" className="small-btn">Save</button>
                    </form>
                  ) : (
                    <>
                      <button className="recent-q" onClick={() => setActiveId(c.id)} title={c.title}>
                        {c.title}
                      </button>
                      <button
                        className="link small"
                        onClick={() => setRenaming({ id: c.id, value: c.title })}
                        aria-label={`Rename "${c.title}"`}
                      >
                        Rename
                      </button>
                      <button className="link small" onClick={() => remove(c.id)} aria-label={`Delete "${c.title}"`}>
                        {confirmDelete === c.id ? "Sure?" : "Delete"}
                      </button>
                    </>
                  )}
                </li>
              ))}
            </ul>
          ) : (
            <p className="muted small">{search ? "No chat matches that." : "Your chats are saved here."}</p>
          )}
        </aside>

        <section className="chat-main">
          <div className="card chat-bar">
            <label className="chat-model">
              <span className="muted small">Model</span>
              <select
                value={installed.find((m) => m.current)?.name ?? ""}
                onChange={(e) => pickModel(e.target.value)}
                disabled={running || !installed.length}
                aria-label="Model that writes the answers"
              >
                {!installed.some((m) => m.current) && <option value="">{models?.current ?? "…"}</option>}
                {installed.map((m) => (
                  <option key={m.name} value={m.name}>
                    {m.name}
                  </option>
                ))}
              </select>
            </label>
            {free && (
              <label className="chat-model">
                <span className="muted small">Persona</span>
                <select
                  value={persona?.id ?? ""}
                  onChange={(e) => setPersonaId(Number(e.target.value))}
                  disabled={running}
                  aria-label="Who answers in Free chat"
                >
                  {personas.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                    </option>
                  ))}
                </select>
                <button className="link small" onClick={() => setShowPersonas(!showPersonas)} aria-expanded={showPersonas}>
                  {showPersonas ? "Close personas" : "Edit personas"}
                </button>
              </label>
            )}
            <button className="link small" onClick={() => setShowMemory(!showMemory)} aria-expanded={showMemory}>
              {showMemory ? "Close memory" : "Memory"}
            </button>
            <button className="link small" onClick={onOpenSetup}>
              Download and compare models
            </button>
          </div>

          {showMemory && <MemoryPanel chatId={activeId} prefill={prefill} onPrefillUsed={clearPrefill} />}

          {free && showPersonas && (
            <section className="card persona-editor" aria-label="Personas">
              <p className="muted small">
                A persona is a set of instructions the model follows in Free chat — who it is, how it writes, what it
                avoids. Built-in ones are read-only; copy one to make it your own.
              </p>
              <ul className="persona-list">
                {personas.map((p) => (
                  <li key={p.id} className={p.id === persona?.id ? "on" : ""}>
                    <button className="recent-q" onClick={() => setPersonaId(p.id)}>
                      {p.name}
                      {p.builtin && <span className="muted small"> · built in</span>}
                    </button>
                    <button className="link small" onClick={() => setEditing({ ...p })}>
                      {p.builtin ? "View / copy" : "Edit"}
                    </button>
                  </li>
                ))}
              </ul>
              <button className="small-btn" onClick={() => setEditing({ id: null, name: "", prompt: "", builtin: false })}>
                New persona
              </button>
              {editing && (
                <form
                  className="persona-form"
                  onSubmit={(e) => {
                    e.preventDefault();
                    savePersona();
                  }}
                >
                  <label>
                    <span className="small">Name</span>
                    <input
                      value={editing.name}
                      onChange={(e) => setEditing({ ...editing, name: e.target.value })}
                      readOnly={editing.builtin}
                      maxLength={60}
                    />
                  </label>
                  <label>
                    <span className="small">Instructions the model follows</span>
                    <textarea
                      rows={7}
                      value={editing.prompt}
                      onChange={(e) => setEditing({ ...editing, prompt: e.target.value })}
                      readOnly={editing.builtin}
                      maxLength={4000}
                    />
                  </label>
                  <div className="persona-actions">
                    {editing.builtin ? (
                      <button
                        key="copy"
                        type="button"
                        onClick={() => setEditing({ id: null, name: `${editing.name} (mine)`, prompt: editing.prompt, builtin: false })}
                      >
                        Copy and edit
                      </button>
                    ) : (
                      // Separate keys: without them React would reuse this very button, flip it from
                      // type="button" to "submit" mid-click, and the click would save the copy at once.
                      <button key="save" type="submit">Save persona</button>
                    )}
                    <button type="button" className="secondary" onClick={() => setEditing(null)}>
                      Close
                    </button>
                    {!editing.builtin && editing.id && (
                      <button type="button" className="link small" onClick={() => removePersona(editing.id)}>
                        Delete this persona
                      </button>
                    )}
                  </div>
                </form>
              )}
            </section>
          )}

          {notice && <p className="notice error">{notice}</p>}

          <div className="chat-thread" ref={threadRef} aria-live="polite">
            {empty && (
              <section className="card chat-empty">
                <p>{free ? "Ask me anything. For example:" : "Ask anything about what is in your files. For example:"}</p>
                <ul>
                  {(free ? FREE_STARTERS : STARTERS).map((s) => (
                    <li key={s}>
                      <button className="link" onClick={() => send(s)} disabled={running}>
                        {s}
                      </button>
                    </li>
                  ))}
                </ul>
              </section>
            )}

            {messages.map((m) =>
              m.role === "user" ? (
                <div key={m.id} className="msg-user-wrap">
                  <div className="msg-user">{m.content}</div>
                  <button
                    className="link small"
                    onClick={() => {
                      setShowMemory(true);
                      setPrefill(m.content);
                    }}
                  >
                    Remember
                  </button>
                </div>
              ) : (
                <AnswerCard
                  key={m.id}
                  m={m}
                  open={openSources.has(m.id)}
                  lit={lit}
                  onToggle={() => toggleSources(m.id)}
                  onCite={(n) => cite(m.id, n)}
                  onOpenTopic={onOpenTopic}
                />
              )
            )}

            {pendingUser && !messages.some((m) => m.role === "user" && m.content === pendingUser) && (
              <div className="msg-user">{pendingUser}</div>
            )}

            {liveHere && (
              <section className="card msg-ai" aria-label="Writing the answer">
                {job.live ? (
                  <div className="answer-body live-writing">
                    <Markdown text={job.live} onCite={() => {}} />
                    <span className="live-cursor" aria-hidden="true" />
                  </div>
                ) : (
                  <div className="thinking" aria-hidden="true">
                    <span />
                    <span />
                    <span />
                  </div>
                )}
                <p className="muted small">
                  {job.stage}
                  {job.live
                    ? free
                      ? ""
                      : " Facts are checked when it finishes."
                    : " A local model on a 4 GB card takes about 20–60 seconds."}
                </p>
              </section>
            )}
          </div>

          <form
            className="card chat-composer"
            onSubmit={(e) => {
              e.preventDefault();
              send();
            }}
          >
            <textarea
              ref={boxRef}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  send();
                }
              }}
              rows={2}
              placeholder={
                free
                  ? `Message the model as “${persona?.name ?? "Assistant"}”… (Enter to send, Shift+Enter for a new line)`
                  : "Ask about your files… (Enter to send, Shift+Enter for a new line)"
              }
              aria-label="Your message"
            />
            <div className="chat-composer-foot">
              <div className="chat-modes" role="group" aria-label="How this chat answers">
                {MODES.map((m) => (
                  <button
                    type="button"
                    key={m.id}
                    className={`seg ${mode === m.id ? "on" : ""}`}
                    aria-pressed={mode === m.id}
                    title={m.hint}
                    onClick={() => setMode(m.id)}
                    disabled={running}
                  >
                    {m.label}
                  </button>
                ))}
              </div>
              {running ? (
                <button type="button" className="secondary" onClick={() => kb.post("/chat/stop", {})}>
                  Stop
                </button>
              ) : (
                <button type="submit" disabled={draft.trim().length < 2}>
                  <Icon name="sparkle" size={18} /> Send
                </button>
              )}
            </div>
          </form>
        </section>
      </div>
    </div>
  );
}

/** One answer: the text, a general-knowledge box if there is one, a checked-note and the sources. */
function AnswerCard({ m, open, lit, onToggle, onCite, onOpenTopic }) {
  const [fromFiles, fromGeneral] = splitGeneral(m.content);
  const sources = Object.entries(m.sources ?? {});
  const removed = m.checks?.removed_count ?? 0;
  const [showRemoved, setShowRemoved] = useState(false);
  return (
    <section className="card msg-ai">
      {fromFiles && (
        <div className="answer-body">
          <Markdown text={fromFiles} onCite={onCite} />
        </div>
      )}
      {m.mode === "free" && (
        <p className="chat-free-label">
          <Icon name="globe" size={14} /> Free chat — written by the model, not from your files, not fact-checked
        </p>
      )}
      {fromGeneral && (
        <div className="chat-general">
          <p className="chat-general-label">
            <Icon name="globe" size={14} /> From general knowledge — not from your files, and not fact-checked
          </p>
          <Markdown text={fromGeneral} onCite={() => {}} />
        </div>
      )}
      <div className="answer-foot">
        <span className="small muted">
          {m.model_used}
          {m.seconds ? ` · ${m.seconds}s` : ""}
          {fromFiles && sources.length ? ` · checked against your sources${removed ? `, ${removed} unsupported item${removed === 1 ? "" : "s"} removed` : ""}` : ""}
        </span>
        <span className="chat-foot-actions">
          {removed > 0 && (
            <button className="link small" onClick={() => setShowRemoved(!showRemoved)}>
              What was removed
            </button>
          )}
          {sources.length > 0 && (
            <button className="link small" onClick={onToggle} aria-expanded={open}>
              {open ? "Hide sources" : `Sources (${sources.length})`}
            </button>
          )}
        </span>
      </div>
      {showRemoved && removed > 0 && (
        <ul className="small muted">
          {m.checks.removed.map((r, i) => (
            <li key={i}>{r}</li>
          ))}
        </ul>
      )}
      {open && (
        <ol className="answer-sources chat-sources">
          {sources.map(([n, s]) => (
            <li
              key={n}
              data-src={`${m.id}:${n}`}
              className={`card ${lit === `${m.id}:${n}` ? "lit" : ""} ${s.cited ? "" : "unused"}`}
            >
              <div className="src-top">
                <span className="cite static">{n}</span>
                <strong>{s.topic_title || "Not in a topic yet"}</strong>
                {s.section && <span className="muted small">› {s.section}</span>}
                {!s.cited && <span className="src-unused">not used in the answer</span>}
              </div>
              <Formatted text={s.text} collapseAt={5} />
              <ul className="point-sources">
                <SourceChip sourceId={s.source_id} fileName={s.file_name} page={s.page_number} />
                {s.topic_id && (
                  <li>
                    <button className="link small" onClick={() => onOpenTopic(s.topic_id, s.point_id)}>
                      Open topic
                    </button>
                  </li>
                )}
              </ul>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
