/**
 * Overview.jsx — the home screen: what the bank holds and what to do next.
 *
 * WHAT:  - A forest-green welcome band with the one most useful next step
 *          (finish setup → add files → wait for import → build topics →
 *          explore topics) as its button
 *        - Four bold tiles: files, passages, topics, repeated passages merged
 *        - The interactive flow map (FlowMap.jsx: files → topics, hover to
 *          trace, click a topic to open it) — replaced the v0.4 schematic,
 *          and totals that count up on first show,
 *          plus pages read, scanned pages read by OCR, pictures read and
 *          duplicate files skipped
 *        - (v0.22) "Your library at a glance": file kinds, subjects treemap, last 30 days, health rings (Glance.jsx)
 *        - Live import progress while an import is running
 * WHY:   With no search typed, the bank should still explain itself: what it
 *        holds and how far along it is (owner requirement).
 * WHEN:  Default screen when the app opens. Refreshes totals every 3 s and
 *        import progress every 1.5 s while visible.
 * CONNECTED TO: bridge.js (GET /stats, /import/status, /setup/status),
 *        FlowMap.jsx, Glance.jsx, ImportProgress (from Library.jsx), icons.jsx,
 *        App.jsx (onNavigate switches screens).
 */
import FlowMap from "./FlowMap.jsx";
import { LibraryGlance } from "./Glance.jsx";
import { useEffect, useRef, useState } from "react";
import { ImportProgress } from "./Library.jsx";
import Icon from "./icons.jsx";
import { formatCount, usePoll } from "./bridge.js";

/**
 * A number that counts up from 0 the first time it appears (one short,
 * orchestrated moment on opening the app). Later changes update instantly.
 * Respects "reduce animations".
 */
function CountUp({ value }) {
  const [shown, setShown] = useState(0);
  const done = useRef(false);
  useEffect(() => {
    if (typeof value !== "number") return undefined;
    const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    if (done.current || reduce || value === 0) {
      setShown(value);
      done.current = true;
      return undefined;
    }
    let raf;
    const start = performance.now();
    const step = (now) => {
      const t = Math.min(1, (now - start) / 900);
      setShown(Math.round(value * (1 - (1 - t) ** 3)));
      if (t < 1) raf = requestAnimationFrame(step);
      else done.current = true;
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [value]);
  return <>{formatCount(typeof value === "number" ? shown : value)}</>;
}

export default function Overview({ onNavigate }) {
  const [stats] = usePoll("/stats", 3000);
  const [imp] = usePoll("/import/status", 1500);
  const [setup] = usePoll("/setup/status", 5000);

  const s = stats ?? {};
  const importing = imp?.state === "running";

  /** Pick the one most useful next step for the owner right now. */
  let next;
  if (setup && !setup.setup_complete) {
    next = { text: "Finish setup so the AI models are ready. You can import files meanwhile.", action: "Open setup", to: "setup", icon: "setup" };
  } else if (!s.sources) {
    next = { text: "Add your PDFs and images. Whole folders work, subfolders included.", action: "Add files", to: "library", icon: "upload" };
  } else if (importing) {
    next = { text: "Import is running. You can already search everything read so far.", action: "Search the library", to: "library", icon: "search" };
  } else if (!s.topics) {
    next = { text: "Everything is imported. Group it into topics so repeats are merged.", action: "Build topics", to: "topics", icon: "sparkle" };
  } else {
    next = { text: `${formatCount(s.topics)} topics are ready to explore.`, action: "Explore topics", to: "topics", icon: "topics" };
  }

  return (
    <div className="overview">
      <header className="hero">
        <div className="hero-text">
          <h1>One bank for everything you've read.</h1>
          <p>{next.text}</p>
        </div>
        <button className="on-dark" onClick={() => onNavigate(next.to)}>
          <Icon name={next.icon} size={18} />
          {next.action}
        </button>
      </header>

      <section className="tiles" aria-label="Totals">
        <div className="tile tone-teal">
          <p className="tile-value"><CountUp value={s.sources} /></p>
          <p className="tile-label">Files</p>
        </div>
        <div className="tile tone-coral">
          <p className="tile-value"><CountUp value={s.passages} /></p>
          <p className="tile-label">Passages</p>
        </div>
        <div className="tile tone-violet">
          <p className="tile-value"><CountUp value={s.topics} /></p>
          <p className="tile-label">Topics</p>
        </div>
        <div className="tile tone-mustard">
          <p className="tile-value"><CountUp value={s.repeats_merged} /></p>
          <p className="tile-label">Repeats merged</p>
        </div>
      </section>

      {importing && <ImportProgress status={imp} />}

      <LibraryGlance />

      <section className="card flow-card" aria-label="Where your knowledge goes">
        <h2>Where your knowledge goes</h2>
        <FlowMap
          version={`${s.sources}-${s.passages}-${s.topics}`}
          onOpenTopic={(id) => onNavigate("topics", { topicId: id })}
        />
        <dl className="facts">
          <div>
            <dt>Pages read</dt>
            <dd>{formatCount(s.pages)}</dd>
          </div>
          <div>
            <dt>Scanned pages read by OCR</dt>
            <dd>{formatCount(s.ocr_pages)}</dd>
          </div>
          <div>
            <dt>Pictures read</dt>
            <dd>{formatCount(s.images)}</dd>
          </div>
          <div>
            <dt>Duplicate files skipped</dt>
            <dd>{formatCount(s.duplicates_skipped)}</dd>
          </div>
        </dl>
      </section>
    </div>
  );
}
