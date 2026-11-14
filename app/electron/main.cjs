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
 *        - src/App.jsx           → the interface that calls window.kb
 *        - engine/kb_engine/server.py → the Python engine it starts
 *        - vite.config.js        → dev server address / build output
 */
const { app, BrowserWindow, ipcMain, shell } = require("electron");
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
 * Engine endpoints the interface may call. Anything else is refused here,
 * before it reaches the engine. New phases add their endpoints to this list.
 */
const ALLOWED_ENGINE_PATHS = new Set(["/health", "/system", "/stats"]);

/** Folder containing the Python engine (sibling of /app in the repo). */
const ENGINE_DIR = path.resolve(__dirname, "..", "..", "engine");

let engineProcess = null; // the running Python process, or null
let engineState = { status: "starting", detail: "" }; // shown in the window
let mainWindow = null;

// ---------------------------------------------------------------------------
// Engine lifecycle
// ---------------------------------------------------------------------------

/**
 * Find the Python interpreter inside the engine's virtual environment
 * (created by setup/setup.ps1). Using the venv guarantees the exact library
 * versions from requirements.txt, not whatever Python the system has.
 * Returns null if setup hasn't been run.
 */
function findEnginePython() {
  const candidates =
    process.platform === "win32"
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
    setEngineState("error", "Engine not installed. Run setup\\setup.ps1 first.");
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
 * Handle `window.kb.get(path)` calls from the interface (via preload.cjs).
 * Refuses paths not on the allow-list, adds the secret token, returns JSON.
 * Errors are returned as { error } objects rather than thrown, so the
 * interface can show a friendly message.
 */
ipcMain.handle("engine:get", async (_event, enginePath) => {
  if (!ALLOWED_ENGINE_PATHS.has(enginePath)) {
    return { error: `Path not allowed: ${enginePath}` };
  }
  if (engineState.status !== "ready") {
    return { error: `Engine is ${engineState.status}` };
  }
  try {
    const res = await fetch(`${ENGINE_URL}${enginePath}`, {
      headers: { "X-KB-Token": ENGINE_TOKEN },
    });
    if (!res.ok) return { error: `Engine returned HTTP ${res.status}` };
    return await res.json();
  } catch (err) {
    return { error: `Engine unreachable: ${err.message}` };
  }
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
    backgroundColor: "#0b1020", // matches the interface so there's no white flash
    title: "Knowledge Bank",
    autoHideMenuBar: true, // hides File/Edit/View menu (press Alt to show)
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      sandbox: true,
      nodeIntegration: false,
    },
  });

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
