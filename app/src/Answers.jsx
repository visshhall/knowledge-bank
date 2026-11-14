/**
 * Answers.jsx — Phase 4 "answer pages": ask a question, get a cited answer
 * written only from your own files.
 *
 * WHAT:  - A question box. Asking starts a background job in the engine
 *          (POST /answer/ask) and this screen shows its live stage
 *          ("Finding the best passages…", "Writing…", "Checking every fact…").
 *        - The answer: Markdown with numbered source chips. Clicking a chip
 *          highlights that source below.
 *        - "Checked against your sources": how many unsupported items the
 *          fact checker removed (expand to see which).
 *        - Sources: every passage the answer could use, numbered, with its
 *          topic, document part, text, an "Open page" chip (original PDF at
 *          that page) and "Open topic". Sources the answer actually cited
 *          are marked.
 *        - Recent questions: earlier answers reopen instantly (saved).
 * WHY:   The owner wants the bank to answer like a colleague who has read
 *        all his documents, but with proof for every line.
 * WHEN:  The "Answers" screen in the side rail, or the "Write an answer"
 *        row in Ctrl+K search (which passes the question in).
 * CONNECTED TO: bridge.js → /answer/ask, /answer/status, /answers, /answer,
 *        /answer/delete (server.py → answers.py); Formatted.jsx (Markdown,
 *        Formatted); SourceChip.jsx; App.jsx (onOpenTopic, initial question).
 */
import { useEffect, useRef, useState } from "react";
import Icon from "./icons.jsx";
import SourceChip from "./SourceChip.jsx";
import { Formatted, Markdown } from "./Formatted.jsx";
import { kb, usePoll } from "./bridge.js";

export default function Answers({ initial, onOpenTopic }) {
  const [q, setQ] = useState("");
  const [answerId, setAnswerId] = useState(null);
  const [answer, setAnswer] = useState(null);
  const [notice, setNotice] = useState("");
  const [lit, setLit] = useState(null);
  const [showChecks, setShowChecks] = useState(false);
  const [job] = usePoll("/answer/status", 900);
  const [recent, reloadRecent] = usePoll("/answers", 0);
  const sourcesRef = useRef(null);
  const started = useRef(null);

  async function ask(question) {
    const text = (question ?? q).trim();
    setNotice("");
    const r = await kb.post("/answer/ask", { question: text });
    if (r.error || r.ok === false) setNotice(r.error || r.message);
    else {
      started.current = text;
      setAnswer(null);
      setAnswerId(null);
    }
  }

  // A question passed in from Ctrl+K search: fill the box and ask at once.
  useEffect(() => {
    if (initial?.question) {
      setQ(initial.question);
      ask(initial.question);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initial]);

  // When the job finishes, show the new answer.
  useEffect(() => {
    if (job?.state === "done" && job.answer_id && started.current === job.question) {
      started.current = null;
      setAnswerId(job.answer_id);
      reloadRecent();
    }
    if (job?.state === "error" && started.current === job.question) {
      started.current = null;
      setNotice(job.message);
    }
  }, [job, reloadRecent]);

  // Opening the screen shows the most recent answer straight away.
  useEffect(() => {
    if (!answerId && !initial?.question && recent?.answers?.length && job?.state !== "running") {
      setAnswerId(recent.answers[0].id);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [recent]);

  useEffect(() => {
    if (!answerId) return;
    kb.get("/answer", { id: answerId }).then((r) => !r.error && setAnswer(r));
    setShowChecks(false);
    setLit(null);
  }, [answerId]);

  function cite(n) {
    setLit(String(n));
    sourcesRef.current?.querySelector(`[data-n="${n}"]`)?.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  async function remove(id) {
    await kb.post("/answer/delete", { id });
    if (id === answerId) {
      setAnswerId(null);
      setAnswer(null);
    }
    reloadRecent();
  }

  const running = job?.state === "running";

  return (
    <div className="answers">
      <header className="page-head">
        <h1>Answers</h1>
        <p className="lede">
          Ask anything. The answer is written only from your files, every sentence is cited, and facts are checked
          against the sources before you see them.
        </p>
      </header>

      <form
        className="ask-box card"
        onSubmit={(e) => {
          e.preventDefault();
          ask();
        }}
      >
        <Icon name="answer" size={22} />
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="e.g. How do I contain an RDP brute force that ended in a successful login?"
          aria-label="Your question"
        />
        <button type="submit" disabled={running || q.trim().length < 4}>
          <Icon name="sparkle" size={18} />
          {running ? "Answering…" : "Ask"}
        </button>
      </form>
      {notice && <p className="notice error">{notice}</p>}

      <div className="answers-layout">
        <div className="answers-main">
          {running && (
            <section className="card answer-wait" aria-live="polite">
              <p className="answer-q">{job.question}</p>
              <div className="thinking" aria-hidden="true">
                <span />
                <span />
                <span />
              </div>
              <p className="muted">{job.stage}</p>
              <p className="small muted">A local model on a 4 GB GPU takes about 20–60 seconds.</p>
            </section>
          )}

          {!running && answer && (
            <>
              <section className="card answer-card">
                <p className="answer-q">{answer.question}</p>
                <div className="answer-body">
                  <Markdown text={answer.answer} onCite={cite} />
                </div>
                <div className="answer-foot">
                  <button className="link" onClick={() => setShowChecks(!showChecks)}>
                    <Icon name="check" size={14} /> Checked against your sources
                    {answer.checks?.removed_count
                      ? `: ${answer.checks.removed_count} unsupported item${answer.checks.removed_count === 1 ? "" : "s"} removed`
                      : ": nothing needed removing"}
                  </button>
                  <span className="small muted">
                    {answer.model_used} · {answer.seconds}s
                  </span>
                </div>
                {showChecks && answer.checks?.removed_count > 0 && (
                  <ul className="small muted">
                    {answer.checks.removed.map((r, i) => (
                      <li key={i}>{r}</li>
                    ))}
                  </ul>
                )}
              </section>

              <h2 className="sources-head">Sources</h2>
              <ol className="answer-sources" ref={sourcesRef}>
                {Object.entries(answer.sources).map(([n, s]) => (
                  <li key={n} data-n={n} className={`card ${lit === n ? "lit" : ""} ${s.cited ? "" : "unused"}`}>
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
            </>
          )}

          {!running && !answer && (
            <section className="card answer-empty">
              <p>Your answer will appear here, with every source you can open at its page.</p>
            </section>
          )}
        </div>

        <aside className="card recent">
          <h2>Recent questions</h2>
          {recent?.answers?.length ? (
            <ul>
              {recent.answers.map((a) => (
                <li key={a.id} className={a.id === answerId ? "on" : ""}>
                  <button className="recent-q" onClick={() => setAnswerId(a.id)}>
                    {a.question}
                  </button>
                  <button className="link small" onClick={() => remove(a.id)} aria-label={`Delete "${a.question}"`}>
                    Delete
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <p className="muted small">Questions you ask are saved here.</p>
          )}
        </aside>
      </div>
    </div>
  );
}
