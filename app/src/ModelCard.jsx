/**
 * ModelCard.jsx — "Models for Chat" card on the Setup screen (v0.11).
 *
 * WHAT:  - Lists the AI models installed on this laptop (size, last measured
 *          speed) and lets you choose which one Chat uses ("Use for Chat").
 *        - Suggests a few other small models that fit a 4 GB graphics card
 *          (Phi-4-mini, Gemma 3 4B, Llama 3.2 3B, Qwen 3.5 2B) with a
 *          Download button. Nothing is downloaded unless you press it.
 *        - "Compare on my files": pick 2–3 installed models; the SAME
 *          questions are put to each with the SAME passages from your
 *          library (three questions made from your biggest topics, or your
 *          own — one per line). You see speed, how many sources each answer
 *          cited, how many unsupported sentences the fact check removed, and
 *          the answers side by side. Better = faster, more sources cited,
 *          fewer removed — but you read the answers and decide.
 * WHY:   The owner asked for a model picker so other small models can be
 *        tried against qwen3.5:4b on his own PDFs. Public rankings say
 *        little about cybersecurity documents on a 4 GB card.
 * WHEN:  Rendered by SetupScreen in App.jsx. Polls the engine every 3 s
 *        (downloads) and 1.5 s (a running comparison).
 * CONNECTED TO: bridge.js → engine /models/choices, /models/select,
 *        /models/download, /models/compare/start, /models/compare/status,
 *        /models/compare/cancel (server.py → modelpick.py).
 */
import { useState } from "react";
import Icon from "./icons.jsx";
import { Formatted } from "./Formatted.jsx";
import { kb, usePoll } from "./bridge.js";

