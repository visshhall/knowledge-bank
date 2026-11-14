/**
 * main.jsx — entry point of the React interface.
 *
 * WHAT:  Mounts the <App /> component into <div id="root"> in index.html
 *        and loads the global stylesheet.
 * WHY:   StrictMode runs extra checks during development (e.g. warns about
 *        listeners that aren't cleaned up). It has no effect in the built app.
 * WHEN:  Runs once when the window loads.
 * CONNECTED TO: index.html (host), App.jsx (the interface), styles.css.
 */
import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import "./styles.css";

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
