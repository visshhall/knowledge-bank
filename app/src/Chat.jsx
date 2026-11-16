/**
 * Chat.jsx — the home screen: a ChatGPT/Claude-style conversation with your library and the model.
 *
 * v0.16: the app learns from use. Under each Free-chat answer: thumbs up / down and "Correct" (rewrite the
 *        answer the way you wanted it). Copy and Regenerate count as signals too. Nothing is asked of you;
 *        training.py turns good answers and corrections into training examples (see the Learning screen).
 *
 * v0.15 (chat-first shell): the chat list moved into the sidebar (Sidebar.jsx), and this screen is now
 *        the whole stage: a slim top bar (chat title, model, persona, Memory), a centred conversation,
 *        and a rounded message box at the bottom with an attach button (add files to the library, or
 *        drop them anywhere on the chat), an "add a web page" button, the answer-mode picker, and a
 *        round Send / Stop button. An empty chat greets you with suggestion cards. Under messages:
 *        Copy, Regenerate (last answer), Edit (last message of yours) and Remember.
 *
 * v0.14: Memory — short facts about you that Free chat uses (MemoryPanel.jsx); "Remember" under a message.
 * v0.12: three answer modes saved per chat — "My files" (cited, fact-checked), "Files + general"
 *        (files first, then a labelled general part) and "Free chat" (no files, with a persona).
 * v0.11: saved conversations, streaming answers, Stop, sources under each answer.
 *
 * WHAT:  - "My files": every answer is written only from passages of your own files, cited [1]…[n]
 *          and fact-checked (numbers, technique IDs, commands must be in the cited sources). "Sources"
 *          under an answer lists the passages with an "Open page" chip and "Open topic".
 *        - "Files + general": when your files don't cover it, the model may add a clearly labelled box
 *          "From general knowledge (not from your files)" — not fact-checked.
 *        - "Free chat": talk about anything; a persona (Assistant, Ākāra copywriter, Coding helper,
 *          Tutor, Security analyst, or your own) shapes the answers. Labelled "not from your files".
 *        - Answers stream in as written; Stop keeps what was written. Enter sends, Shift+Enter = new line.
 *        - Regenerate / Edit take back the last exchange (POST /chat/undo) and ask again / put your
 *          message back in the box. Not available while a reply is being written.
 * WHY:   The owner asked for the whole app to feel like a chat app. Everything runs on this laptop.
 * WHEN:  The "chat" screen of App.jsx — the screen the app opens on.
 * CONNECTED TO: App.jsx (activeId, onActiveChange, newChatTick, onListChanged, onOpenTopic, onOpenSetup);
 *        Sidebar.jsx (shows the chat list; it refreshes when we call onListChanged);
 *        bridge.js → engine /chat/get, /chat/send, /chat/status, /chat/stop, /chat/undo, /training/signal, /training/correct, /chat/personas,
 *        /chat/persona/save, /chat/persona/delete, /models/choices, /models/select, /library/add,
 *        /crawl/start, /crawl/status, /crawl/stop (server.py → chat.py, modelpick.py, importer.py,
 *        crawler.py); MemoryPanel.jsx; Formatted.jsx (Markdown, Formatted); SourceChip.jsx; icons.jsx.
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
  { id: "free", label: "Free chat", hint: "No files. Talk to the model about anything. Not cited, not fact-checked." },
];

/** Suggestion cards on an empty chat — what you can ask in each mode. */
const STARTERS = {
  library: [
    "How do I detect and contain an RDP brute force that ended in a successful login?",
    "Explain Kerberoasting step by step and which Windows events show it.",
    "Which KQL queries in my files help find lateral movement?",
  ],
  both: [
    "Summarise what my files say about phishing triage, then add anything important they miss.",
    "Compare pass-the-hash and pass-the-ticket using my files first.",
    "What should a SOC analyst check first on a suspicious PowerShell alert?",
  ],
  free: [
    "Explain how a heat pump works in simple words.",
    "Write a polite follow-up email to a customer who hasn't replied for a week.",
    "Help me plan my week as a small-business owner.",
  ],
};

/** Web page reading choices in the "add a web page" popover (same limits as the Library card). */
const WEB_SCOPES = [
  { id: "page", label: "This page only", pages: 1 },
  { id: "section", label: "This page and the pages under it", pages: 30 },
  { id: "site", label: "The whole site", pages: 100 },
];

