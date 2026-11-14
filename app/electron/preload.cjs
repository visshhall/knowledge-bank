/**
 * preload.cjs — the only bridge between the interface and the rest of the app.
 *
 * WHAT:  Exposes a tiny, fixed set of functions to the page as `window.kb`:
 *          kb.get(path)            → ask the engine for data (e.g. "/stats")
 *          kb.engineStatus()       → current engine status
 *          kb.onEngineStatus(cb)   → be told whenever engine status changes
 *
 * WHY:   With contextIsolation + sandbox (set in main.cjs) the page cannot
 *        reach Electron or Node.js at all. This file decides exactly what it
 *        CAN do — nothing more. Engine requests still pass through main.cjs's
 *        allow-list and token check.
 *
 * WHEN:  Loaded by Electron into the window just before the page's own code.
 *
 * CONNECTED TO: electron/main.cjs (ipcMain handlers "engine:get",
 *        "engine:status", event "engine:status"); src/App.jsx (the caller).
 */
const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("kb", {
  /** Fetch JSON from an allowed engine endpoint. Resolves to data or {error}. */
  get: (enginePath) => ipcRenderer.invoke("engine:get", enginePath),

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
