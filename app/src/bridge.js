/**
 * bridge.js — one shared handle to `window.kb` for every React component.
 *
 * WHAT:  Exports `kb`: the real bridge from electron/preload.cjs when running
 *        inside the app, or a harmless stub when the page is opened in a
 *        normal browser (e.g. design work), so screens still render and
 *        explain why there's no data.
 * WHY:   Avoids repeating the same fallback in every component.
 * WHEN:  Imported by App.jsx and SetupWizard.jsx at load time.
 * CONNECTED TO: electron/preload.cjs (defines the real window.kb).
 */
const NOT_IN_APP = { error: "Not running inside the Knowledge Bank app" };

export const kb =
  window.kb ?? {
    get: async () => NOT_IN_APP,
    post: async () => NOT_IN_APP,
    pickFolder: async () => null,
    openReports: async () => NOT_IN_APP,
    engineStatus: async () => ({ status: "error", detail: "Not running inside the app" }),
    onEngineStatus: () => () => {},
  };
