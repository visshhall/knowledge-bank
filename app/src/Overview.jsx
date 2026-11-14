/**
 * Overview.jsx — the home screen: what the bank holds and what to do next.
 *
 * WHAT:  - The Schematic drawing (files → passages → topics) with live totals
 *        - A short line of supporting numbers (pages, scanned pages read,
 *          pictures read, duplicates skipped)
 *        - Live import progress when an import is running
 *        - One clear next step, depending on where the owner is
 *          (finish setup → add files → wait for import → search)
 * WHY:   With no search typed, the bank should still explain itself: what it
 *        holds and how far along it is (owner requirement).
 * WHEN:  Default screen when the app opens. Refreshes every 3 s (totals)
 *        and 1.5 s (import progress) while visible.
 * CONNECTED TO: bridge.js (GET /stats, /import/status, /setup/status),
 *        Schematic.jsx, ImportProgress (from Library.jsx), App.jsx
 *        (onNavigate switches screens).
 */
import Schematic from "./Schematic.jsx";
import { ImportProgress } from "./Library.jsx";
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
    next = {
      text: "Finish setup so the AI models are ready. Importing works meanwhile.",
      action: "Open setup",
      to: "setup",
    };
  } else if (!s.sources) {
    next = {
      text: "Add your PDFs and images. Folders are searched, subfolders included.",
      action: "Add files",
      to: "library",
    };
  } else if (importing) {
    next = { text: "Import is running. You can already search what's been read so far.", action: "Search the library", to: "library" };
  } else {
    next = { text: "Everything is imported. Search any word, ID or query across every page.", action: "Search the library", to: "library" };
  }

  return (
    <div className="overview">
      <header className="ov-head">
        <h1>One bank for everything you've read.</h1>
        <p className="lede">
          Every PDF and image goes in once. The bank keeps each passage with its file and page,
          drops exact copies, and — in the next updates — merges what they say into single topic
          pages.
        </p>
      </header>

      <section className="frame schematic-frame" aria-label="Knowledge bank overview">
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

      {importing && <ImportProgress status={imp} />}

      <section className="next-step">
        <p>{next.text}</p>
        <button onClick={() => onNavigate(next.to)}>{next.action}</button>
      </section>
    </div>
  );
}
