/**
 * main.cjs — the Electron "main process": the app's control centre.
 *
 * WHAT:  1. Starts the Python engine (engine/kb_engine/server.py) as a hidden
 *           background process when the app opens.
 *        2. Creates the app window and loads the React interface.
 *        3. Relays requests from the window to the engine (the window itself
 *           is never allowed to contact the engine or the internet directly).
 *        4. Stops the engine when the app closes.
 *
 * WHY:   Electron gives us a native Windows app with a modern interface.
 *        Routing every engine call through here (instead of letting the
 *        page call http://127.0.0.1:8765 itself) means:
 *          - the secret engine token never reaches the page,
 *          - only an approved list of engine endpoints can be called,
 *          - a compromised page could not talk to anything else.
 *
 * WHEN:  Runs once, from the moment the app is launched until it is closed.
 *
 * CONNECTED TO:
 *        - electron/preload.cjs  → exposes the safe `window.kb` bridge
 *        - src/App.jsx, src/SetupWizard.jsx → the interface that calls window.kb
 *        - engine/kb_engine/server.py → the Python engine it starts
 *        - vite.config.js        → dev server address / build output
 *        - package.json "build"  → how the Windows installer bundles the
 *          engine and its private Python (see "Where the engine lives")
 */
const { app, BrowserWindow, dialog, ipcMain, shell } = require("electron");
const { pathToFileURL } = require("url");
const { spawn } = require("node:child_process");
const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");

// ---------------------------------------------------------------------------
// Settings
// ---------------------------------------------------------------------------

/** Port the engine listens on. Must match engine/kb_engine/config.py. */
const ENGINE_PORT = Number(process.env.KB_ENGINE_PORT || 8765);
const ENGINE_URL = `http://127.0.0.1:${ENGINE_PORT}`;

/**
 * Fresh random secret for this launch. Passed to the engine as an
 * environment variable; every request must include it. 32 random bytes =
 * impossible to guess. Regenerated every launch, never saved to disk.
 */
const ENGINE_TOKEN = crypto.randomBytes(32).toString("hex");

/**
 * Engine endpoints the interface may call, as "METHOD /path". Anything else
 * is refused here, before it reaches the engine. New phases add theirs.
 */
const ALLOWED_ENGINE_CALLS = new Set([
  "GET /health",
  "GET /system",
  "GET /stats",
  "GET /setup/status",
  "POST /setup/ollama/install",
  "POST /setup/ollama/start",
  "POST /setup/models/pull",
  "POST /setup/benchmark/start",
  "POST /setup/benchmark/cancel",
  "POST /setup/models/remove",
  // Phase 1 — import, library, search
  "GET /library",
  "POST /library/add",
  "POST /library/remove",
  "POST /library/remove-many",
  "POST /library/retry",
  "POST /library/keep", // v0.8.2: import a set-aside file anyway
  "GET /gpu/status", // v0.8.2: graphics card report (Setup)
  "GET /storage", // v0.9: disk space + clean-up
  "POST /storage/cleanup",
  "GET /topics/names", // v0.9: editing topics by hand
  "POST /topics/rename",
  "POST /topics/merge",
  "POST /topics/move",
  "POST /topics/split",
  "POST /gpu/tune",
  "GET /library/filter", // v0.8.2: "Only keep cybersecurity files" switch
  "POST /library/filter",
  "POST /library/dedupe", // v0.8.2: "Skip content already in the bank" switch
  "GET /import/status",
  "GET /settings/watch",
  "POST /settings/watch",
  "GET /search",
  // Phase 2 — topics
  "POST /distill/start",
  "GET /distill/status",
  "GET /topics",
  "GET /topic",
  // Phase 3 — articles
  "POST /write/start",
  "GET /write/status",
  "POST /write/cancel",
  // v0.6 — automatic visual lessons
  "GET /lesson",
  "POST /lesson/regenerate",
  // v0.6.1 — "Read in context"
  "GET /passage/context",
  "GET /passage/section",
  "GET /overview/flow",
  "GET /search/quick",
  // v0.7 — answer pages, Learn mode, tools, updates, backup
  "POST /answer/ask",
  "GET /answer/status",
  "GET /answers",
  "GET /answer",
  "POST /answer/delete",
  "GET /source",
  "GET /topics/map",
  "POST /tools/iocs",
  "GET /tools/bank-iocs",
  "GET /tools/mitre",
  "GET /tools/queries",
  "POST /backup/create",
  "POST /backup/restore",
  "GET /backup/status",
  "POST /distill/update",
  "POST /library/password",
  "GET /learn/summary",
  "GET /learn/session",
  "POST /learn/review",
  // AI updates
  "POST /updates/check",
  "GET /updates/status",
  "POST /updates/model",
  "POST /updates/ollama",
]);

