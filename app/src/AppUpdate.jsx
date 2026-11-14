/**
 * AppUpdate.jsx — app updates in the window (v0.9).
 *
 * WHAT:  UpdateBanner — a small banner under the version badge when a newer
 *        Knowledge Bank is found (by the quiet check at start, or by the
 *        Setup card): "Install" for an installer already on this laptop,
 *        "Download and install" for one on GitHub, with a progress bar.
 *        UpdateCard — the "App updates" card on the Setup screen: current
 *        version, "Check for updates", the daily automatic check switch.
 * WHY:   Owner chose "app updates itself" (15 Nov 2026).
 * WHEN:  UpdateBanner sits in the app header (App.jsx); UpdateCard on Setup.
 * CONNECTED TO: preload.cjs window.kb.update* → electron/updater.cjs.
 */
import { useEffect, useState } from "react";
import Icon from "./icons.jsx";

const kb = window.kb ?? {};

/** Shared logic: what was found, download progress, install. */
function useUpdate() {
  const [found, setFound] = useState(null); // updater state with .result
  const [progress, setProgress] = useState(null);
  const [message, setMessage] = useState("");
  useEffect(() => {
    if (!kb.onUpdate) return undefined;
    kb.updateState?.().then((s) => s?.result && setFound(s));
    const off1 = kb.onUpdate("found", setFound);
    const off2 = kb.onUpdate("progress", setProgress);
    return () => {
      off1();
      off2();
    };
  }, []);
  async function check(online) {
    setMessage(online ? "Checking…" : "");
    const r = await kb.updateCheck(online);
    setFound(r);
    setMessage(
      r.error ||
        (r.result?.local || r.result?.online ? "" : online ? "You have the newest version." : "")
    );
  }
  async function install() {
    let target = found?.result?.local?.path;
    if (!target) {
      setMessage("Downloading…");
      const d = await kb.updateDownload();
      if (!d.ok) {
        setMessage(d.message);
        return;
      }
      target = d.path;
    }
    const r = await kb.updateInstall(target);
    setMessage(r.message);
  }
  const version = found?.result?.local?.version || found?.result?.online?.version;
  return { found, version, progress, message, check, install };
}

export function UpdateBanner() {
  const u = useUpdate();
  const [hidden, setHidden] = useState(false);
  if (!u.version || hidden) return null;
  const downloading = u.progress !== null && u.progress < 1;
  return (
    <div className="update-banner" role="status">
      <Icon name="refresh" size={15} />
      <span>
        Version {u.version} is ready{u.found?.result?.local ? " (found in your Downloads)" : ""}.
      </span>
      {downloading ? (
        <span className="update-progress">
          <span style={{ width: `${Math.round(u.progress * 100)}%` }} />
        </span>
      ) : (
        <button className="link" onClick={u.install}>
          {u.found?.result?.local ? "Install" : "Download and install"}
        </button>
      )}
      {!downloading && (
        <button className="link muted" onClick={() => setHidden(true)} aria-label="Later">
          Later
        </button>
      )}
      {u.message && <span className="small muted">{u.message}</span>}
    </div>
  );
}

export function UpdateCard() {
  const u = useUpdate();
  const [current, setCurrent] = useState("");
  const [auto, setAuto] = useState(true);
  useEffect(() => {
    kb.appVersion?.().then(setCurrent);
    kb.updateSettings?.().then((s) => s && setAuto(s.auto !== false));
  }, []);
  async function toggle() {
    const s = await kb.updateSettings({ auto: !auto });
    setAuto(s.auto !== false);
  }
  const notes = u.found?.result?.online?.notes;
  return (
    <section className="card updates" aria-label="App updates">
      <div className="section-head">
        <div>
          <h2>App updates</h2>
          <p className="muted small">
            You have Knowledge Bank {current}. Updates come from the project's GitHub releases, or from a newer
            installer in your Downloads folder. Checking sends nothing but the request itself.
          </p>
        </div>
        <button className="secondary" onClick={() => u.check(true)}>
          <Icon name="refresh" size={16} />
          Check for updates
        </button>
      </div>
      {u.message && <p className="notice ok">{u.message}</p>}
      {u.version && (
        <div className="update-ready">
          <p>
            <strong>Version {u.version}</strong> is ready.{" "}
            <button onClick={u.install}>{u.found?.result?.local ? "Install now" : "Download and install"}</button>
          </p>
          {u.progress !== null && u.progress < 1 && (
            <span className="update-progress wide">
              <span style={{ width: `${Math.round(u.progress * 100)}%` }} />
            </span>
          )}
          {notes && <pre className="update-notes">{notes}</pre>}
          <p className="small muted">The app closes, installs the new version and opens again by itself. Your bank is kept.</p>
        </div>
      )}
      <label className="relevance-switch">
        <input type="checkbox" checked={auto} onChange={toggle} />
        <span>Check for updates automatically once a day</span>
      </label>
    </section>
  );
}
