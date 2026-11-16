/**
 * MemoryPanel.jsx — v0.14 "Memory": the facts your assistant knows about you (a panel in Chat).
 *
 * WHAT:  A plain list you control.
 *        - A switch "Use my memory in Free chat" (off keeps the list but stops using it).
 *        - Add a fact (a short sentence), pin it (pinned facts are always used first), edit it,
 *          delete it, or "Forget everything" (asks twice).
 *        - "Suggest from this chat": the model reads what YOU wrote in the open chat and proposes up
 *          to 5 lasting facts. Each one is only saved if you press "Remember"; "Skip" drops it.
 *        - A small meter shows how much of the memory fits into one reply (a 4 GB-card model has a
 *          small window, so the newest and pinned facts win when there are many).
 * WHY:   The owner wants an assistant that knows him without it secretly learning things he cannot
 *        see. Everything here is visible and editable; nothing is added without his click.
 * WHEN:  Opened from the "Memory" button in the Chat bar, or from "Remember" under one of your
 *        messages (which pre-fills the box with that message so you can shorten it).
 * CONNECTED TO: bridge.js → engine /memory, /memory/add, /memory/update, /memory/delete,
 *        /memory/clear, /memory/enable, /memory/suggest, /memory/suggest/status (server.py →
 *        memory.py); Chat.jsx (renders this).
 */
import { useEffect, useState } from "react";
import { kb, usePoll } from "./bridge.js";

