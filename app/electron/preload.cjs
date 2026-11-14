/**
 * preload.cjs — the only bridge between the interface and the rest of the app.
 *
 * WHAT:  Exposes a tiny, fixed set of functions to the page as `window.kb`:
 *          kb.get(path, params)     → GET data from the engine
 *                                     (e.g. kb.get("/search", { q: "4625" }))
 *          kb.post(path, body)      → ask the engine to do something
 *          kb.pickFolder(purpose)   → "choose folder" dialog
 *                                     (purpose: "import" | "watch" | "benchmark")
 *          kb.pickFiles()           → "open files" dialog (PDFs + images)
 *          kb.pathForFile(file)     → real disk path of a file dropped on
 *                                     the window (drag-and-drop import)
 *          kb.openReports()         → open the benchmark reports folder
 *          kb.appVersion()          → installed version, e.g. "0.6.1"
 *          kb.openFile(id, page)    → open an imported file at a page (v0.7)
 *          kb.webOpen(kind, value)  → optional web look-up in the browser (v0.7)
 *          kb.saveBackupDialog() / kb.pickBackupDialog() / kb.restart() (v0.7)
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
 *        "engine:post", "dialog:pickFolder", "dialog:pickFiles",
 *        "shell:openReports", "app:version", "file:open", "web:open", "dialog:saveBackup", "dialog:pickBackup", "app:restart", "engine:status", and the "engine:status"
 *        event); src/*.jsx via src/bridge.js.
 */
const { contextBridge, ipcRenderer, webUtils } = require("electron");

contextBridge.exposeInMainWorld("kb", {
  /** GET from an allowed engine endpoint. Resolves to data or {error}. */
  get: (enginePath, params) => ipcRenderer.invoke("engine:get", enginePath, params),

  /** POST to an allowed engine endpoint. Resolves to data or {error}. */
  post: (enginePath, body) => ipcRenderer.invoke("engine:post", enginePath, body),

  /** Resolve to the chosen folder path, or null if cancelled. */
  pickFolder: (purpose) => ipcRenderer.invoke("dialog:pickFolder", purpose),

  /** Resolve to an array of chosen file paths (empty if cancelled). */
  pickFiles: () => ipcRenderer.invoke("dialog:pickFiles"),

  /**
   * Disk path of a File from a drag-and-drop event. Electron removed the old
   * File.path property for security; webUtils is the supported replacement.
   * Returns "" for things that aren't real files (e.g. dragged text).
   */
  pathForFile: (file) => {
    try {
      return webUtils.getPathForFile(file);
    } catch {
      return "";
    }
  },

  /** Open an imported file (PDFs at the given page, in a viewer window). */
  openFile: (sourceId, page) => ipcRenderer.invoke("file:open", sourceId, page),

  /** Open a web look-up in the normal browser: kind = search|mitre|virustotal|cve. */
  webOpen: (kind, value) => ipcRenderer.invoke("web:open", kind, value),

  /** Backup dialogs + restart (v0.7). */
  saveBackupDialog: () => ipcRenderer.invoke("dialog:saveBackup"),
  pickBackupDialog: () => ipcRenderer.invoke("dialog:pickBackup"),
  restart: () => ipcRenderer.invoke("app:restart"),

  /** Resolve to the app version, e.g. "0.6.1" (shown top-right). */
  appVersion: () => ipcRenderer.invoke("app:version"),

  /** Open the reports folder in File Explorer. */
  openReports: () => ipcRenderer.invoke("shell:openReports"),

  /** Resolve to {status: "starting"|"ready"|"error", detail}. */
  engineStatus: () => ipcRenderer.invoke("engine:status"),

  /**
   * Subscribe to engine status changes. Returns an unsubscribe function so
   * React components can clean up when they unmount.
   */
  onEngineStatus: (callback) => {
    const listener = (_event, state) => callback(state);
    ipcRenderer.on("engine:status", listener);
    return () => ipcRenderer.removeListener("engine:status", listener);
  },
});
