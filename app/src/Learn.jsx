/**
 * Learn.jsx — Phase 5 Learn mode: flashcards with spaced review and progress.
 *
 * WHAT:  Home view:
 *          - Tiles: cards due, new today, day streak, mastered.
 *          - Activity: reviews per day for the last two weeks (bars).
 *          - Progress by topic: a bar per topic (mastered / learning / new),
 *            with "Practise" (that topic's cards now) and "Open topic".
 *          - "Start review" with today's due + new cards.
 *        Review view (one card at a time):
 *          - The card flips over in 3D to show the answer. Quiz cards first
 *            ask you to pick from the options (right/wrong shown), concept
 *            cards ask you to recall, then flip.
 *          - Rate it: Again / Hard / Good / Easy, each showing when you'll
 *            see the card next ("1 day", "2 weeks"). Keys 1–4 and Space work.
 *          - "Again" puts the card back at the end of today's session.
 *          - A progress bar; a finish screen with what you did.
 * WHY:   Spaced repetition is the most reliable way to remember what you
 *        read; cards come from the fact-checked lessons, so no new AI work.
 * WHEN:  The "Learn" screen in the side rail.
 * CONNECTED TO: bridge.js → GET /learn/summary, GET /learn/session,
 *        POST /learn/review (server.py → learn.py); App.jsx (onOpenTopic);
 *        styles.css (.learn-*, .flash-*).
 */
import { useEffect, useState } from "react";
import Icon from "./icons.jsx";
import { formatCount, kb, usePoll } from "./bridge.js";

const RATINGS = [
  { n: 1, label: "Again", tone: "coral" },
  { n: 2, label: "Hard", tone: "mustard" },
  { n: 3, label: "Good", tone: "teal" },
  { n: 4, label: "Easy", tone: "violet" },
];

export default function Learn({ onOpenTopic }) {
  const [summary, reload] = usePoll("/learn/summary", 0);
  const [queue, setQueue] = useState(null); // cards in this session
  const [done, setDone] = useState({ count: 0, again: 0 });
  const [notice, setNotice] = useState("");

  async function start(topicId) {
    setNotice("");
    const r = await kb.get("/learn/session", topicId ? { topic_id: topicId } : undefined);
    if (r.error) return setNotice(r.error);
    if (!r.cards.length) return setNotice("Nothing due right now — come back tomorrow, or practise a topic below.");
    setDone({ count: 0, again: 0 });
    setQueue(r.cards);
  }

  function finish() {
    setQueue(null);
    reload();
  }

  if (queue) {
    return (
      <Session
        queue={queue}
        setQueue={setQueue}
        done={done}
        setDone={setDone}
        onExit={finish}
        onOpenTopic={onOpenTopic}
      />
    );
  }

  const s = summary;
  const maxDay = Math.max(1, ...(s?.activity ?? []).map((d) => d.reviews));
  const toStudy = (s?.due ?? 0) + (s?.new_today ?? 0);

  return (
    <div className="learn">
      <header className="page-head">
        <h1>Learn</h1>
        <p className="lede">
          Flashcards made from your lessons, shown again just before you'd forget them. A few minutes a day keeps
          everything in your bank in your head too.
        </p>
      </header>

      {!s ? (
        <p className="muted">Loading…</p>
      ) : !s.total ? (
        <section className="card learn-empty">
          <Icon name="learn" size={28} />
          <p>
            No cards yet. Cards are made automatically from each topic's lesson — go to <strong>Topics</strong> and
            press <strong>Write articles and lessons</strong>.
          </p>
        </section>
      ) : (
        <>
          <section className="learn-start card">
            <div>
              <h2>{toStudy ? `${formatCount(toStudy)} cards to study today` : "All caught up"}</h2>
              <p className="muted">
                {formatCount(s.due)} due for review · {formatCount(s.new_today)} new · {formatCount(s.reviewed_today)} reviewed
                today
              </p>
            </div>
            <button onClick={() => start()} disabled={!toStudy}>
              <Icon name="learn" size={18} />
              Start review
            </button>
          </section>
          {notice && <p className="notice">{notice}</p>}

          <section className="tiles" aria-label="Progress">
            <div className="tile tone-coral">
              <p className="tile-value">{formatCount(s.streak)}</p>
              <p className="tile-label">Day streak</p>
            </div>
            <div className="tile tone-teal">
              <p className="tile-value">{formatCount(s.mastered)}</p>
              <p className="tile-label">Cards mastered</p>
            </div>
            <div className="tile tone-violet">
              <p className="tile-value">{formatCount(s.total)}</p>
              <p className="tile-label">Cards in all</p>
            </div>
            <div className="tile tone-mustard">
              <p className="tile-value">{formatCount(s.reviewed_today)}</p>
              <p className="tile-label">Reviewed today</p>
            </div>
          </section>

          <section className="card">
            <h2>Last two weeks</h2>
            <div className="activity" role="img" aria-label="Reviews per day for the last 14 days">
              {s.activity.map((d, i) => (
                <div key={d.date} className="activity-day" title={`${d.date}: ${d.reviews} reviews`}>
                  <span
                    className={d.reviews ? "bar on" : "bar"}
                    style={{ height: `${Math.max(4, (d.reviews / maxDay) * 100)}%`, animationDelay: `${i * 0.03}s` }}
                  />
                  <span className="day">{new Date(d.date).toLocaleDateString("en-GB", { weekday: "narrow" })}</span>
                </div>
              ))}
            </div>
          </section>

          <section className="card">
            <h2>Progress by topic</h2>
            <ul className="topic-progress">
              {s.topics.map((t) => (
                <li key={t.topic_id}>
                  <button className="link tp-title" onClick={() => onOpenTopic(t.topic_id)}>
                    {t.title}
                  </button>
                  <div className="tp-bar" title={`${t.mastered} mastered, ${t.learning} learning, ${t.new} new`}>
                    <span className="m" style={{ width: `${(100 * t.mastered) / t.cards}%` }} />
                    <span className="l" style={{ width: `${(100 * t.learning) / t.cards}%` }} />
                  </div>
                  <span className="small muted tp-count">
                    {t.mastered}/{t.cards} mastered
                  </span>
                  <button className="secondary small-btn" onClick={() => start(t.topic_id)}>
                    Practise
                  </button>
                </li>
              ))}
            </ul>
            <p className="small muted legend-line">
              <span className="key m" /> mastered (next review 3+ weeks away) <span className="key l" /> learning{" "}
              <span className="key n" /> new
            </p>
          </section>
        </>
      )}
    </div>
  );
}

