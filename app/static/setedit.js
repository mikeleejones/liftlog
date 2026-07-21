"use strict";

// Shared "correct a logged set" sheet (BACKLOG item 18), used by BOTH Active
// Workout's completed-sets list and Exercise Detail's history. Self-contained:
// it builds its own sheet DOM on first open, so neither template carries markup
// for it, and it wraps everything in an IIFE so its constants don't collide with
// workout.js's identically-named ones in the shared script scope.
//
// It deliberately does NOT reuse workout.js's stepper: that one is bound to the
// live-logging `pending`/`currentIndex` module state, and the gym-critical
// logging path is not worth destabilising to save a few lines here.
window.SetEdit = (function () {
  const KG_PER_LB = 0.45359237;
  const STEP = { kg: 2.5, lbs: 5 };
  const DIST_STEP = 0.1;
  const DURATION_STEP = 5;
  const M_PER_KM = 1000;
  const M_PER_MI = 1609.344;

  // same axis map as workout.js's TYPE_AXES and main.py's SET_AXES
  const TYPE_AXES = {
    weight_reps: ["weight", "reps"],
    reps_only: ["reps"],
    duration: ["duration"],
    duration_weight: ["weight", "duration"],
    distance: ["distance"],
    distance_weight: ["distance", "weight"],
    none: [],
  };

  function weightUnit(ctx) {
    return ctx.exercise_type === "distance_weight" ? "kg" : ctx.display_unit;
  }
  function distanceUnit(ctx) {
    return ctx.display_unit;
  }
  function toDisplay(kg, unit) {
    return unit === "kg" ? kg : kg / KG_PER_LB;
  }
  function toKg(v, unit) {
    return unit === "kg" ? v : v * KG_PER_LB;
  }
  function distToDisplay(m, unit) {
    return unit === "mi" ? m / M_PER_MI : m / M_PER_KM;
  }
  function distToM(v, unit) {
    return unit === "mi" ? v * M_PER_MI : v * M_PER_KM;
  }
  function roundTo2(v) {
    return Math.round(v * 100) / 100;
  }
  function fmt(v) {
    return roundTo2(v).toString();
  }
  function fmtDur(seconds) {
    seconds = Math.max(0, Math.round(seconds));
    return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
  }
  function esc(s) {
    const d = document.createElement("div");
    d.textContent = s;
    return d.innerHTML;
  }

  let backdrop = null;
  let sheet = null;
  let active = null; // the set currently open in the sheet

  function build() {
    backdrop = document.createElement("div");
    backdrop.className = "sheet-backdrop";
    backdrop.hidden = true;
    backdrop.addEventListener("click", close);

    sheet = document.createElement("div");
    sheet.className = "sheet";
    sheet.hidden = true;

    document.body.appendChild(backdrop);
    document.body.appendChild(sheet);
  }

  function close() {
    active = null;
    sheet.hidden = true;
    backdrop.hidden = true;
  }

  function axisLabel(ctx, axis) {
    if (axis === "reps") return "reps";
    if (axis === "duration") return "time";
    if (axis === "weight") return `weight (${weightUnit(ctx)})`;
    return `distance (${distanceUnit(ctx)})`;
  }

  function axisValueText(axis) {
    const p = active.pending;
    if (axis === "reps") return String(p.reps);
    if (axis === "duration") return fmtDur(p.duration);
    if (axis === "weight") return fmt(p.weight);
    return fmt(p.distance);
  }

  // same shape as workout.js's bigValueHtml, minus the unit chip: the display
  // unit isn't toggleable from inside an edit
  function bigValue() {
    const axes = TYPE_AXES[active.ctx.exercise_type];
    const frag = (axis) => {
      if (axis === "reps") return `${active.pending.reps}`;
      if (axis === "duration") return fmtDur(active.pending.duration);
      if (axis === "weight") return `${fmt(active.pending.weight)} ${weightUnit(active.ctx)}`;
      return `${fmt(active.pending.distance)} ${distanceUnit(active.ctx)}`;
    };
    let out = "";
    axes.forEach((axis, i) => {
      out += i === 0
        ? frag(axis)
        : (axis === "reps" ? " × " : ' <span class="big-sep">·</span> ') + frag(axis);
    });
    return out;
  }

  function applyStep(kind) {
    const [axis, dir] = kind.split("-");
    const up = dir === "up";
    const p = active.pending;
    if (axis === "weight") {
      const step = STEP[weightUnit(active.ctx)];
      p.weight = Math.max(0, roundTo2(p.weight + (up ? step : -step)));
    } else if (axis === "reps") {
      p.reps = up ? p.reps + 1 : Math.max(1, p.reps - 1);
    } else if (axis === "duration") {
      p.duration = Math.max(0, p.duration + (up ? DURATION_STEP : -DURATION_STEP));
    } else {
      p.distance = Math.max(0, roundTo2(p.distance + (up ? DIST_STEP : -DIST_STEP)));
    }
    updateValues();
  }

  function updateValues() {
    const big = sheet.querySelector(".big-value");
    if (big) big.innerHTML = bigValue();
    TYPE_AXES[active.ctx.exercise_type].forEach((axis) => {
      const el = sheet.querySelector(`[data-value="${axis}"]`);
      if (el) el.textContent = axisValueText(axis);
    });
  }

  // long-press auto-repeat, matching the live-logging stepper's feel
  function bindStepper(btn) {
    const kind = btn.dataset.step;
    let holdTimeout = null;
    let holdInterval = null;
    const start = (e) => {
      e.preventDefault();
      applyStep(kind);
      holdTimeout = setTimeout(() => {
        holdInterval = setInterval(() => applyStep(kind), 130);
      }, 400);
    };
    const stop = () => {
      clearTimeout(holdTimeout);
      clearInterval(holdInterval);
    };
    btn.addEventListener("pointerdown", start);
    btn.addEventListener("pointerup", stop);
    btn.addEventListener("pointercancel", stop);
    btn.addEventListener("pointerleave", stop);
    btn.addEventListener("contextmenu", (e) => e.preventDefault());
  }

  function render() {
    const axes = TYPE_AXES[active.ctx.exercise_type];
    sheet.innerHTML = `
      <div class="sheet-handle"></div>
      <div class="section-label">edit ${esc(active.label)}</div>
      <div class="mono muted card-meta">correcting a logged set — it stays in the same slot</div>
      <div class="big-value">${bigValue()}</div>
      <div class="steppers">
        ${axes
          .map(
            (axis) => `<div>
              <div class="stepper">
                <button class="stepper-btn" data-step="${axis}-down" type="button">−</button>
                <span class="stepper-value" data-value="${axis}">${axisValueText(axis)}</span>
                <button class="stepper-btn" data-step="${axis}-up" type="button">+</button>
              </div>
              <div class="stepper-label">${axisLabel(active.ctx, axis)}</div>
            </div>`
          )
          .join("")}
      </div>
      <button class="btn-primary accent-${active.ctx.accent || "indigo"} sheet-finish"
              data-act="save" type="button">SAVE CHANGES</button>
      <button class="btn-quiet mono cancel-link" data-act="cancel" type="button">cancel</button>`;

    sheet.querySelectorAll(".stepper-btn").forEach(bindStepper);
    sheet.querySelector('[data-act="cancel"]').addEventListener("click", close);
    sheet.querySelector('[data-act="save"]').addEventListener("click", save);
  }

  async function save() {
    const btn = sheet.querySelector('[data-act="save"]');
    btn.disabled = true;
    const ctx = active.ctx;
    const axes = TYPE_AXES[ctx.exercise_type];
    const body = { weight_kg: null, reps: null, duration_seconds: null, distance_m: null };
    if (axes.includes("weight")) body.weight_kg = toKg(active.pending.weight, weightUnit(ctx));
    if (axes.includes("reps")) body.reps = active.pending.reps;
    if (axes.includes("duration")) body.duration_seconds = active.pending.duration;
    if (axes.includes("distance")) body.distance_m = distToM(active.pending.distance, distanceUnit(ctx));
    try {
      const res = await fetch(`${ctx.base || ""}/api/set/${active.setId}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) throw new Error("request failed");
      const saved = await res.json();
      const done = active.onSaved;
      close();
      if (done) done(saved);
    } catch (err) {
      btn.disabled = false;
      btn.textContent = "SAVE FAILED — RETRY";
    }
  }

  return {
    // ctx: { base, exercise_type, display_unit, accent } — .btn-primary carries
    // no fill of its own, the accent class is what colours it (defaults to the
    // indigo analysis accent when the caller has no day accent to hand)
    // values: the set's stored canonical metrics (kg / metres / seconds)
    open(ctx, setId, values, label, onSaved) {
      if (!TYPE_AXES[ctx.exercise_type].length) return; // 'none': nothing to edit
      if (!sheet) build();
      const wu = weightUnit(ctx);
      const du = distanceUnit(ctx);
      active = {
        ctx,
        setId,
        label: label || "set",
        onSaved,
        // pre-filled from what's stored, in display units — never from a
        // suggestion, so the sheet opens showing exactly what was logged
        pending: {
          weight: values.weight_kg == null ? 0 : roundTo2(toDisplay(values.weight_kg, wu)),
          reps: values.reps == null ? 1 : values.reps,
          duration: values.duration_seconds == null ? 0 : values.duration_seconds,
          distance: values.distance_m == null ? 0 : roundTo2(distToDisplay(values.distance_m, du)),
        },
      };
      render();
      sheet.hidden = false;
      backdrop.hidden = false;
    },
  };
})();