/** Splits an answer into the part from the files and the general-knowledge part. */
function splitGeneral(text) {
  const at = text.indexOf(GENERAL_MARK);
  if (at < 0) return [text, ""];
  return [text.slice(0, at).trim(), text.slice(at + GENERAL_MARK.length).trim()];
}

export default function Chat({ activeId, onActiveChange, newChatTick, onListChanged, onOpenTopic, onOpenSetup }) {
  const [chat, setChat] = useState(null); // the open chat's messages
  const [draft, setDraft] = useState("");
  const [mode, setMode] = useState("library"); // how the next message is answered: library | both | free
  const [personaId, setPersonaId] = useState(null); // who answers in Free chat (null = the Assistant)
  const [editing, setEditing] = useState(null); // the persona being written: { id, name, prompt, builtin }
  const [panel, setPanel] = useState(null); // which panel is open under the top bar: "memory" | "personas" | null
  const [prefill, setPrefill] = useState(""); // text for a new memory fact, from "Remember" under a message
  const clearPrefill = useCallback(() => setPrefill(""), []);
  const [notice, setNotice] = useState(""); // an error line above the message box
  const [info, setInfo] = useState(""); // a quiet confirmation (files added, copied …)
  const [openSources, setOpenSources] = useState(() => new Set()); // message ids with Sources open
  const [lit, setLit] = useState(null); // "messageId:n" of the highlighted source
  const [pendingUser, setPendingUser] = useState(null); // text shown at once while the engine stores it
  const [webOpen, setWebOpen] = useState(false); // the "add a web page" popover
  const [webUrl, setWebUrl] = useState("");
  const [webScope, setWebScope] = useState("page");
  const [dragging, setDragging] = useState(false); // files are being dragged over the window
  const [copied, setCopied] = useState(null); // message id whose Copy was just pressed
  const [rated, setRated] = useState({}); // message id -> "up" | "down" (this session), so the thumb stays lit
  const [correcting, setCorrecting] = useState(null); // { id, text } — an answer being rewritten
  const [job] = usePoll("/chat/status", 700);
  const [crawl, reloadCrawl] = usePoll("/crawl/status", 1500);
  const [models, reloadModels] = usePoll("/models/choices", 0);
  const [personaData, reloadPersonas] = usePoll("/chat/personas", 0);
  const personas = personaData?.personas ?? [];
  const awaiting = useRef(null); // chat id we are waiting on a reply for
  const sentAt = useRef(0); // when we pressed Send (seconds); ignores a stale "done" from the previous reply
  const activeRef = useRef(activeId); // always the open chat, for callbacks that outlive a render
  activeRef.current = activeId;
  const threadRef = useRef(null);
  const boxRef = useRef(null);
  const dragDepth = useRef(0);

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

  // "New chat" (button or Ctrl+Shift+O): clear the screen and put the cursor in the box.
  useEffect(() => {
    if (!newChatTick) return;
    setChat(null);
    setDraft("");
    setNotice("");
    setInfo("");
    setPendingUser(null);
    boxRef.current?.focus();
  }, [newChatTick]);

  // Returning to Chat while a reply is still being written: show it again.
  useEffect(() => {
    if (job?.state === "running" && job.chat_id && !awaiting.current) {
      awaiting.current = job.chat_id;
      if (!activeRef.current) onActiveChange(job.chat_id);
    }
  }, [job, onActiveChange]);

  // When the reply is finished, load the saved conversation (only if that chat is still the open one).
  useEffect(() => {
    if (!awaiting.current || !job) return;
    if (job.started_at && job.started_at < sentAt.current - 1) return; // still the previous reply's status
    if (job.state === "done" || job.state === "error") {
      const id = awaiting.current;
      awaiting.current = null;
      setPendingUser(null);
      if (job.state === "error") setNotice(job.message || "The reply could not be written.");
      if (id === activeRef.current) loadChat(id);
      onListChanged();
    }
  }, [job, loadChat, onListChanged]);

  // Keep the newest text in view while the reply is written.
  const running = job?.state === "running";
  const liveHere = running && job.chat_id === activeId;
  useEffect(() => {
    const el = threadRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [chat, job?.live, pendingUser]);

  // The message box grows with what is typed, up to about eight lines.
  useEffect(() => {
    const el = boxRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }, [draft]);

  // A confirmation line fades away by itself.
  useEffect(() => {
    if (!info) return undefined;
    const t = setTimeout(() => setInfo(""), 6000);
    return () => clearTimeout(t);
  }, [info]);

  async function send(text) {
    const body = (text ?? draft).trim();
    if (body.length < 2 || running) return;
    setNotice("");
    setInfo("");
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
    if (r.chat_id !== activeId) onActiveChange(r.chat_id);
    else loadChat(r.chat_id);
    onListChanged();
  }

  /** Take back the last question and answer; resolves to the question's text (or null). */
  async function takeBack(reason) {
    if (!activeId || running) return null;
    const r = await kb.post("/chat/undo", { chat_id: activeId, reason });
    if (r.error || r.ok === false) {
      setNotice(r.error || r.message);
      return null;
    }
    await loadChat(activeId);
    onListChanged();
    return r.text;
  }

  /** Regenerate: ask the same question again for a fresh answer. */
  async function regenerate() {
    const text = await takeBack("regen"); // Regenerate = "that answer was not good" for the learning signals
    if (text) send(text);
  }

  /** Edit: put your last message back in the box to change and send again. */
  async function editLast() {
    const text = await takeBack("edit"); // Edit = neutral
    if (text) {
      setDraft(text);
      boxRef.current?.focus();
    }
  }

  /** Tell the engine how the owner reacted to an answer (thumbs, Copy). Quiet: failures are ignored. */
  function signal(id, kind) {
    kb.post("/training/signal", { message_id: id, signal: kind });
  }

  function rate(id, kind) {
    setRated((cur) => ({ ...cur, [id]: kind }));
    signal(id, kind);
  }

  async function saveCorrection() {
    if (!correcting) return;
    const r = await kb.post("/training/correct", { message_id: correcting.id, text: correcting.text });
    if (r.ok === false || r.error) {
      setNotice(r.message || r.error);
      return;
    }
    setCorrecting(null);
    setInfo("Saved. This corrected answer will be used to teach the model your way.");
    loadChat(activeId);
  }

  async function copyText(id, text, isAnswer = false) {
    if (isAnswer) signal(id, "copy");
    try {
      await navigator.clipboard.writeText(text);
      setCopied(id);
      setTimeout(() => setCopied((c) => (c === id ? null : c)), 1500);
    } catch {
      setNotice("Copying isn't allowed here. Select the text and press Ctrl+C instead.");
    }
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

  /** Add files to the library (from the paperclip or dropped on the chat). They become searchable in "My files". */
  async function addFiles(paths) {
    const list = (paths ?? []).filter(Boolean);
    if (!list.length) return;
    const r = await kb.post("/library/add", { paths: list });
    if (r.error || r.ok === false) {
      setNotice(r.error || r.message || "The files could not be added.");
      return;
    }
    const bits = [];
    if (r.added) bits.push(`${r.added} added to your library`);
    if (r.duplicates || r.already_in_bank) bits.push(`${(r.duplicates || 0) + (r.already_in_bank || 0)} already there`);
    if (r.unsupported) bits.push(`${r.unsupported} not a supported type`);
    setInfo(
      (bits.join(", ") || "Nothing new to add") +
        (r.added ? ". They are read in the background; ask about them in “My files” when done." : ".")
    );
  }

  async function readWebPage() {
    setNotice("");
    const scope = WEB_SCOPES.find((s) => s.id === webScope);
    const r = await kb.post("/crawl/start", { url: webUrl, scope: webScope, max_pages: scope.pages });
    if (r.error || r.ok === false) {
      setNotice(r.message || r.error);
      return;
    }
    reloadCrawl();
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

  // Dragging files over the window shows a drop target; dropping adds them to the library.
  function dragEvents() {
    const hasFiles = (e) => [...(e.dataTransfer?.types ?? [])].includes("Files");
    return {
      onDragEnter: (e) => {
        if (!hasFiles(e)) return;
        e.preventDefault();
        dragDepth.current += 1;
        setDragging(true);
      },
      onDragOver: (e) => hasFiles(e) && e.preventDefault(),
      onDragLeave: (e) => {
        if (!hasFiles(e)) return;
        dragDepth.current = Math.max(0, dragDepth.current - 1);
        if (!dragDepth.current) setDragging(false);
      },
      onDrop: (e) => {
        if (!hasFiles(e)) return;
        e.preventDefault();
        dragDepth.current = 0;
        setDragging(false);
        addFiles([...e.dataTransfer.files].map((f) => kb.pathForFile(f)));
      },
    };
  }

  const messages = chat?.messages ?? [];
  const lastUser = [...messages].reverse().find((m) => m.role === "user");
  const lastAssistant = [...messages].reverse().find((m) => m.role === "assistant");
  const installed = models?.installed ?? [];
  const empty = !messages.length && !pendingUser && !liveHere;
  const free = mode === "free";
  const persona = personas.find((p) => p.id === personaId) ?? personas[0];
  const crawling = crawl?.state === "running";
  const modeInfo = MODES.find((m) => m.id === mode) ?? MODES[0];

  return (
    <div className="cx" {...dragEvents()}>
      {dragging && (
        <div className="cx-drop" aria-hidden="true">
          <Icon name="upload" size={34} />
          <p>Drop files to add them to your library</p>
          <span className="muted small">Documents, slides, spreadsheets, pictures. They become searchable in “My files”.</span>
        </div>
      )}

      <header className="cx-top">
        <h1 className="cx-title" title={chat?.title}>
          {chat?.title || "New chat"}
        </h1>
        <div className="cx-top-tools">
          <label className="cx-select">
            <span className="visually-hidden">Model that writes the answers</span>
            <select
              value={installed.find((m) => m.current)?.name ?? ""}
              onChange={(e) => pickModel(e.target.value)}
              disabled={running || !installed.length}
              aria-label="Model that writes the answers"
              title="Model that writes the answers"
            >
              {!installed.some((m) => m.current) && <option value="">{models?.current ?? "…"}</option>}
              {installed.map((m) => (
                <option key={m.name} value={m.name}>
                  {m.name}
                </option>
              ))}
            </select>
          </label>
          <button className="cx-chip" onClick={onOpenSetup} title="Download more models and compare them">
            More models
          </button>
          <button
            className={`cx-chip ${panel === "memory" ? "on" : ""}`}
            onClick={() => setPanel(panel === "memory" ? null : "memory")}
            aria-expanded={panel === "memory"}
          >
            Memory
          </button>
          {free && (
            <button
              className={`cx-chip ${panel === "personas" ? "on" : ""}`}
              onClick={() => setPanel(panel === "personas" ? null : "personas")}
              aria-expanded={panel === "personas"}
            >
              Personas
            </button>
          )}
        </div>
      </header>

      {panel && (
        <div className="cx-panel">
          {panel === "memory" && <MemoryPanel chatId={activeId} prefill={prefill} onPrefillUsed={clearPrefill} />}

          {panel === "personas" && free && (
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
        </div>
      )}

      <div className="cx-scroll" ref={threadRef} aria-live="polite">
        <div className="cx-col">
          {empty && (
            <section className="cx-hello">
              <div className="cx-hello-mark" aria-hidden="true">
                <span className="wm-mark">
                  <i />
                  <i />
                  <i />
                  <i />
                </span>
              </div>
              <h2>{free ? "What would you like to talk about?" : "What do you want to look up?"}</h2>
              <p className="muted">
                {free
                  ? `Free chat${persona ? ` as “${persona.name}”` : ""}: the model answers from what it knows, not from your files.`
                  : mode === "both"
                    ? "Your files first, then a clearly labelled part from the model's own knowledge."
                    : "Answers come only from your files, with every source cited and checked."}
              </p>
              <ul className="cx-cards">
                {STARTERS[mode].map((s) => (
                  <li key={s}>
                    <button onClick={() => send(s)} disabled={running}>
                      {s}
                    </button>
                  </li>
                ))}
              </ul>
            </section>
          )}

          {messages.map((m) =>
            m.role === "user" ? (
              <div key={m.id} className="cx-user">
                <div className="msg-user">{m.content}</div>
                <div className="cx-actions">
                  <button className="cx-act" onClick={() => copyText(m.id, m.content)} title="Copy">
                    <Icon name={copied === m.id ? "check" : "copy"} size={14} /> {copied === m.id ? "Copied" : "Copy"}
                  </button>
                  {lastUser?.id === m.id && !running && (
                    <button className="cx-act" onClick={editLast} title="Change this message and send it again">
                      <Icon name="edit" size={14} /> Edit
                    </button>
                  )}
                  <button
                    className="cx-act"
                    onClick={() => {
                      setPanel("memory");
                      setPrefill(m.content);
                    }}
                    title="Save something from this message as a fact about you"
                  >
                    <Icon name="plus" size={14} /> Remember
                  </button>
                </div>
              </div>
            ) : (
              <AnswerCard
                key={m.id}
                m={m}
                open={openSources.has(m.id)}
                lit={lit}
                copied={copied === m.id}
                rating={rated[m.id]}
                correcting={correcting?.id === m.id ? correcting : null}
                onRate={(kind) => rate(m.id, kind)}
                onCorrectStart={() => setCorrecting({ id: m.id, text: m.content })}
                onCorrectChange={(text) => setCorrecting({ id: m.id, text })}
                onCorrectSave={saveCorrection}
                onCorrectCancel={() => setCorrecting(null)}
                canRegenerate={lastAssistant?.id === m.id && !running}
                onToggle={() => toggleSources(m.id)}
                onCite={(n) => cite(m.id, n)}
                onCopy={() => copyText(m.id, m.content, true)}
                onRegenerate={regenerate}
                onOpenTopic={onOpenTopic}
              />
            )
          )}

          {pendingUser && !messages.some((m) => m.role === "user" && m.content === pendingUser) && (
            <div className="cx-user">
              <div className="msg-user">{pendingUser}</div>
            </div>
          )}

          {liveHere && (
            <section className="cx-ai" aria-label="Writing the answer">
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
      </div>

      <div className="cx-dock">
        <div className="cx-col">
          {notice && (
            <p className="notice error" role="alert">
              {notice}
            </p>
          )}
          {info && !notice && (
            <p className="cx-info" role="status">
              <Icon name="check" size={14} /> {info}
            </p>
          )}

          {webOpen && (
            <section className="cx-web" aria-label="Add a web page to your library">
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  readWebPage();
                }}
              >
                <input
                  autoFocus
                  value={webUrl}
                  onChange={(e) => setWebUrl(e.target.value)}
                  placeholder="https://example.com/page"
                  aria-label="Web address"
                  disabled={crawling}
                />
                <select value={webScope} onChange={(e) => setWebScope(e.target.value)} aria-label="How much to read" disabled={crawling}>
                  {WEB_SCOPES.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.label}
                    </option>
                  ))}
                </select>
                {crawling ? (
                  <button type="button" className="secondary small-btn" onClick={() => kb.post("/crawl/stop", {}).then(reloadCrawl)}>
                    Stop
                  </button>
                ) : (
                  <button type="submit" className="small-btn" disabled={webUrl.trim().length < 4}>
                    Read it
                  </button>
                )}
                <button type="button" className="link small" onClick={() => setWebOpen(false)}>
                  Close
                </button>
              </form>
              <p className="muted small">
                {crawling
                  ? `Reading… ${crawl.fetched ?? 0} page${crawl.fetched === 1 ? "" : "s"} read, ${crawl.stored ?? 0} added to your library.`
                  : crawl?.state === "done" || crawl?.state === "stopped"
                    ? `Finished: ${crawl.stored ?? 0} page${crawl.stored === 1 ? "" : "s"} added. Ask about them in “My files”.`
                    : crawl?.state === "error"
                      ? crawl.message
                      : "The page is read on this laptop and added to your library, like a file. Pages that need JavaScript to show text can't be read."}
              </p>
            </section>
          )}

          <form
            className="cx-compose"
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
                if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                  e.preventDefault();
                  send();
                }
              }}
              rows={1}
              placeholder={
                free
                  ? `Message the model as “${persona?.name ?? "Assistant"}”…`
                  : mode === "both"
                    ? "Ask your files, with general knowledge as backup…"
                    : "Ask about your files…"
              }
              aria-label="Your message"
            />
            <div className="cx-compose-foot">
              <div className="cx-compose-left">
                <button
                  type="button"
                  className="cx-round"
                  onClick={async () => addFiles(await kb.pickFiles())}
                  title="Add files to your library (or drop them anywhere here)"
                  aria-label="Add files to your library"
                >
                  <Icon name="clip" size={18} />
                </button>
                <button
                  type="button"
                  className={`cx-round ${webOpen || crawling ? "on" : ""}`}
                  onClick={() => setWebOpen(!webOpen)}
                  title="Add a web page to your library"
                  aria-label="Add a web page to your library"
                  aria-expanded={webOpen}
                >
                  <Icon name="globe" size={18} />
                </button>
                <label className="cx-pill" title={modeInfo.hint}>
                  <span className="visually-hidden">How this chat answers</span>
                  <select value={mode} onChange={(e) => setMode(e.target.value)} disabled={running} aria-label="How this chat answers">
                    {MODES.map((m) => (
                      <option key={m.id} value={m.id}>
                        {m.label}
                      </option>
                    ))}
                  </select>
                </label>
                {free && (
                  <label className="cx-pill" title="Who answers in Free chat">
                    <span className="visually-hidden">Persona</span>
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
                  </label>
                )}
              </div>
              {running ? (
                <button type="button" className="cx-send stop" onClick={() => kb.post("/chat/stop", {})} aria-label="Stop writing" title="Stop">
                  <Icon name="stop" size={16} />
                </button>
              ) : (
                <button type="submit" className="cx-send" disabled={draft.trim().length < 2} aria-label="Send" title="Send (Enter)">
                  <Icon name="send" size={18} />
                </button>
              )}
            </div>
          </form>
          <p className="cx-fineprint muted small">
            {modeInfo.hint} Everything stays on this laptop. Shift+Enter adds a line.
          </p>
        </div>
      </div>
    </div>
  );
}

