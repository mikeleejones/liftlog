"use strict";

// Ticks the minimized-session bar (BACKLOG item 20). Shows the live rest
// countdown when one is running, otherwise elapsed session time. Read-only: it
// never touches the wake lock (the screen has no reason to stay awake while you
// browse other tabs) and never writes session state — the full Active Workout
// view owns that.
(function () {
  const bar = document.querySelector(".minibar");
  if (!bar) return;
  const meta = document.getElementById("minibar-meta");
  const workoutId = Number(bar.dataset.workoutId);
  // "2026-07-20T14:44:12Z" — explicit UTC, matching the server's utcnow()
  const startedAt = Date.parse(bar.dataset.startedAt);
  // how long "rest done" keeps showing before the bar falls back to elapsed,
  // matching the full view's 4s auto-hide
  const DONE_LINGER_MS = 4000;

  function clock(totalSeconds) {
    const s = Math.max(0, Math.round(totalSeconds));
    return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
  }

  function tick() {
    const now = Date.now();
    const rec = window.LiftLogSession.read(workoutId);
    const endsAt = rec && rec.restEndsAt;
    if (endsAt && now < endsAt) {
      meta.textContent = `rest ${clock((endsAt - now) / 1000)}`;
      bar.classList.add("resting");
      return;
    }
    if (endsAt && now < endsAt + DONE_LINGER_MS) {
      meta.textContent = "rest done";
      bar.classList.add("resting");
      return;
    }
    bar.classList.remove("resting");
    meta.textContent = Number.isNaN(startedAt)
      ? "in progress"
      : `${clock((now - startedAt) / 1000)} elapsed`;
  }

  tick();
  setInterval(tick, 1000);
})();