/** One review session: flip, answer, rate, next. */
function Session({ queue, setQueue, done, setDone, onExit, onOpenTopic }) {
  const [flipped, setFlipped] = useState(false);
  const [picked, setPicked] = useState(null);
  const [busy, setBusy] = useState(false);
  const card = queue[0];
  const total = done.count + queue.length;

  async function rate(n) {
    if (!card || busy || !flipped) return;
    setBusy(true);
    await kb.post("/learn/review", { card_id: card.id, rating: n });
    setBusy(false);
    setFlipped(false);
    setPicked(null);
    // "Again" sends the card to the back of today's queue.
    const rest = queue.slice(1);
    setDone({ count: done.count + (n === 1 ? 0 : 1), again: done.again + (n === 1 ? 1 : 0) });
    setTimeout(() => setQueue(n === 1 ? [...rest, card] : rest), 180);
  }

  // Keyboard: Space/Enter flips, 1–4 rate.
  useEffect(() => {
    function onKey(e) {
      if (e.target.closest?.("input, textarea")) return;
      if ((e.key === " " || e.key === "Enter") && !flipped && card?.kind !== "quiz") {
        e.preventDefault();
        setFlipped(true);
      } else if (["1", "2", "3", "4"].includes(e.key) && flipped) rate(Number(e.key));
      else if (e.key === "Escape") onExit();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  if (!card) {
    return (
      <div className="learn">
        <section className="card session-done">
          <div className="done-burst" aria-hidden="true">
            {Array.from({ length: 12 }, (_, i) => (
              <i key={i} style={{ "--a": `${i * 30}deg`, "--d": `${(i % 3) * 0.08}s` }} />
            ))}
            <Icon name="check" size={34} />
          </div>
          <h2>Session complete</h2>
          <p className="muted">
            {done.count} card{done.count === 1 ? "" : "s"} reviewed
            {done.again ? `, ${done.again} repeated until they stuck` : ""}. See you tomorrow.
          </p>
          <button onClick={onExit}>Back to Learn</button>
        </section>
      </div>
    );
  }

  return (
    <div className="learn session">
      <div className="session-top">
        <button className="ghost" onClick={onExit}>
          <Icon name="arrow-left" size={18} /> End session
        </button>
        <div className="session-progress" aria-label={`${done.count} of ${total} done`}>
          <span style={{ width: `${(100 * done.count) / total}%` }} />
        </div>
        <span className="small muted">
          {done.count} / {total}
        </span>
      </div>

      <div className={`flash ${flipped ? "flipped" : ""}`} key={card.id + "-" + queue.length}>
        <div className="flash-inner">
          <section className="flash-face front card">
            <p className="flash-topic">{card.topic_title}</p>
            <h2 className="flash-q">{card.front}</h2>
            {card.kind === "quiz" && card.options ? (
              <div className="quiz-options">
                {card.options.map((o, j) => {
                  const state = picked === null ? "" : o === card.back ? "right" : picked === j ? "wrong" : "";
                  return (
                    <button
                      key={j}
                      className={`quiz-option ${state}`}
                      onClick={() => {
                        if (picked !== null) return;
                        setPicked(j);
                        setTimeout(() => setFlipped(true), 650);
                      }}
                    >
                      {o}
                    </button>
                  );
                })}
              </div>
            ) : (
              <button className="secondary flip-btn" onClick={() => setFlipped(true)}>
                Show answer <kbd>Space</kbd>
              </button>
            )}
          </section>
          <section className="flash-face back card" aria-hidden={!flipped}>
            <p className="flash-topic">{card.topic_title}</p>
            <p className="flash-q small-q">{card.front}</p>
            <p className="flash-a">{card.back}</p>
            {card.topic_id && (
              <button className="link small" onClick={() => onOpenTopic(card.topic_id)}>
                Open the topic to read more
              </button>
            )}
          </section>
        </div>
      </div>

      <div className={`rate-row ${flipped ? "show" : ""}`} aria-hidden={!flipped}>
        {RATINGS.map((r) => (
          <button key={r.n} className={`rate tone-${r.tone}`} onClick={() => rate(r.n)} disabled={!flipped || busy}>
            <strong>{r.label}</strong>
            <span>{card.preview[String(r.n)]}</span>
            <kbd>{r.n}</kbd>
          </button>
        ))}
      </div>
    </div>
  );
}