/** One answer: the text, a general-knowledge box if there is one, a checked-note, actions and the sources. */
function AnswerCard({ m, open, lit, copied, rating, correcting, onRate, onCorrectStart, onCorrectChange, onCorrectSave, onCorrectCancel, canRegenerate, onToggle, onCite, onCopy, onRegenerate, onOpenTopic }) {
  const [fromFiles, fromGeneral] = splitGeneral(m.content);
  const sources = Object.entries(m.sources ?? {});
  const removed = m.checks?.removed_count ?? 0;
  const [showRemoved, setShowRemoved] = useState(false);
  return (
    <section className="cx-ai">
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
        <span className="chat-foot-actions cx-actions">
          <button className="cx-act" onClick={onCopy} title="Copy this answer">
            <Icon name={copied ? "check" : "copy"} size={14} /> {copied ? "Copied" : "Copy"}
          </button>
          {m.mode === "free" && (
            <>
              <button
                className={`cx-act ${rating === "up" ? "lit" : ""}`}
                onClick={() => onRate("up")}
                aria-pressed={rating === "up"}
                title="Good answer — the app learns from it"
              >
                <Icon name="thumbup" size={14} />
              </button>
              <button
                className={`cx-act ${rating === "down" ? "lit" : ""}`}
                onClick={() => onRate("down")}
                aria-pressed={rating === "down"}
                title="Not good — the app will not learn from it"
              >
                <Icon name="thumbdown" size={14} />
              </button>
              <button className="cx-act" onClick={onCorrectStart} title="Rewrite this answer the way you wanted it; the app learns your way">
                <Icon name="edit" size={14} /> Correct
              </button>
            </>
          )}
          {canRegenerate && (
            <button className="cx-act" onClick={onRegenerate} title="Ask again for a fresh answer">
              <Icon name="refresh" size={14} /> Regenerate
            </button>
          )}
          {removed > 0 && (
            <button className="cx-act" onClick={() => setShowRemoved(!showRemoved)}>
              What was removed
            </button>
          )}
          {sources.length > 0 && (
            <button className="cx-act" onClick={onToggle} aria-expanded={open}>
              {open ? "Hide sources" : `Sources (${sources.length})`}
            </button>
          )}
        </span>
      </div>
      {correcting && (
        <div className="cx-correct">
          <p className="small muted">Write the answer the way you wanted it. It replaces this one and is kept as a teaching example.</p>
          <textarea
            value={correcting.text}
            onChange={(e) => onCorrectChange(e.target.value)}
            rows={8}
            aria-label="The corrected answer"
            maxLength={6000}
          />
          <div className="persona-actions">
            <button type="button" className="small-btn" onClick={onCorrectSave} disabled={correcting.text.trim().length < 2}>
              Save correction
            </button>
            <button type="button" className="secondary small-btn" onClick={onCorrectCancel}>
              Cancel
            </button>
          </div>
        </div>
      )}
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
