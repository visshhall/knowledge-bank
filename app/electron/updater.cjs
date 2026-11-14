/**
 * updater.cjs — the app updates itself (v0.9).
 *
 * WHAT:  1. check({ online }) finds a newer Knowledge Bank installer:
 *            - LOCAL: a "KnowledgeBank-Setup-<version>.exe" newer than the
 *              running app in the owner's Downloads or Desktop folder (for an
 *              installer sent in chat and downloaded by hand);
 *            - ONLINE (when asked, and automatically at most once a day):
 *              the latest release of the project on GitHub
 *              (github.com/visshhall/knowledge-bank/releases).
 *        2. download() fetches the online installer into the app's own
 *           "updates" folder, with progress, then checks its size, that it
 *           is a Windows program ("MZ" header) and its SHA-256 against the
 *           value published in the release notes ("sha256: …").
 *        3. install(path) runs the installer silently ("/S --force-run":
 *           replace the app in place, then start the new version) and closes
 *           this one. Only an installer this module found or downloaded can
 *           be run — the page can't ask to run any other file.
 *
 * WHY:   Owner chose "app updates itself — check, download, install in one
 *        click" (15 Nov 2026) instead of reinstalling every .exe by hand.
 *
 * PRIVACY: the online check contacts api.github.com and github.com only,
 *        sending nothing but the request itself (no documents, no names).
 *        The daily automatic check can be turned off in Setup → App updates.
 *
 * WHEN:  main.cjs registers the IPC handlers below; the renderer
 *        (AppUpdate.jsx) calls them. A quiet online check runs 30 s after
 *        start when the last one was more than a day ago.
 *
 * CONNECTED TO: main.cjs (handlers, quit), preload.cjs (window.kb.update*),
 *        src/AppUpdate.jsx (banner + Setup card), package.json (version,
 *        NSIS installer that accepts /S and --force-run).
 */
const { app, net } = require("electron");
const { spawn } = require("node:child_process");
const crypto = require("node:crypto");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const REPO = "visshhall/knowledge-bank";
const NAME = /^KnowledgeBank-Setup-(\d+)\.(\d+)\.(\d+)\.exe$/i;
const DAY_MS = 24 * 60 * 60 * 1000;

const allowed = new Set(); // installer paths this module found or downloaded
let state = { checking: false, downloading: false, progress: 0, error: null, result: null };

const settingsFile = () => path.join(app.getPath("userData"), "update-settings.json");
function loadSettings() {
  try {
    return JSON.parse(fs.readFileSync(settingsFile(), "utf8"));
  } catch {
    return { auto: true, lastCheck: 0 };
  }
}
function saveSettings(s) {
  try {
    fs.writeFileSync(settingsFile(), JSON.stringify(s));
  } catch {
    /* a settings file we can't write only means the next check runs again */
  }
}

/** "0.9.1" → [0, 9, 1]; compares versions component by component. */
const parts = (v) => String(v).replace(/^v/, "").split(".").map((n) => parseInt(n, 10) || 0);
function newer(a, b) {
  const x = parts(a);
  const y = parts(b);
  for (let i = 0; i < 3; i++) if (x[i] !== y[i]) return x[i] > y[i];
  return false;
}

function findLocal() {
  const current = app.getVersion();
  let best = null;
  for (const dir of [path.join(os.homedir(), "Downloads"), path.join(os.homedir(), "Desktop")]) {
    let names = [];
    try {
      names = fs.readdirSync(dir);
    } catch {
      continue;
    }
    for (const name of names) {
      const m = name.match(NAME);
      if (!m) continue;
      const version = `${m[1]}.${m[2]}.${m[3]}`;
      if (newer(version, current) && (!best || newer(version, best.version))) {
        best = { version, path: path.join(dir, name) };
      }
    }
  }
  if (best) allowed.add(best.path);
  return best;
}

