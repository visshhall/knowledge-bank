/**
 * main.jsx — entry point of the React interface.
 *
 * WHAT:  Loads the two typefaces and the stylesheet, then mounts <App /> into
 *        <div id="root"> in index.html.
 * WHY:   The fonts are bundled into the app by Vite (from npm packages), so
 *        they work fully offline — no font downloads at runtime.
 *          - Bricolage Grotesque: headings and big numbers; characterful,
 *            gives the app its own voice.
 *          - Atkinson Hyperlegible: everything else; designed for maximum
 *            legibility (clear 0/O, 1/l/I), ideal for long study sessions
 *            and for event IDs and query text.
 *        StrictMode runs extra checks in development only.
 * WHEN:  Runs once when the window loads.
 * CONNECTED TO: index.html (host), App.jsx, styles.css.
 */
import React from "react";
import { createRoot } from "react-dom/client";
import "@fontsource-variable/bricolage-grotesque/opsz.css";
import "@fontsource/atkinson-hyperlegible/400.css";
import "@fontsource/atkinson-hyperlegible/700.css";
import App from "./App.jsx";
import "./styles.css";

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
