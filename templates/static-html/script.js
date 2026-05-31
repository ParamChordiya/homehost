/**
 * HomeHost — Static-HTML Template Script
 * ✏️ Edit freely — this file controls interactive behaviour.
 */

/* ──────────────────────────────────────────────────────
   1. Theme toggle (dark ↔ light)
   Persists the user's choice in localStorage.
   ────────────────────────────────────────────────────── */
(function initTheme() {
  const root = document.documentElement;
  const btn = document.getElementById("theme-toggle");
  if (!btn) return;

  const stored = localStorage.getItem("hh-theme");
  const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
  let isDark = stored ? stored === "dark" : prefersDark;

  function applyTheme(dark) {
    root.setAttribute("data-theme", dark ? "dark" : "light");
    btn.textContent = dark ? "☀️" : "🌙";
    btn.setAttribute("aria-label", dark ? "Switch to light mode" : "Switch to dark mode");
  }

  applyTheme(isDark);

  btn.addEventListener("click", () => {
    isDark = !isDark;
    applyTheme(isDark);
    localStorage.setItem("hh-theme", isDark ? "dark" : "light");
  });
})();

/* ──────────────────────────────────────────────────────
   2. Animated visit counter
   Counts up from 0 to a target value with easing.
   ────────────────────────────────────────────────────── */
(function animateCounter() {
  const el = document.getElementById("counter-visits");
  if (!el) return;

  // In a real app you'd fetch this from your API.
  // For the template we simulate a plausible daily count.
  const target = Math.floor(Math.random() * 80) + 20; // 20–99
  const duration = 1400; // ms
  const start = performance.now();

  function easeOutQuart(t) {
    return 1 - Math.pow(1 - t, 4);
  }

  function tick(now) {
    const elapsed = now - start;
    const progress = Math.min(elapsed / duration, 1);
    const value = Math.round(easeOutQuart(progress) * target);
    el.textContent = value;
    if (progress < 1) requestAnimationFrame(tick);
  }

  // Only start when the element enters the viewport
  const observer = new IntersectionObserver(
    (entries) => {
      if (entries[0].isIntersecting) {
        requestAnimationFrame(tick);
        observer.disconnect();
      }
    },
    { threshold: 0.5 }
  );
  observer.observe(el);
})();

/* ──────────────────────────────────────────────────────
   3. Smooth scroll for anchor links
   Native scroll-behavior: smooth is set in CSS, but this
   adds keyboard / reduced-motion awareness.
   ────────────────────────────────────────────────────── */
(function smoothScroll() {
  const prefersReduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  document.querySelectorAll('a[href^="#"]').forEach((anchor) => {
    anchor.addEventListener("click", (e) => {
      const id = anchor.getAttribute("href").slice(1);
      const target = document.getElementById(id);
      if (!target) return;
      e.preventDefault();
      target.scrollIntoView({
        behavior: prefersReduced ? "instant" : "smooth",
        block: "start",
      });
      // Move focus for keyboard users
      target.setAttribute("tabindex", "-1");
      target.focus({ preventScroll: true });
    });
  });
})();

/* ──────────────────────────────────────────────────────
   4. Scroll-reveal: fade cards in as they enter the viewport
   ────────────────────────────────────────────────────── */
(function scrollReveal() {
  if (!("IntersectionObserver" in window)) return;
  const prefersReduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (prefersReduced) return;

  const style = document.createElement("style");
  style.textContent = `
    .reveal {
      opacity: 0;
      transform: translateY(24px);
      transition: opacity 0.5s ease, transform 0.5s ease;
    }
    .reveal.visible {
      opacity: 1;
      transform: none;
    }
  `;
  document.head.appendChild(style);

  const targets = document.querySelectorAll(".card, .about-inner > *");
  targets.forEach((el, i) => {
    el.classList.add("reveal");
    el.style.transitionDelay = `${i * 80}ms`;
  });

  const observer = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          entry.target.classList.add("visible");
          observer.unobserve(entry.target);
        }
      });
    },
    { threshold: 0.15 }
  );

  targets.forEach((el) => observer.observe(el));
})();