/*
 * Where the engine lives:
 *  - Installed app (app.isPackaged): the installer copies the engine code to
 *    <install folder>/resources/engine and a private Windows Python (with all
 *    libraries pre-installed) to <install folder>/resources/python. The owner
 *    never installs Python.
 *  - Development (running from the repo): engine/ next to app/, using the
 *    engine/.venv created by `python -m venv .venv`.
 */
const ENGINE_DIR = app.isPackaged
  ? path.join(process.resourcesPath, "engine")
  : path.resolve(__dirname, "..", "..", "engine");

/**
 * The reports folder (benchmark results). Computed here, the same way the
 * engine's config.py does, so the window can only ever open THIS folder —
 * it can't ask main.cjs to open arbitrary paths.
 */
const REPORTS_DIR = path.join(
  process.env.KB_DATA_DIR ||
    (process.env.LOCALAPPDATA
      ? path.join(process.env.LOCALAPPDATA, "KnowledgeBank")
      : path.join(require("node:os").homedir(), ".knowledge-bank")),
  "reports"
);

let engineProcess = null; // the running Python process, or null
let engineState = { status: "starting", detail: "" }; // shown in the window
let mainWindow = null;

// ---------------------------------------------------------------------------
// Engine lifecycle
// ---------------------------------------------------------------------------

/**
 * Find the Python that runs the engine.
 *  - Installed app: the bundled private Python (resources/python/python.exe).
 *  - Development: the engine's virtual environment.
 * Never uses a system-wide Python, so library versions always match
 * requirements.txt exactly. Returns null if none is found.
 */
function findEnginePython() {
  const candidates = app.isPackaged
    ? [path.join(process.resourcesPath, "python", "python.exe")]
    : process.platform === "win32"
      ? [path.join(ENGINE_DIR, ".venv", "Scripts", "python.exe")]
      : [path.join(ENGINE_DIR, ".venv", "bin", "python")];
  return candidates.find((p) => fs.existsSync(p)) || null;
}

/** Update the engine status and tell the window (if it's open). */
function setEngineState(status, detail = "") {
  engineState = { status, detail };
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send("engine:status", engineState);
  }
}

/**
 * Start the Python engine as a hidden child process.
 *
 * HOW:  `python -m kb_engine.server` from the engine folder, with the token
 *       and port in its environment. windowsHide stops a black console
 *       window from appearing. Output is forwarded to this process's console
 *       for debugging.
 * WHEN: Once, after Electron is ready (see app.whenReady below).
 */
function startEngine() {
  const python = findEnginePython();
  if (!python) {
    setEngineState("error", "The app's engine files are missing. Please reinstall Knowledge Bank.");
    return;
  }
  engineProcess = spawn(python, ["-m", "kb_engine.server"], {
    cwd: ENGINE_DIR,
    env: {
      ...process.env,
      KB_ENGINE_TOKEN: ENGINE_TOKEN,
      KB_ENGINE_PORT: String(ENGINE_PORT),
      PYTHONUNBUFFERED: "1",
    },
    windowsHide: true,
  });
  // The engine already prefixes its own lines with "[engine]".
  engineProcess.stdout.on("data", (d) => process.stdout.write(d));
  engineProcess.stderr.on("data", (d) => process.stderr.write(d));
  engineProcess.on("exit", (code) => {
    engineProcess = null;
    if (!app.isQuitting) {
      setEngineState("error", `Engine stopped unexpectedly (exit code ${code}).`);
    }
  });
  waitForEngine();
}

