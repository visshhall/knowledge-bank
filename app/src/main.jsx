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
 *        v0.8: wraps everything in CrashGuard so a screen error never
 *        leaves a blank window.
 * CONNECTED TO: index.html (host), App.jsx, styles.css.
 */
import React from "react";
import { createRoot } from "react-dom/client";
import "@fontsource-variable/dm-sans/opsz.css";
import "@fontsource-variable/literata/opsz.css";
import App from "./App.jsx";
import "./styles.css";

/**
 * Crash guard (v0.8).
 * WHY:  Without it, any error while drawing a screen (a bad diagram, or a
 *       screen part that failed to load) leaves the whole window blank, and
 *       the owner has no way back except closing the app.
 * HOW:  React calls getDerivedStateFromError when anything below it throws;
 *       we show a short message and a "Reload the window" button instead.
 *       Documents and the bank are not touched — it only redraws the screen.
 */
class CrashGuard extends React.Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }
  static getDerivedStateFromError(error) {
    return { error };
  }
  componentDidCatch(error) {
    console.error("[ui] screen crashed:", error);
  }
  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="card" style={{ maxWidth: 520, margin: "15vh auto", padding: 32, textAlign: "center" }}>
        <h2>This screen hit a problem</h2>
        <p className="muted">Your files and topics are safe. Reload the window to carry on.</p>
        <button onClick={() => window.location.reload()}>Reload the window</button>
      </div>
    );
  }
}

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <CrashGuard>
      <App />
    </CrashGuard>
  </React.StrictMode>
);
