/**
 * Constellation.jsx — animated background of drifting, connected points.
 *
 * WHAT:  Draws softly glowing dots that drift slowly and link with faint
 *        lines when near each other, on a full-screen <canvas>.
 * WHY:   The owner asked for an interactive, animated app rather than a
 *        "boring PDF" feel. This is the visual seed of the Phase 4 Knowledge
 *        Map (where each dot will become a real topic). In Phase 0 it is
 *        decoration only — it shows no data.
 * WHEN:  Mounted by App.jsx behind all content, for the app's lifetime.
 * HOW:   requestAnimationFrame loop (~60 fps, paused automatically by the
 *        browser when the window is hidden). Uses fewer points on small
 *        windows. If Windows' "reduce animations" setting is on, it draws
 *        one still frame instead of animating (accessibility).
 * CONNECTED TO: App.jsx only. Standalone otherwise — reads no engine data.
 */
import { useEffect, useRef } from "react";

/** Points closer than this (px) are joined by a line. */
const LINK_DISTANCE = 140;

export default function Constellation() {
  const canvasRef = useRef(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    const ctx = canvas.getContext("2d");
    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let points = [];
    let frameId = 0;

    /**
     * Size the canvas to the window (accounting for high-DPI screens so lines
     * stay crisp) and scatter a fresh set of points.
     */
    function resize() {
      const dpr = window.devicePixelRatio || 1;
      canvas.width = window.innerWidth * dpr;
      canvas.height = window.innerHeight * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      const count = Math.round((window.innerWidth * window.innerHeight) / 22000);
      points = Array.from({ length: count }, () => ({
        x: Math.random() * window.innerWidth,
        y: Math.random() * window.innerHeight,
        vx: (Math.random() - 0.5) * 0.25, // slow drift, px per frame
        vy: (Math.random() - 0.5) * 0.25,
        r: 1 + Math.random() * 1.8,
      }));
    }

    /** Draw one frame: move points (wrapping at edges), then lines, then dots. */
    function draw() {
      const w = window.innerWidth;
      const h = window.innerHeight;
      ctx.clearRect(0, 0, w, h);

      for (const p of points) {
        p.x = (p.x + p.vx + w) % w;
        p.y = (p.y + p.vy + h) % h;
      }

      // Lines: fade with distance so the web looks soft, not cluttered.
      for (let i = 0; i < points.length; i++) {
        for (let j = i + 1; j < points.length; j++) {
          const dx = points[i].x - points[j].x;
          const dy = points[i].y - points[j].y;
          const d = Math.hypot(dx, dy);
          if (d < LINK_DISTANCE) {
            ctx.strokeStyle = `rgba(94, 234, 212, ${0.12 * (1 - d / LINK_DISTANCE)})`;
            ctx.lineWidth = 1;
            ctx.beginPath();
            ctx.moveTo(points[i].x, points[i].y);
            ctx.lineTo(points[j].x, points[j].y);
            ctx.stroke();
          }
        }
      }

      for (const p of points) {
        ctx.fillStyle = "rgba(125, 211, 252, 0.55)";
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
        ctx.fill();
      }

      if (!reduceMotion) frameId = requestAnimationFrame(draw);
    }

    resize();
    draw();
    window.addEventListener("resize", resize);

    // Cleanup when the component unmounts: stop the loop and the listener.
    return () => {
      cancelAnimationFrame(frameId);
      window.removeEventListener("resize", resize);
    };
  }, []);

  return <canvas ref={canvasRef} className="constellation" aria-hidden="true" />;
}