/**
 * Poll GET /health every 500 ms until the engine answers (max ~60 s).
 * WHY: Python + database startup takes a moment; the window shows a
 *      "starting" animation meanwhile instead of errors.
 */
async function waitForEngine() {
  for (let attempt = 0; attempt < 120; attempt++) {
    if (!engineProcess) return; // it crashed; exit handler already reported
    try {
      const res = await fetch(`${ENGINE_URL}/health`, {
        headers: { "X-KB-Token": ENGINE_TOKEN },
      });
      if (res.ok) {
        const body = await res.json();
        setEngineState("ready", `engine ${body.engine_version}`);
        return;
      }
    } catch {
      /* not up yet — keep waiting */
    }
    await new Promise((r) => setTimeout(r, 500));
  }
  setEngineState("error", "Engine did not start within 60 seconds.");
}

/** Stop the engine when the app closes, so no Python process is left behind. */
function stopEngine() {
  if (engineProcess) {
    engineProcess.kill();
    engineProcess = null;
  }
}

// ---------------------------------------------------------------------------
// Bridge: window → engine
// ---------------------------------------------------------------------------

/**
 * Send one request to the engine, adding the secret token.
 *   method      "GET" or "POST"
 *   enginePath  must be on ALLOWED_ENGINE_CALLS (checked without any query)
 *   body        POST: JSON body · GET: optional object of query parameters
 *               (e.g. { q: "4625" } → /search?q=4625), safely encoded here
 * Errors come back as { error } objects rather than thrown, so the
 * interface can show a friendly message.
 */
async function callEngine(method, enginePath, body) {
  if (!ALLOWED_ENGINE_CALLS.has(`${method} ${enginePath}`)) {
    return { error: `Not allowed: ${method} ${enginePath}` };
  }
  if (engineState.status !== "ready") {
    return { error: `Engine is ${engineState.status}` };
  }
  const query =
    method === "GET" && body && typeof body === "object"
      ? `?${new URLSearchParams(body).toString()}`
      : "";
  try {
    const res = await fetch(`${ENGINE_URL}${enginePath}${query}`, {
      method,
      headers: { "X-KB-Token": ENGINE_TOKEN, "Content-Type": "application/json" },
      body: method === "POST" ? JSON.stringify(body ?? {}) : undefined,
    });
    if (!res.ok) return { error: `Engine returned HTTP ${res.status}` };
    return await res.json();
  } catch (err) {
    return { error: `Engine unreachable: ${err.message}` };
  }
}

/** window.kb.get(path, params) → GET request to the engine. */
ipcMain.handle("engine:get", (_event, enginePath, params) =>
  callEngine("GET", enginePath, params)
);

/** window.kb.post(path, body) → POST request to the engine. */
ipcMain.handle("engine:post", (_event, enginePath, body) =>
  callEngine("POST", enginePath, body)
);

/**
 * window.kb.pickFolder(purpose) → Windows "choose a folder" dialog.
 * purpose picks the dialog title from a fixed list (the page can't inject
 * arbitrary text). Returns the chosen path, or null if cancelled.
 */
const FOLDER_DIALOG_TITLES = {
  benchmark: "Choose a folder with 5–10 of your PDFs",
  import: "Choose a folder to import (subfolders included)",
  watch: "Choose a folder to watch for new PDFs and images",
};
ipcMain.handle("dialog:pickFolder", async (_event, purpose) => {
  const result = await dialog.showOpenDialog(mainWindow, {
    title: FOLDER_DIALOG_TITLES[purpose] || FOLDER_DIALOG_TITLES.import,
    properties: ["openDirectory"],
  });
  return result.canceled ? null : result.filePaths[0];
});

/**
 * window.kb.pickFiles() → Windows "open files" dialog for PDFs and images.
 * Returns an array of paths (empty if cancelled).
 */
