/**
 * Lesson.jsx — a topic's automatic visual lesson, taught one step at a time.
 *
 * WHAT:  - Step dots + "Step n of N", the step's title and short explanation
 *          (with source chips), and its diagram (Diagrams.jsx).
 *        - Back / Next buttons; arrow keys also move between steps.
 *        - A short quiz at the end, checked instantly, with the source of
 *          each answer.
 *        - A "Checked against your sources" note: how many invented items
 *          the fact checker removed (expand to see what), and which steps
 *          were calculated from data rather than written by AI.
 *        - "Regenerate lesson" to redesign it.
 * WHY:   The owner wants the app to teach "like a teacher": one idea at a
 *        time, with the right picture for it, and without mistakes. The
 *        verification note makes the checking visible instead of a promise.
 * WHEN:  Shown on the Lesson tab of a topic (Topics.jsx), which is the first
 *        tab whenever a lesson exists.
 * CONNECTED TO: bridge.js → GET /lesson, POST /lesson/regenerate,
 *        GET /write/status (server.py → lessons.py, writer.py);
 *        Diagrams.jsx; Topics.jsx passes onCite(marker, pointId), which opens the source panel.
 */
import { useEffect, useState } from "react";
import Visual from "./Diagrams.jsx";
import Icon from "./icons.jsx";
import { kb, usePoll } from "./bridge.js";

export default function Lesson({ topicId, onCite }) {
  const [data, reload] = usePoll("/lesson", 0, { id: topicId });
  const [write] = usePoll("/write/status", 2000);
  const [step, setStep] = useState(0);
  const [notice, setNotice] = useState("");
  const [showChecks, setShowChecks] = useState(false);

  const lesson = data?.lesson;
  const steps = lesson?.steps ?? [];
  const quiz = lesson?.quiz ?? [];
  const total = steps.length + (quiz.length ? 1 : 0); // the quiz is the last "step"
  const regenerating = write?.state === "running";

  // When a regeneration finishes, show the new lesson from the start.
  useEffect(() => {
    if (write?.state === "done") {
      reload();
      setStep(0);
    }
  }, [write?.state, reload]);

  // Left/right arrow keys move between steps (when not typing in a field).
  useEffect(() => {
    function onKey(e) {
      if (e.target.closest?.("input, textarea")) return;
      if (e.key === "ArrowRight") setStep((s) => Math.min(s + 1, total - 1));
      if (e.key === "ArrowLeft") setStep((s) => Math.max(s - 1, 0));
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [total]);

  async function regenerate() {
    setNotice("");
    const r = await kb.post("/lesson/regenerate", { topic_id: topicId });
    if (r.error || r.ok === false) setNotice(r.error || r.message);
  }

  if (!data) return <p className="muted">Loading lesson…</p>;
  if (!lesson) {
    return (
      <section className="card lesson-empty">
        <p>No lesson for this topic yet. Lessons are designed automatically when articles are written.</p>
        <button onClick={regenerate} disabled={regenerating}>
          <Icon name="sparkle" size={18} />
          {regenerating ? "Working…" : "Design lesson now"}
        </button>
        {notice && <p className="notice error">{notice}</p>}
      </section>
    );
  }

  const current = steps[step];
  // Source chips carry the lesson's own marker numbers; translate each to the
  // point id the Topics side panel understands.
  const cite = (n) => onCite?.(String(n), lesson.citations?.[String(n)]);
  const removed = data.checks?.removed_count ?? 0;

  return (
    <div className="lesson">
      <div className="lesson-top">
        <ol className="lesson-dots" aria-label="Lesson steps">
          {Array.from({ length: total }, (_, i) => (
            <li key={i}>
              <button
                className={`dot ${i === step ? "on" : i < step ? "seen" : ""}`}
                onClick={() => setStep(i)}
                aria-label={i < steps.length ? `Step ${i + 1}: ${steps[i].title}` : "Quiz"}
                aria-current={i === step ? "step" : undefined}
              >
                {i < steps.length ? i + 1 : "?"}
              </button>
            </li>
          ))}
        </ol>
        <button className="ghost" onClick={regenerate} disabled={regenerating} title="Design this lesson again">
          <Icon name="refresh" size={16} />
          {regenerating ? "Redesigning…" : "Regenerate lesson"}
        </button>
      </div>
      {notice && <p className="notice error">{notice}</p>}

      {current ? (
        <section className="card lesson-step" key={step}>
          <p className="lesson-count">
            Step {step + 1} of {steps.length}
            {current.computed && <span className="computed-badge">Calculated from your data</span>}
          </p>
          <h2>{current.title}</h2>
          {current.text && (
            <p className="lesson-text">
              {current.text}
              {current.cites?.map((n) => (
                <button key={n} className="cite" onClick={() => cite(n)} aria-label={`Show source ${n}`}>
                  {n}
                </button>
              ))}
            </p>
          )}
          {current.visual && (
            <div className="lesson-visual">
              <Visual spec={current.visual} />
            </div>
          )}
        </section>
      ) : (
        <Quiz quiz={quiz} onCite={cite} />
      )}

      <div className="lesson-nav">
        <button className="secondary" onClick={() => setStep(step - 1)} disabled={step === 0}>
          <Icon name="arrow-left" size={16} />
          Back
        </button>
        <button onClick={() => setStep(step + 1)} disabled={step >= total - 1}>
          {step === steps.length - 1 && quiz.length ? "Take the quiz" : "Next step"}
        </button>
      </div>

      <section className="lesson-checks">
        <button className="link" onClick={() => setShowChecks(!showChecks)}>
          <Icon name="check" size={14} /> Checked against your sources
          {removed ? `: ${removed} unsupported item${removed === 1 ? "" : "s"} removed` : ": nothing needed removing"}
        </button>
        {showChecks && removed > 0 && (
          <ul className="small muted">
            {data.checks.removed.map((r, i) => (
              <li key={i}>{r}</li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

/** End-of-lesson quiz: pick an answer, see right/wrong and its source. */
function Quiz({ quiz, onCite }) {
  const [picked, setPicked] = useState({});
  const score = quiz.filter((q, i) => picked[i] === q.answer).length;
  const done = Object.keys(picked).length === quiz.length;
  return (
    <section className="card lesson-step quiz">
      <p className="lesson-count">Quick check</p>
      <h2>Test yourself</h2>
      {quiz.map((q, i) => (
        <fieldset key={i} className="quiz-q">
          <legend>
            {i + 1}. {q.q}
          </legend>
          <div className="quiz-options">
            {q.options.map((o, j) => {
              const state =
                picked[i] === undefined ? "" : j === q.answer ? "right" : picked[i] === j ? "wrong" : "";
              return (
                <button
                  key={j}
                  className={`quiz-option ${state}`}
                  onClick={() => picked[i] === undefined && setPicked({ ...picked, [i]: j })}
                  aria-pressed={picked[i] === j}
                >
                  {o}
                </button>
              );
            })}
          </div>
          {picked[i] !== undefined && q.cite && (
            <button className="link small" onClick={() => onCite(q.cite)}>
              See the source for this answer
            </button>
          )}
        </fieldset>
      ))}
      {done && (
        <p className="quiz-score">
          {score} of {quiz.length} correct
        </p>
      )}
    </section>
  );
}
