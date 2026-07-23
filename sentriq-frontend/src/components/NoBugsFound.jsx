import { useEffect, useRef } from "react";

// Confetti fires at most once per full browser page load. A hard reload of the
// page resets this flag because the module is re-evaluated; navigating within
// the SPA (re-mounts, tab switches, polling refreshes) does not.
let hasFiredConfetti = false;

const CONFETTI_COLORS = [
  "#afc6ff", // primary
  "#528dff", // primary container
  "#ffffff", // white
  "#ffb77b", // tertiary
  "#00e676", // green
];

/**
 * Celebratory empty state for the Live Findings dashboard.
 * Renders a prominent, centered panel inside a single table cell (or any
 * container). Fires a self-contained DOM confetti burst exactly once per page
 * load and cleans up after itself on unmount.
 */
export default function NoBugsFound() {
  const containerRef = useRef(null);

  useEffect(() => {
    // If confetti already fired in this page load, do nothing. This prevents
    // re-firing on tab switches, polling refreshes, or re-mounts.
    if (hasFiredConfetti) return;

    const container = containerRef.current;
    if (!container) return;

    const wrapper = document.createElement("div");
    wrapper.style.position = "absolute";
    wrapper.style.inset = "0";
    wrapper.style.pointerEvents = "none";
    wrapper.style.zIndex = "0";
    wrapper.style.overflow = "hidden";
    wrapper.setAttribute("aria-hidden", "true");
    container.appendChild(wrapper);

    const width = container.clientWidth;
    const height = container.clientHeight;

    // Build a burst of 60 rectangular pieces launched from the center.
    const particleCount = 60;
    const particles = [];
    for (let i = 0; i < particleCount; i++) {
      const angle = Math.random() * Math.PI * 2;
      const speed = Math.random() * 4 + 2;
      const color =
        CONFETTI_COLORS[Math.floor(Math.random() * CONFETTI_COLORS.length)];
      const size = Math.random() * 6 + 4;

      const el = document.createElement("div");
      el.style.position = "absolute";
      el.style.left = "0";
      el.style.top = "0";
      el.style.width = `${size}px`;
      el.style.height = `${size * 0.6}px`;
      el.style.backgroundColor = color;
      el.style.willChange = "transform, opacity";
      wrapper.appendChild(el);

      particles.push({
        el,
        x: width / 2,
        y: height / 2,
        vx: Math.cos(angle) * speed,
        vy: Math.sin(angle) * speed - 3,
        gravity: 0.15,
        drag: 0.96,
        size,
        rotation: Math.random() * Math.PI * 2,
        rotationSpeed: (Math.random() - 0.5) * 0.3,
        opacity: 1,
        decay: Math.random() * 0.008 + 0.004,
      });
    }

    let rafId = 0;
    let startTime = null;
    const duration = 2800; // ms

    const cleanup = () => {
      if (rafId) {
        cancelAnimationFrame(rafId);
        rafId = 0;
      }
      if (wrapper.parentNode === container) {
        container.removeChild(wrapper);
      }
    };

    const draw = (timestamp) => {
      if (!startTime) startTime = timestamp;
      const elapsed = timestamp - startTime;

      let active = 0;
      for (const p of particles) {
        if (p.opacity <= 0 || p.y > height + 20) continue;
        active += 1;

        p.vx *= p.drag;
        p.vy *= p.drag;
        p.vy += p.gravity;
        p.x += p.vx;
        p.y += p.vy;
        p.rotation += p.rotationSpeed;
        p.opacity -= p.decay;

        p.el.style.transform = `translate(${p.x - p.size / 2}px, ${
          p.y - p.size / 2
        }px) rotate(${p.rotation}rad)`;
        p.el.style.opacity = Math.max(0, p.opacity).toString();
      }

      if (elapsed < duration && active > 0) {
        rafId = requestAnimationFrame(draw);
      } else {
        cleanup();
      }
    };

    // Mark confetti as fired so this SPA session never fires again.
    hasFiredConfetti = true;
    rafId = requestAnimationFrame(draw);

    return cleanup;
  }, []);

  return (
    <tr>
      <td colSpan={6} className="p-4 md:p-6">
        <div
          ref={containerRef}
          className="relative overflow-hidden bg-surface-container border-2 border-outline p-8 md:p-12 text-center flex flex-col items-center justify-center gap-4 max-w-xl mx-auto"
        >
          <div className="relative z-10 flex flex-col items-center gap-3">
            <h3 className="font-display-lg text-display-lg text-primary uppercase tracking-tight">
              NO BUGS FOUND
            </h3>
            <p className="font-body-md text-body-md text-on-surface">
              Clean scan — nothing to fix.
            </p>
          </div>
        </div>
      </td>
    </tr>
  );
}
