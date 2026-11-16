/**
 * Chat.jsx — v0.11 "Chat": talk to your library in saved conversations.
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
 *        /models/choices, /models/select (server.py → chat.py,
 *        modelpick.py); Formatted.jsx (Markdown, Formatted); SourceChip.jsx;
 *        App.jsx (onOpenTopic, onOpenSetup).
 */
import { useCallback, useEffect, useRef, useState } from "react";
import Icon from "./icons.jsx";
import SourceChip from "./SourceChip.jsx";
import { Formatted, Markdown } from "./Formatted.jsx";
import { kb, usePoll } from "./bridge.js";

/** The line chat.py puts in front of everything that is NOT from the files. */
const GENERAL_MARK = "From general knowledge (not from your files):";

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
  const [general, setGeneral] = useState(false); // "Also use general knowledge" for the next message
  const [notice, setNotice] = useState("");
  const [renaming, setRenaming] = useState(null); // { id, value }
  const [confirmDelete, setConfirmDelete] = useState(null); // chat id waiting for a second click
  const [openSources, setOpenSources] = useState(() => new Set()); // message ids with Sources open
  const [lit, setLit] = useState(null); // "messageId:n" of the highlighted source
  const [pendingUser, setPendingUser] = useState(null); // text shown at once while the engine stores it
  const [job] = usePoll("/chat/status", 700);
  const [list, reloadList] = usePoll("/chat/list", 0, { q: search });
  const [models, reloadModels] = usePoll("/models/choices", 0);
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
    if (!r.error) setChat(r);
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
    const r = await kb.post("/chat/send", { chat_id: activeId, text: body, general });
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

  return (
    <div className="chat">
      <header className="page-head">
        <h1>Chat</h1>
        <p className="lede">
          Talk to your library. Answers come from your own files with every source cited and checked; follow-up
          questions remember the conversation. Everything stays on this laptop.
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
            <button className="link small" onClick={onOpenSetup}>
              Download and compare models
            </button>
          </div>

          {notice && <p className="notice error">{notice}</p>}

          <div className="chat-thread" ref={threadRef} aria-live="polite">
            {empty && (
              <section className="card chat-empty">
                <p>Ask anything about what is in your files. For example:</p>
                <ul>
                  {STARTERS.map((s) => (
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
                <div key={m.id} className="msg-user">
                  {m.content}
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
                  {job.live ? " Facts are checked when it finishes." : " A local model on a 4 GB card takes about 20–60 seconds."}
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
              placeholder="Ask about your files… (Enter to send, Shift+Enter for a new line)"
              aria-label="Your message"
            />
            <div className="chat-composer-foot">
              <label className="chat-general-switch" title="When your files don't cover the question, let the model use what it knows. That part is labelled and is not fact-checked.">
                <input type="checkbox" checked={general} onChange={(e) => setGeneral(e.target.checked)} />
                Also use general knowledge
              </label>
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
