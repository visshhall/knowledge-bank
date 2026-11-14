/**
 * preload.cjs — the only bridge between the interface and the rest of the app.
 *
 * WHAT:  Exposes a tiny, fixed set of functions to the page as `window.kb`:
 *          kb.get(path)             → GET data from the engine (e.g. "/stats")
 *          kb.post(path, body)      → ask the engine to do something
 *                                     (e.g. start model downloads)
 *          kb.pickFolder()          → Windows "choose folder" dialog
 *          kb.openReports()         → open the benchmark reports folder
 *          kb.engineStatus()        → current engine status
 *          kb.onEngineStatus(cb)    → be told whenever engine status changes
 *
 * WHY:   With contextIsolation + sandbox (set in main.cjs) the page cannot
 *        reach Electron or Node.js at all. This file decides exactly what it
 *        CAN do — nothing more. Engine requests still pass through main.cjs's
 *        allow-list and token check.
 *
 * WHEN:  Loaded by Electron into the window just before the page's own code.
 *
 * CONNECTED TO: electron/main.cjs (ipcMain handlers "engine:get",
 *        "engine:post", "dialog:pickFolder", "shell:openReports",
 *        "engine:status", and the "engine:status" event);
 *        src/App.jsx and src/SetupWizard.jsx (the callers).
 */
const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("kb", {
  /** Fetch JSON from an allowed engine endpoint. Resolves to data or {error}. */
  get: (enginePath) => ipcRenderer.invoke("engine:get", enginePath),

  /** POST to an allowed engine endpoint. Resolves to data or {error}. */
  post: (enginePath, body) => ipcRenderer.invoke("engine:post", enginePath, body),

  /** Resolve to the chosen folder path, or null if cancelled. */
  pickFolder: () => ipcRenderer.invoke("dialog:pickFolder"),

  /** Open the reports folder in File Explorer. */
  openReports: () => ipcRenderer.invoke("shell:openReports"),

  /** Resolve to {status: "starting"|"ready"|"error", detail}. */
  engineStatus: () => ipcRenderer.invoke("engine:status"),

  /**
   * Subscribe to engine status changes. Returns an unsubscribe function so
   * React components can clean up when they unmount (avoids duplicate
   * listeners piling up).
   */
  onEngineStatus: (callback) => {
    const listener = (_event, state) => callback(state);
    ipcRenderer.on("engine:status", listener);
    return () => ipcRenderer.removeListener("engine:status", listener);
  },
});
