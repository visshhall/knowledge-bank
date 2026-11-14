/**
 * bridge.js — one shared handle to `window.kb` for every React component,
 *             plus small helpers several screens use.
 *
 * WHAT:  Exports `kb`: the real bridge from electron/preload.cjs when running
 *        inside the app, or a harmless stub when the page is opened in a
 *        normal browser (e.g. design work), so screens still render.
 *        Also exports usePoll() (refresh data on a timer) and formatting
 *        helpers.
 * WHY:   Avoids repeating the same fallback and polling code in every screen.
 * WHEN:  Imported by every screen at load time.
 * CONNECTED TO: electron/preload.cjs (defines the real window.kb).
 */
import { useCallback, useEffect, useRef, useState } from "react";

const NOT_IN_APP = { error: "Not running inside the Knowledge Bank app" };

export const kb =
  window.kb ?? {
    get: async () => NOT_IN_APP,
    post: async () => NOT_IN_APP,
    pickFolder: async () => null,
    pickFiles: async () => [],
    pathForFile: () => "",
    openReports: async () => NOT_IN_APP,
    appVersion: async () => "dev",
    engineStatus: async () => ({ status: "error", detail: "Not running inside the app" }),
    onEngineStatus: () => () => {},
  };

/**
 * Fetch `path` now and every `intervalMs` while the component is on screen.
 * RETURNS [data, reload] — call reload() after an action to refresh at once.
 * Errors leave the previous data in place (a brief engine hiccup doesn't
 * blank the screen).
 */
export function usePoll(path, intervalMs = 1500, params) {
  const [data, setData] = useState(null);
  const paramsKey = JSON.stringify(params ?? null);
  const latest = useRef(paramsKey);
  latest.current = paramsKey;

  const reload = useCallback(async () => {
    const result = await kb.get(path, params);
    if (!result?.error && latest.current === paramsKey) setData(result);
    return result;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, paramsKey]);

  useEffect(() => {
    reload();
    if (!intervalMs) return undefined;
    const id = setInterval(reload, intervalMs);
    return () => clearInterval(id);
  }, [reload, intervalMs]);

  return [data, reload];
}

/** "1.2 GB" / "340 MB" / "12 KB" for file sizes and download progress. */
export function formatBytes(bytes) {
  if (!bytes) return "0 KB";
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(1)} GB`;
  if (bytes >= 1024 ** 2) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  return `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

/** Percentage 0–100 from done/total (0 when total unknown). */
export function percent(done, total) {
  return total ? Math.min(100, Math.round((100 * done) / total)) : 0;
}

/** 12345 → "12,345" (Indian grouping is not used, to match file sizes). */
export function formatCount(n) {
  return typeof n === "number" ? n.toLocaleString("en-US") : "—";
}