export default function ModelCard() {
  const [choices, reload] = usePoll("/models/choices", 3000);
  const [cmp, reloadCmp] = usePoll("/models/compare/status", 1500);
  const [picked, setPicked] = useState(() => new Set());
  const [own, setOwn] = useState("");
  const [notice, setNotice] = useState("");

  const installed = choices?.installed ?? [];
  const download = choices?.download ?? {};
  const downloading = download.state === "running";
  const comparing = cmp?.state === "running";

  async function use(model) {
    const r = await kb.post("/models/select", { model });
    setNotice(r.message || r.error || "");
    reload();
  }

  async function get(model) {
    const r = await kb.post("/models/download", { model });
    setNotice(r.message || r.error || "");
    reload();
  }

  function toggle(name) {
    setPicked((cur) => {
      const next = new Set(cur);
      if (next.has(name)) next.delete(name);
      else if (next.size < 3) next.add(name);
      return next;
    });
  }

  async function compare() {
    const questions = own.split("\n").map((q) => q.trim()).filter(Boolean);
    const r = await kb.post("/models/compare/start", { models: [...picked], questions: questions.length ? questions : null });
    setNotice(r.message || r.error || "");
    reloadCmp();
  }

  const results = cmp?.results ?? [];

  return (
    <section className="card updates model-card" aria-label="Models for Chat">
      <div className="section-head">
        <div>
          <h2>Models for Chat</h2>
          <p className="muted small">
            Chat uses <strong>{choices?.current ?? "…"}</strong>. Try another small model, then compare it with your current one
            on your own files before you switch.
          </p>
        </div>
      </div>
      {notice && <p className="notice">{notice}</p>}
      {choices && !choices.ollama && <p className="notice error">The AI engine (Ollama) isn't running. Start it above.</p>}

      {installed.length > 0 && (
        <ul className="model-list">
          {installed.map((m) => (
            <li key={m.name}>
              <label className="model-pick" title="Tick 2 or 3 models to compare them on your files">
                <input type="checkbox" checked={picked.has(m.name)} onChange={() => toggle(m.name)} disabled={comparing} />
                <strong>{m.name}</strong>
              </label>
              <span className="muted small">
                {m.size_mb >= 1024 ? `${(m.size_mb / 1024).toFixed(1)} GB` : `${m.size_mb} MB`}
                {m.speed ? ` · ${m.speed.value} ${m.speed.kind === "tokens/s" ? "words/s" : m.speed.kind} at ${m.speed.at}` : ""}
              </span>
              {m.current ? (
                <span className="state state-up_to_date">Used by Chat</span>
              ) : (
                <button className="secondary small-btn" onClick={() => use(m.name)}>
                  Use for Chat
                </button>
              )}
            </li>
          ))}
        </ul>
      )}

      {choices?.suggested?.length > 0 && (
        <>
          <h3 className="model-sub">Other models that fit a 4 GB card</h3>
          <ul className="model-list">
            {choices.suggested.map((s) => (
              <li key={s.name}>
                <strong>{s.name}</strong>
                <span className="muted small">
                  about {s.approx_gb} GB · {s.note}
                </span>
                <button className="secondary small-btn" onClick={() => get(s.name)} disabled={downloading}>
                  <Icon name="upload" size={14} /> Download
                </button>
              </li>
            ))}
          </ul>
          {downloading && <p className="muted small" aria-live="polite">{download.message}</p>}
          {download.state === "error" && <p className="notice error">{download.message}</p>}
        </>
      )}

      <h3 className="model-sub">Compare on my files</h3>
      <p className="muted small">
        Tick 2 or 3 models above. Each answers the same questions from the same passages of your library. This takes a few
        minutes and uses the graphics card, so don't write articles at the same time.
      </p>
      <textarea
        className="model-questions"
        value={own}
        onChange={(e) => setOwn(e.target.value)}
        rows={3}
        placeholder="Optional: your own questions, one per line (up to 5). Leave empty to use questions made from your biggest topics."
        aria-label="Your own questions for the comparison"
        disabled={comparing}
      />
      <div className="model-actions">
        <button onClick={compare} disabled={comparing || picked.size < 2 || !choices?.ollama}>
          {comparing ? "Comparing…" : picked.size < 2 ? "Compare models" : `Compare ${picked.size} models`}
        </button>
        {comparing && (
          <button className="secondary" onClick={() => kb.post("/models/compare/cancel", {}).then(reloadCmp)}>
            Stop
          </button>
        )}
        {comparing && (
          <span className="muted small" aria-live="polite">
            {cmp.stage} ({cmp.done} of {cmp.total} done)
          </span>
        )}
      </div>
      {cmp?.state === "error" && <p className="notice error">{cmp.message}</p>}

      {results.length > 0 && (
        <>
          <table className="model-table">
            <thead>
              <tr>
                <th>Model</th>
                <th>Words per second</th>
                <th>Seconds per answer</th>
                <th>Sources cited</th>
                <th>Unsupported sentences removed</th>
              </tr>
            </thead>
            <tbody>
              {results.map((r) => (
                <tr key={r.model}>
                  <th scope="row">{r.model}</th>
                  <td>{r.avg_tokens_per_s}</td>
                  <td>{r.avg_seconds}</td>
                  <td>{r.cited_total}</td>
                  <td>{r.removed_total}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="muted small">
            Faster is better, more cited sources is better, fewer removed sentences is better. Numbers can't tell you
            whether an answer is useful — read them below.
          </p>
          {(cmp.questions ?? []).map((q, qi) => (
            <div key={q} className="model-qa">
              <p className="model-q">{q}</p>
              <div className="model-cols" style={{ gridTemplateColumns: `repeat(${results.length}, minmax(0, 1fr))` }}>
                {results.map((r) => {
                  const a = r.answers[qi];
                  return (
                    <div key={r.model} className="model-col">
                      <p className="small">
                        <strong>{r.model}</strong>
                        {a ? ` · ${a.seconds}s · ${a.removed_count} removed` : ""}
                      </p>
                      {a ? <Formatted text={a.answer} collapseAt={8} /> : <p className="muted small">Not answered (stopped).</p>}
                    </div>
                  );
                })}
              </div>
            </div>
          ))}
        </>
      )}
    </section>
  );
}
