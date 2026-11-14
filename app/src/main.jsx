/**
 * main.jsx — entry point of the React interface.
 *
 * WHAT:  Loads the two typefaces and the stylesheet, then mounts <App /> into
 *        <div id="root"> in index.html.
 * WHY:   The fonts are bundled into the app by Vite (from npm packages), so
 *        they work fully offline — no font downloads at runtime.
 *          - DM Sans: the interface (headings, buttons, numbers, labels).
 *            Friendly, geometric and very clear at small sizes.
 *          - Literata: reading text (topic points, search snippets). A
 *            book typeface designed for long on-screen reading — it makes
 *            the bank feel like a well-printed study book, not a dashboard.
 *        Both were chosen with the owner's "Sage Vivid" theme (v0.4).
 *        StrictMode runs extra checks in development only.
 * WHEN:  Runs once when the window loads.
 * CONNECTED TO: index.html (host), App.jsx, styles.css.
 */
import React from "react";
import { createRoot } from "react-dom/client";
import "@fontsource-variable/dm-sans/opsz.css";
import "@fontsource-variable/literata/opsz.css";
import App from "./App.jsx";
import "./styles.css";

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