ipcMain.handle("dialog:pickFiles", async () => {
  const result = await dialog.showOpenDialog(mainWindow, {
    title: "Add PDFs, images and spreadsheets to the knowledge bank",
    properties: ["openFile", "multiSelections"],
    filters: [
      // v0.9: Word, PowerPoint, saved web pages, text and Markdown too
      { name: "Documents, images and spreadsheets", extensions: ["pdf", "docx", "pptx", "html", "htm", "txt", "md", "markdown", "png", "jpg", "jpeg", "webp", "bmp", "gif", "tif", "tiff", "xlsx", "xlsm", "csv"] },
    ],
  });
  return result.canceled ? [] : result.filePaths;
});

/*
 * Backup files (v0.7): choose where to save a backup, or which one to
 * restore. Only ".kbbackup" files. "app:restart" relaunches after a restore
 * so the engine swaps the bank in at start-up (backup.apply_pending_restore).
 */
ipcMain.handle("dialog:saveBackup", async () => {
  const stamp = new Date().toISOString().slice(0, 10);
  const result = await dialog.showSaveDialog(mainWindow, {
    title: "Save an encrypted backup of the knowledge bank",
    defaultPath: `KnowledgeBank-${stamp}.kbbackup`,
    filters: [{ name: "Knowledge Bank backup", extensions: ["kbbackup"] }],
  });
  return result.canceled ? null : result.filePath;
});
ipcMain.handle("dialog:pickBackup", async () => {
  const result = await dialog.showOpenDialog(mainWindow, {
    title: "Choose a backup to restore",
    properties: ["openFile"],
    filters: [{ name: "Knowledge Bank backup", extensions: ["kbbackup"] }],
  });
  return result.canceled ? null : result.filePaths[0];
});
ipcMain.handle("app:restart", () => {
  app.relaunch();
  app.quit(); // the normal quit path stops the engine first
});

/** window.kb.openReports() → open the reports folder in File Explorer. */
/*
 * Open an imported file at a page (v0.7): PDFs open in a separate, locked-
 * down viewer window using Chromium's built-in PDF viewer, jumping to the
 * cited page (#page=N). Other files (images) open in their Windows app.
 * The renderer only passes a source id; the path comes from the engine's
 * own database, so the page can't ask to open arbitrary files.
 */
ipcMain.handle("file:open", async (_event, sourceId, page) => {
  const src = await callEngine("GET", "/source", { id: Number(sourceId) });
  if (src.error) return src;
  if (!src.exists) return { error: "The original file was moved or deleted, so it can't be opened." };
  if (src.file_type !== "pdf") {
    const err = await shell.openPath(src.path);
    return err ? { error: err } : { ok: true };
  }
  const n = Math.max(1, Number(page) || 1);
  const viewer = new BrowserWindow({
    width: 1000,
    height: 900,
    title: `${src.file_name} — page ${n}`,
    backgroundColor: "#e2e8df",
    autoHideMenuBar: true,
    webPreferences: { plugins: true, sandbox: true, contextIsolation: true, nodeIntegration: false },
  });
  viewer.on("page-title-updated", (event) => event.preventDefault());
  viewer.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
  viewer.webContents.on("will-navigate", (event) => event.preventDefault());
  await viewer.loadURL(`${pathToFileURL(src.path).href}#page=${n}`);
  return { ok: true };
});

/*
 * Optional web look-ups (Phase 6 "web assist"), always opened in the
 * owner's normal browser — never inside the app, never automatic. Only the
 * single value shown on the button is sent (a search phrase, a technique ID,
 * an indicator), and the URL is built here from a fixed list of sites, so
 * the page can't send anything else anywhere.
 */
const WEB_LOOKUPS = {
  search: (v) => `https://duckduckgo.com/?q=${encodeURIComponent(v)}`,
  mitre: (v) => `https://attack.mitre.org/techniques/${encodeURIComponent(v).replace(".", "/")}/`,
  virustotal: (v) => `https://www.virustotal.com/gui/search/${encodeURIComponent(v)}`,
  cve: (v) => `https://nvd.nist.gov/vuln/detail/${encodeURIComponent(v)}`,
};
ipcMain.handle("web:open", async (_event, kind, value) => {
  const make = WEB_LOOKUPS[kind];
  const v = String(value ?? "").trim();
  if (!make || !v || v.length > 300) return { error: "Nothing to look up." };
  if (kind === "mitre" && !/^T\d{4}(\.\d{3})?$/.test(v)) return { error: "Not a technique ID." };
  await shell.openExternal(make(v));
  return { ok: true };
});