async function findOnline() {
  const res = await net.fetch(`https://api.github.com/repos/${REPO}/releases/latest`, {
    headers: { Accept: "application/vnd.github+json", "User-Agent": "KnowledgeBank-updater" },
  });
  if (res.status === 404) return null; // no release published yet
  if (!res.ok) throw new Error(`GitHub answered ${res.status}`);
  const rel = await res.json();
  const asset = (rel.assets || []).find((a) => NAME.test(a.name));
  const version = (rel.tag_name || "").replace(/^v/, "");
  if (!asset || !newer(version, app.getVersion())) return null;
  const sha = (rel.body || "").match(/sha256:\s*([a-f0-9]{64})/i);
  return {
    version,
    url: asset.browser_download_url,
    size: asset.size,
    name: asset.name,
    sha256: sha ? sha[1].toLowerCase() : null,
    notes: (rel.body || "").replace(/sha256:\s*[a-f0-9]{64}/i, "").trim().slice(0, 1500),
  };
}

async function check({ online = false } = {}) {
  state = { ...state, checking: true, error: null };
  const result = { current: app.getVersion(), local: findLocal(), online: null, checkedOnline: false };
  if (online) {
    try {
      result.online = await findOnline();
      result.checkedOnline = true;
      saveSettings({ ...loadSettings(), lastCheck: Date.now() });
    } catch (err) {
      state.error = `Couldn't reach GitHub (${err.message}). The app works normally; try again later.`;
    }
  }
  state = { ...state, checking: false, result };
  return { ...state };
}

async function download(onProgress) {
  const info = state.result?.online;
  if (!info) return { ok: false, message: "Check for updates first." };
  const dir = path.join(app.getPath("userData"), "updates");
  fs.mkdirSync(dir, { recursive: true });
  const target = path.join(dir, info.name);
  state = { ...state, downloading: true, progress: 0, error: null };
  try {
    const res = await net.fetch(info.url, { headers: { "User-Agent": "KnowledgeBank-updater" } });
    if (!res.ok || !res.body) throw new Error(`download failed (${res.status})`);
    const hash = crypto.createHash("sha256");
    const out = fs.createWriteStream(target);
    let got = 0;
    const reader = res.body.getReader();
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      hash.update(value);
      out.write(Buffer.from(value));
      got += value.length;
      state.progress = info.size ? got / info.size : 0;
      onProgress?.(state.progress);
    }
    await new Promise((resolve, reject) => out.end((err) => (err ? reject(err) : resolve())));
    const head = Buffer.alloc(2);
    const fd = fs.openSync(target, "r");
    fs.readSync(fd, head, 0, 2, 0);
    fs.closeSync(fd);
    if (info.size && got !== info.size) throw new Error("the download was incomplete");
    if (head.toString("latin1") !== "MZ") throw new Error("the file is not a Windows installer");
    if (info.sha256 && hash.digest("hex") !== info.sha256) throw new Error("the file's fingerprint doesn't match the release");
    allowed.add(target);
    state = { ...state, downloading: false, progress: 1, downloaded: target };
    return { ok: true, path: target };
  } catch (err) {
    try {
      fs.unlinkSync(target);
    } catch {
      /* nothing to remove */
    }
    state = { ...state, downloading: false, error: `Update download stopped: ${err.message}.` };
    return { ok: false, message: state.error };
  }
}

/** Run a found/downloaded installer silently and close this app. */
function install(installerPath) {
  if (!allowed.has(installerPath) || !fs.existsSync(installerPath)) {
    return { ok: false, message: "That installer wasn't found by the update check." };
  }
  if (process.platform !== "win32") return { ok: false, message: "Installing updates works on Windows only." };
  const child = spawn(installerPath, ["/S", "--force-run"], { detached: true, stdio: "ignore" });
  child.unref();
  setTimeout(() => app.quit(), 800); // the normal quit path stops the engine first
  return { ok: true, message: "Installing — Knowledge Bank will reopen by itself in a moment." };
}

function settings(next) {
  if (next && typeof next.auto === "boolean") saveSettings({ ...loadSettings(), auto: next.auto });
  return loadSettings();
}

/** Quiet daily online check, 30 s after start. */
function scheduleAutoCheck(notify) {
  setTimeout(async () => {
    const s = loadSettings();
    if (!s.auto || Date.now() - (s.lastCheck || 0) < DAY_MS) {
      const r = await check({ online: false });
      if (r.result?.local) notify(r);
      return;
    }
    const r = await check({ online: true });
    if (r.result?.local || r.result?.online) notify(r);
  }, 30000);
}

module.exports = { check, download, install, settings, scheduleAutoCheck, getState: () => ({ ...state }) };