export default function MemoryPanel({ chatId, prefill, onPrefillUsed }) {
  const [data, reload] = usePoll("/memory", 0);
  const [suggest, reloadSuggest] = usePoll("/memory/suggest/status", 0);
  const [draft, setDraft] = useState("");
  const [pinNew, setPinNew] = useState(false);
  const [editing, setEditing] = useState(null); // { id, text }
  const [confirmClear, setConfirmClear] = useState(false);
  const [notice, setNotice] = useState("");
  const [proposals, setProposals] = useState([]);
  const [reading, setReading] = useState(false);

  // "Remember" under a message pre-fills the box.
  useEffect(() => {
    if (prefill) {
      setDraft(prefill.slice(0, 300));
      onPrefillUsed?.();
    }
  }, [prefill, onPrefillUsed]);

  // While the model reads the chat, check on it every second.
  useEffect(() => {
    if (!reading) return undefined;
    const id = setInterval(reloadSuggest, 1000);
    return () => clearInterval(id);
  }, [reading, reloadSuggest]);
  useEffect(() => {
    if (!reading || !suggest) return;
    if (suggest.state === "done") {
      setReading(false);
      setProposals(suggest.proposals ?? []);
      if (!(suggest.proposals ?? []).length) setNotice("Nothing new worth remembering in that chat.");
    } else if (suggest.state === "error") {
      setReading(false);
      setNotice(suggest.message || "Couldn't read the chat.");
    }
  }, [suggest, reading]);

  const facts = data?.facts ?? [];

  async function add(text, pinned = false) {
    const r = await kb.post("/memory/add", { text, pinned });
    if (r.error || r.ok === false) {
      setNotice(r.message || r.error);
      return false;
    }
    setNotice("");
    reload();
    return true;
  }

  async function saveEdit() {
    const r = await kb.post("/memory/update", { id: editing.id, text: editing.text });
    if (r.error || r.ok === false) {
      setNotice(r.message || r.error);
      return;
    }
    setEditing(null);
    setNotice("");
    reload();
  }

  async function startSuggest() {
    setNotice("");
    setProposals([]);
    const r = await kb.post("/memory/suggest", { chat_id: chatId });
    if (r.error || r.ok === false) {
      setNotice(r.message || r.error);
      return;
    }
    setReading(true);
  }

  async function forgetAll() {
    if (!confirmClear) {
      setConfirmClear(true);
      return;
    }
    setConfirmClear(false);
    await kb.post("/memory/clear", {});
    reload();
  }

  return (
    <section className="card memory-panel" aria-label="Memory about you">
      <p className="muted small">
        Short facts your assistant knows about you, used in Free chat so you don't repeat yourself. Only you add
        to this list — nothing is saved unless you press a button. It stays on this laptop.
      </p>

      <label className="memory-switch">
        <input
          type="checkbox"
          checked={data?.enabled ?? true}
          onChange={async (e) => {
            await kb.post("/memory/enable", { on: e.target.checked });
            reload();
          }}
        />
        Use my memory in Free chat
        <span className="muted small">
          {" "}
          · {facts.length} fact{facts.length === 1 ? "" : "s"}, {data?.used_chars ?? 0} of {data?.limit_chars ?? 1400} characters fit one reply
        </span>
      </label>

      <form
        className="memory-add"
        onSubmit={async (e) => {
          e.preventDefault();
          if (await add(draft, pinNew)) {
            setDraft("");
            setPinNew(false);
          }
        }}
      >
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          maxLength={300}
          placeholder="e.g. I sell 3D-printed planters and lamps under the brand Ākāra"
          aria-label="A new fact to remember"
        />
        <label className="small">
          <input type="checkbox" checked={pinNew} onChange={(e) => setPinNew(e.target.checked)} /> Pin
        </label>
        <button type="submit" disabled={draft.trim().length < 3}>
          Remember
        </button>
      </form>

      {notice && <p className="notice error">{notice}</p>}

      {facts.length > 0 ? (
        <ul className="memory-list">
          {facts.map((f) => (
            <li key={f.id}>
              {editing?.id === f.id ? (
                <form
                  className="memory-edit"
                  onSubmit={(e) => {
                    e.preventDefault();
                    saveEdit();
                  }}
                >
                  <input autoFocus value={editing.text} maxLength={300} onChange={(e) => setEditing({ ...editing, text: e.target.value })} aria-label="Edit the fact" />
                  <button type="submit" className="small-btn">Save</button>
                  <button type="button" className="link small" onClick={() => setEditing(null)}>Cancel</button>
                </form>
              ) : (
                <>
                  <span className="memory-text">
                    {f.pinned && <span className="pin" title="Pinned: always used first">📌 </span>}
                    {f.text}
                  </span>
                  <span className="memory-actions">
                    <button className="link small" onClick={async () => { await kb.post("/memory/update", { id: f.id, pinned: !f.pinned }); reload(); }}>
                      {f.pinned ? "Unpin" : "Pin"}
                    </button>
                    <button className="link small" onClick={() => setEditing({ id: f.id, text: f.text })}>Edit</button>
                    <button className="link small" onClick={async () => { await kb.post("/memory/delete", { id: f.id }); reload(); }}>Delete</button>
                  </span>
                </>
              )}
            </li>
          ))}
        </ul>
      ) : (
        <p className="muted small">Nothing remembered yet.</p>
      )}

      <div className="memory-foot">
        <button className="secondary" onClick={startSuggest} disabled={!chatId || reading}>
          {reading ? "Reading this chat…" : "Suggest from this chat"}
        </button>
        {facts.length > 0 && (
          <button className="link small" onClick={forgetAll}>
            {confirmClear ? "Really forget everything?" : "Forget everything"}
          </button>
        )}
        {!chatId && <span className="muted small">Open a chat with some messages from you to get suggestions.</span>}
      </div>

      {proposals.length > 0 && (
        <div className="memory-proposals">
          <p className="small">
            <strong>Worth remembering?</strong> These come from your messages in this chat. Nothing is saved until you press Remember.
          </p>
          <ul className="memory-list">
            {proposals.map((p) => (
              <li key={p}>
                <span className="memory-text">{p}</span>
                <span className="memory-actions">
                  <button className="small-btn" onClick={async () => { if (await add(p)) setProposals((cur) => cur.filter((x) => x !== p)); }}>
                    Remember
                  </button>
                  <button className="link small" onClick={() => setProposals((cur) => cur.filter((x) => x !== p))}>Skip</button>
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
