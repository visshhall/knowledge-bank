/**
 * Overview.jsx — the home screen: what the bank holds and what to do next.
 *
 * WHAT:  - A forest-green welcome band with the one most useful next step
 *          (finish setup → add files → wait for import → build topics →
 *          explore topics) as its button
 *        - Four bold tiles: files, passages, topics, repeated passages merged
 *        - The Schematic drawing (files → passages → topics) with live totals,
 *          plus pages read, scanned pages read by OCR, pictures read and
 *          duplicate files skipped
 *        - Live import progress while an import is running
 * WHY:   With no search typed, the bank should still explain itself: what it
 *        holds and how far along it is (owner requirement).
 * WHEN:  Default screen when the app opens. Refreshes totals every 3 s and
 *        import progress every 1.5 s while visible.
 * CONNECTED TO: bridge.js (GET /stats, /import/status, /setup/status),
 *        Schematic.jsx, ImportProgress (from Library.jsx), icons.jsx,
 *        App.jsx (onNavigate switches screens).
 */
import Schematic from "./Schematic.jsx";
import { ImportProgress } from "./Library.jsx";
import Icon from "./icons.jsx";
import { formatCount, usePoll } from "./bridge.js";

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
          <p className="tile-value">{formatCount(s.sources)}</p>
          <p className="tile-label">Files</p>
        </div>
        <div className="tile tone-coral">
          <p className="tile-value">{formatCount(s.passages)}</p>
          <p className="tile-label">Passages</p>
        </div>
        <div className="tile tone-violet">
          <p className="tile-value">{formatCount(s.topics)}</p>
          <p className="tile-label">Topics</p>
        </div>
        <div className="tile tone-mustard">
          <p className="tile-value">{formatCount(s.repeats_merged)}</p>
          <p className="tile-label">Repeats merged</p>
        </div>
      </section>

      {importing && <ImportProgress status={imp} />}

      <section className="card schematic-card" aria-label="How the bank is built">
        <h2>How your bank is built</h2>
        <Schematic sources={s.sources ?? 0} passages={s.passages ?? 0} topics={s.topics ?? 0} />
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
