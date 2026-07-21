"use strict";

// The small slice of Active Workout state that has to survive a page load
// (BACKLOG item 20). Minimizing a session navigates to another tab, so the rest
// countdown and the current exercise position would otherwise be lost the moment
// you leave — this keeps both in localStorage, keyed to the workout id so a
// stale record from a previous session is ignored rather than misapplied.
//
// Presentation state only. Nothing here is training data: every set is already
// on the server the instant it's logged, so clearing localStorage costs you a
// scroll position and a countdown, never a rep.
window.LiftLogSession = (function () {
  const KEY = "liftlog.session";

  function read(workoutId) {
    try {
      const raw = localStorage.getItem(KEY);
      if (!raw) return null;
      const rec = JSON.parse(raw);
      return rec && rec.workoutId === workoutId ? rec : null;
    } catch (err) {
      return null; // unparseable / storage disabled — behave as if empty
    }
  }

  function write(workoutId, patch) {
    try {
      const rec = read(workoutId) || { workoutId };
      localStorage.setItem(KEY, JSON.stringify(Object.assign(rec, patch)));
    } catch (err) {
      /* private mode / quota — the session still works, it just won't survive
         a navigation. Never worth breaking a set over. */
    }
  }

  return {
    read,
    // the exercise the user is actually on, so returning from minimized lands
    // where they left off rather than at the first unfinished exercise
    saveIndex(workoutId, index) {
      write(workoutId, { exerciseIndex: index });
    },
    // endsAt is an absolute epoch ms so the countdown stays truthful across a
    // navigation; total is kept for the progress fill's denominator
    saveRest(workoutId, totalSeconds, endsAt) {
      write(workoutId, { restTotal: totalSeconds, restEndsAt: endsAt });
    },
    clearRest(workoutId) {
      write(workoutId, { restTotal: null, restEndsAt: null });
    },
    clear() {
      try {
        localStorage.removeItem(KEY);
      } catch (err) {
        /* nothing to do */
      }
    },
  };
})();
