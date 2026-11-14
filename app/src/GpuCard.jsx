/**
 * GpuCard.jsx — "Graphics card" card on the Setup screen (v0.8.2).
 *
 * WHAT:  Shows whether the AI really runs on the graphics card:
 *          - the card's name and how much of its memory is in use
 *          - each AI model currently loaded, with the share of it held on
 *            the card (100% = full speed; less = part runs on the processor)
 *          - the last measured speed (words per second while writing,
 *            passages per second while grouping topics)
 *          - plain advice when something is holding it back
 *        "Test and tune speed" measures writing speed with Ollama's own
 *        split and with every layer forced onto the card, and keeps the
 *        faster one (engine gpu.py).
 * WHY:   Owner: "make sure all this is done on GPU and not CPU, it's very
 *        slow". His benchmark (11.6 tokens/s) pointed to part of the model
 *        running on the processor; this card makes that visible and fixable.
 * WHEN:  Rendered by SetupScreen in App.jsx; refreshes every 3 s.
 * CONNECTED TO: bridge.js → engine GET /gpu/status, POST /gpu/tune
 *        (server.py → gpu.py, ollama_client.py, system_check.py).
 */
import { useState } from "react";
import Icon from "./icons.jsx";
import { kb, usePoll } from "./bridge.js";

/** "62%" with a colour class: full = good, partial = warn. */
function Share({ value }) {
  if (value == null) return <span className="state">—</span>;
  const pct = Math.round(value * 100);
  return (
    <span className={`state ${pct >= 99 ? "state-up_to_date" : "state-update_available"}`}>
      {pct >= 99 ? "100% on graphics card" : `${pct}% on graphics card`}
    </span>
  );
}

export default function GpuCard() {
  const [status, reload] = usePoll("/gpu/status", 3000);
  const [notice, setNotice] = useState("");
  const gpu = status?.gpu;
  const tuning = status?.tuning;
  const running = tuning?.state === "running";

  async function tune() {
    const r = await kb.post("/gpu/tune", {});
    setNotice(r.message || r.error || "");
    reload();
  }

  const speeds = Object.entries(status?.speeds ?? {});
  const tuned = Object.values(status?.tuned ?? {});

  return (
    <section className="card updates gpu-card" aria-label="Graphics card">
      <div className="section-head">
        <div>
          <h2>Graphics card</h2>
          <p className="muted small">
            {gpu?.available
              ? `${gpu.name} · ${gpu.vram_used_mb} of ${gpu.vram_total_mb} MB in use`
              : gpu
                ? "No NVIDIA graphics card found by its driver."
                : "Checking…"}
            {status?.memory_savers ? " · memory savers on" : ""}
          </p>
        </div>
        <button className="secondary" onClick={tune} disabled={running}>
          <Icon name="refresh" size={16} />
          {running ? "Measuring…" : "Test and tune speed"}
        </button>
      </div>

      {(running || tuning?.message) && <p className="notice ok">{tuning.message}</p>}
      {notice && !running && !tuning?.message && <p className="notice ok">{notice}</p>}
      {status?.advice?.map((a) => (
        <p key={a} className="notice error">
          {a}
        </p>
      ))}

      <ul className="update-list">
        {(status?.loaded ?? []).map((m) => (
          <li key={m.name}>
            <div>
              <p className="update-name">{m.name}</p>
              <p className="small muted">
                {m.vram_mb} of {m.size_mb} MB on the graphics card
              </p>
            </div>
            <Share value={m.gpu_share} />
          </li>
        ))}
        {status && !status.loaded?.length && (
          <li>
            <p className="small muted">No AI model is loaded right now. Shares appear while topics or articles are being made.</p>
          </li>
        )}
      </ul>

      {(speeds.length > 0 || tuned.length > 0) && (
        <p className="small muted foot-note">
          {speeds.map(([name, s]) => `${name}: ${s.value} ${s.kind === "tokens/s" ? "words/s writing" : "passages/s"} (${s.at})`).join(" · ")}
          {tuned.map((t) =>
            t.ok
              ? ` · Tuned ${t.at}: ${t.chosen === "forced" ? "every layer on the card" : "Ollama's own split"} was faster (${t.auto?.tokens_per_s ?? "?"} vs ${t.forced?.tokens_per_s ?? "?"} words/s)`
              : ""
          )}
        </p>
      )}
      <p className="small muted foot-note">
        On a 4 GB card the writing model only just fits. For full speed keep games, video and other AI apps closed
        while topics and articles are being made.
      </p>
    </section>
  );
}
