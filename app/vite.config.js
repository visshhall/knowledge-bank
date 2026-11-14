/**
 * vite.config.js — build settings for the app's interface (React).
 *
 * WHAT:  Tells Vite (the tool that bundles the React interface) how to run
 *        the live-reload dev server and how to build the final files.
 * WHY:   - base: './' makes the built files load from disk (file://) inside
 *          Electron — without it, the packaged app would show a blank window.
 *        - The dev server is pinned to 127.0.0.1:5173 so `npm run dev` and
 *          electron/main.cjs agree on where to find it, and it is never
 *          reachable from the network.
 *        - injectCsp() adds the Content-Security-Policy security lock to the
 *          built index.html only (see below for why not in development).
 * WHEN:  Used by `npm run dev` (development) and `npm run build` (release).
 * CONNECTED TO: package.json scripts; index.html; electron/main.cjs loads
 *        either the dev server URL or dist/index.html produced here.
 */
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

/**
 * The page may only load its own scripts/styles/images and may not contact
 * ANY address (connect-src 'none'): all engine traffic goes through
 * window.kb (preload.cjs → main.cjs), so the page never needs network access.
 * 'unsafe-inline' for styles only is required by React style attributes;
 * scripts stay strictly 'self'.
 */
const CSP =
  "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; " +
  "img-src 'self' data:; connect-src 'none'; object-src 'none'; " +
  "base-uri 'none'; form-action 'none'";

/**
 * Vite plugin that writes the CSP <meta> tag into index.html at BUILD time.
 * apply: "build" → skipped in development, where the React live-reload
 * helper relies on a small inline script that this policy would block.
 */
function injectCsp() {
  return {
    name: "kb-inject-csp",
    apply: "build",
    transformIndexHtml(html) {
      return html.replace(
        "<head>",
        `<head>\n    <meta http-equiv="Content-Security-Policy" content="${CSP}" />`
      );
    },
  };
}

export default defineConfig({
  plugins: [react(), injectCsp()],
  base: "./",
  server: { host: "127.0.0.1", port: 5173, strictPort: true },
  build: { outDir: "dist", emptyOutDir: true },
});