// The installed version (from package.json), shown in the top-right corner
// of the window so the owner always knows which build is running (v0.6.1).
ipcMain.handle("app:version", () => app.getVersion());

/*
 * App updates (v0.9, updater.cjs): check (Downloads/Desktop + GitHub
 * releases), download with progress, install silently and reopen. Only an
 * installer the updater itself found or downloaded can be run.
 */
const updater = require("./updater.cjs");
ipcMain.handle("update:check", (_event, online) => updater.check({ online: Boolean(online) }));
ipcMain.handle("update:state", () => updater.getState());
ipcMain.handle("update:download", () =>
  updater.download((p) => mainWindow?.webContents.send("update:progress", p))
);
ipcMain.handle("update:install", (_event, installerPath) => updater.install(String(installerPath || "")));
ipcMain.handle("update:settings", (_event, next) => updater.settings(next));

ipcMain.handle("shell:openReports", async () => {
  fs.mkdirSync(REPORTS_DIR, { recursive: true });
  const err = await shell.openPath(REPORTS_DIR);
  return err ? { error: err } : { ok: true };
});

/** Lets the window ask for the current engine status (e.g. right after loading). */
ipcMain.handle("engine:status", () => engineState);

// ---------------------------------------------------------------------------
// Window
// ---------------------------------------------------------------------------

/**
 * Create the main window with locked-down security settings:
 *  - contextIsolation: page code can't touch Electron/Node internals
 *  - sandbox: the page runs like a normal, restricted web page
 *  - nodeIntegration off: page can't run system commands
 * Only window.kb (from preload.cjs) is exposed.
 */
function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 820,
    minWidth: 960,
    minHeight: 640,
    backgroundColor: "#e2e8df", // matches the interface so there's no white flash
    title: `Knowledge Bank ${app.getVersion()}`,
    autoHideMenuBar: true, // hides File/Edit/View menu (press Alt to show)
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      sandbox: true,
      nodeIntegration: false,
    },
  });

  // Keep the version in the title bar: the page's own <title> would
  // otherwise replace it once loaded.
  mainWindow.on("page-title-updated", (event) => event.preventDefault());

  // Links to websites open in the normal browser, never inside the app.
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith("https://")) shell.openExternal(url);
    return { action: "deny" };
  });

  // Block the window from navigating away from the app's own pages.
  mainWindow.webContents.on("will-navigate", (event, url) => {
    const devUrl = process.env.VITE_DEV_SERVER_URL;
    if (!(devUrl && url.startsWith(devUrl))) event.preventDefault();
  });

  if (process.env.VITE_DEV_SERVER_URL) {
    mainWindow.loadURL(process.env.VITE_DEV_SERVER_URL); // live-reload during development
  } else {
    mainWindow.loadFile(path.join(__dirname, "..", "dist", "index.html")); // built app
  }

  mainWindow.on("closed", () => {
    mainWindow = null;
  });
}

// ---------------------------------------------------------------------------
// App lifecycle
// ---------------------------------------------------------------------------

// Only one copy of the app may run (two would fight over the engine port).
if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on("second-instance", () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.focus();
    }
  });

  app.whenReady().then(() => {
    startEngine();
    createWindow();
    // v0.9: quiet update check 30 s after start (online at most once a day,
    // if allowed); the page shows a banner when something newer is found.
    updater.scheduleAutoCheck((r) => mainWindow?.webContents.send("update:found", r));
  });

  // Flag used by the engine's exit handler to tell a crash from a normal quit.
  app.on("before-quit", () => {
    app.isQuitting = true;
    stopEngine();
  });

  app.on("window-all-closed", () => {
    app.quit();
  });
}
