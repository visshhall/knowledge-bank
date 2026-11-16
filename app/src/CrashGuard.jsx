/**
 * CrashGuard.jsx — keeps one broken screen from blanking the whole window.
 *
 * WHAT:  A React error boundary. If anything inside it throws while drawing, it shows a short message with
 *        "Try again" (redraws just that part) and "Reload the window" instead of a blank screen.
 * WHY:   v0.8 had one guard around the whole app, so a crash on one screen hid the sidebar too and the only way
 *        out was a reload. v0.22.1 (owner: "screen stopped loading") also wraps each screen on its own, keyed by
 *        the screen name, so moving to another screen clears the error and the sidebar always keeps working.
 * WHEN:  main.jsx wraps <App/> (last resort); App.jsx wraps the current screen (normal case).
 * CONNECTED TO: main.jsx, App.jsx. Errors are written to the console ("[ui] screen crashed") for diagnosis.
 */
import React from "react";

export default class CrashGuard extends React.Component {
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
      <div className="card" role="alert" style={{ maxWidth: 520, margin: "15vh auto", padding: 32, textAlign: "center" }}>
        <h2>This screen hit a problem</h2>
        <p className="muted">Your files and topics are safe. Try again, or pick another screen on the left.</p>
        <p className="muted small">{String(this.state.error?.message ?? this.state.error).slice(0, 160)}</p>
        <div style={{ display: "flex", gap: 10, justifyContent: "center" }}>
          <button onClick={() => this.setState({ error: null })}>Try again</button>
          <button className="secondary" onClick={() => window.location.reload()}>Reload the window</button>
        </div>
      </div>
    );
  }
}
