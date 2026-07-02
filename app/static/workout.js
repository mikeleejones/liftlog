"use strict";

const state = JSON.parse(document.getElementById("state").textContent);

// proxy prefix this app is mounted under (e.g. "/liftlog"), "" at domain root.
// every fetch and navigation must go through it or nginx won't route it.
const BASE = state.base || "";

const KG_PER_LB = 0.45359237;
const STEP = { kg: 2.5, lbs: 5 };
const WARMUP_REST_SECONDS = 60;

const view = document.getElementById("exercise-view");
const progressEl = document.getElementById("workout-progress");
const timerBar = document.getElementById("timer-bar");
const timerFill = document.getElementById("timer-fill");
const timerCount = document.getElementById("timer-count");

let currentIndex = firstPendingIndex();
// pending set values, in display units; edited = stepper was touched
let pending = null;
let timer = null;

function exerciseDone(ex) {
  return ex.skipped || ex.sets.length >= ex.target_sets;
}

function inWarmup(ex) {
  return (
    !ex.skipped &&
    !ex.warmupsSkipped &&
    ex.warmups.length > 0 &&
    ex.warmups_logged < ex.warmups.length &&
    ex.sets.length === 0
  );
}

function firstPendingIndex() {
  const i = state.exercises.findIndex((ex) => !exerciseDone(ex));
  return i === -1 ? 0 : i;
}

function toDisplay(kg, unit) {
  return unit === "kg" ? kg : kg / KG_PER_LB;
}
function toKg(value, unit) {
  return unit === "kg" ? value : value * KG_PER_LB;
}
function roundLoad(value, unit) {
  return Math.round(value / STEP[unit]) * STEP[unit];
}
function roundTo2(v) {
  return Math.round(v * 100) / 100;
}
function fmt(value) {
  return roundTo2(value).toString();
}

function resetPending(ex) {
  const source = inWarmup(ex) ? ex.warmups[ex.warmups_logged] : {
    weight_kg: ex.suggest_weight_kg,
    reps: ex.suggest_reps,
  };
  pending = {
    weight: roundLoad(toDisplay(source.weight_kg, ex.display_unit), ex.display_unit),
    reps: source.reps,
    edited: false,
  };
}

function allDone() {
  return state.exercises.every(exerciseDone);
}

async function api(path, body) {
  const res = await fetch(BASE + path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error("request failed");
  return res.json();
}

function esc(s) {
  const div = document.createElement("div");
  div.textContent = s;
  return div.innerHTML;
}

// ---- render ----

function suggestChip(ex) {
  const w = fmt(roundLoad(toDisplay(ex.suggest_weight_kg, ex.display_unit), ex.display_unit));
  if (ex.suggest_kind === "progress")
    return `<span class="chip chip-progress mono">↑ ${w}</span>`;
  if (ex.suggest_kind === "stall")
    return `<span class="chip chip-stall mono">stalled: try ${w} ${ex.display_unit}</span>`;
  if (ex.suggest_kind === "deload")
    return `<span class="chip chip-stall mono">deload — 60%</span>`;
  return "";
}

function render() {
  const ex = state.exercises[currentIndex];
  if (!pending) resetPending(ex);
  const warmup = inWarmup(ex);
  const done = exerciseDone(ex);

  progressEl.textContent = allDone()
    ? "all exercises done"
    : state.is_deload
      ? `deload — exercise ${currentIndex + 1} of ${state.exercises.length}`
      : `exercise ${currentIndex + 1} of ${state.exercises.length}`;

  const ytUrl =
    "https://www.youtube.com/results?search_query=" +
    encodeURIComponent(ex.youtube_query);

  let html = `
    <div class="exercise-panel">
      <div class="header-row">
        <div class="exercise-name">${esc(ex.name)}</div>
        ${suggestChip(ex)}
      </div>
      <div class="exercise-cue">${esc(ex.cue)}</div>
      <div class="exercise-target">${ex.target_sets} × ${ex.rep_min}${ex.rep_min === ex.rep_max ? "" : "–" + ex.rep_max}
        · rest ${ex.rest_seconds}s</div>
      <div class="exercise-actions">
        <a class="link-chip mono" href="${ytUrl}" target="_blank" rel="noopener">demo</a>
        ${done ? "" : `<button class="link-chip mono" id="swap-btn" type="button">swap</button>`}
      </div>
      <div class="done-sets">
        ${ex.sets
          .map(
            (s) => `<div class="done-set">
              <span>set ${s.set_number}</span>
              <span>${fmt(toDisplay(s.weight_kg, ex.display_unit))} ${ex.display_unit} × ${s.reps}</span>
              <span class="check">done</span>
            </div>`
          )
          .join("")}
      </div>`;

  if (ex.skipped) {
    html += `<div class="mono muted skipped-note">skipped</div>`;
  } else if (!done) {
    const label = warmup
      ? `warmup ${ex.warmups_logged + 1} of ${ex.warmups.length}`
      : `set ${ex.sets.length + 1} of ${ex.target_sets}`;
    html += `
      <div class="current-set">
        <div class="header-row">
          <div class="section-label current-set-label">${label}</div>
          ${warmup ? `<button class="link-chip mono" id="skip-warmups-btn" type="button">skip warmups</button>` : ""}
        </div>
        <div class="big-value">${fmt(pending.weight)}
          <button class="unit-chip" id="unit-chip" type="button">${ex.display_unit}</button>
          × ${pending.reps}</div>
        <div class="steppers">
          <div>
            <div class="stepper">
              <button class="stepper-btn" data-step="weight-down" type="button">−</button>
              <span class="stepper-value" id="weight-value">${fmt(pending.weight)}</span>
              <button class="stepper-btn" data-step="weight-up" type="button">+</button>
            </div>
            <div class="stepper-label">weight (${ex.display_unit})</div>
          </div>
          <div>
            <div class="stepper">
              <button class="stepper-btn" data-step="reps-down" type="button">−</button>
              <span class="stepper-value" id="reps-value">${pending.reps}</span>
              <button class="stepper-btn" data-step="reps-up" type="button">+</button>
            </div>
            <div class="stepper-label">reps</div>
          </div>
        </div>
        <button class="btn-primary accent-${state.accent}" id="log-btn" type="button">
          ${warmup ? "LOG WARMUP" : pending.edited ? "LOG SET" : "DID AS SUGGESTED"}</button>
      </div>`;
  } else if (allDone()) {
    html += `<button class="btn-primary accent-${state.accent}" id="finish-inline" type="button">FINISH WORKOUT</button>`;
  } else {
    html += `<div class="mono muted skipped-note">exercise done</div>`;
  }
  html += `</div>`;
  view.innerHTML = html;

  if (!done && !ex.skipped) {
    document.getElementById("log-btn").addEventListener("click", logSet);
    document.getElementById("unit-chip").addEventListener("click", toggleUnit);
    view.querySelectorAll(".stepper-btn").forEach(bindStepper);
    const skipWarmups = document.getElementById("skip-warmups-btn");
    if (skipWarmups)
      skipWarmups.addEventListener("click", () => {
        ex.warmupsSkipped = true;
        pending = null;
        render();
      });
  }
  const swapBtn = document.getElementById("swap-btn");
  if (swapBtn) swapBtn.addEventListener("click", openSubSheet);
  const finishInline = document.getElementById("finish-inline");
  if (finishInline) finishInline.addEventListener("click", finishWorkout);
  renderJumpList();
}

// ---- steppers with long-press auto-repeat ----

function applyStep(kind) {
  const ex = state.exercises[currentIndex];
  const step = STEP[ex.display_unit];
  if (kind === "weight-up") pending.weight = roundTo2(pending.weight + step);
  if (kind === "weight-down") pending.weight = Math.max(0, roundTo2(pending.weight - step));
  if (kind === "reps-up") pending.reps += 1;
  if (kind === "reps-down") pending.reps = Math.max(1, pending.reps - 1);
  pending.edited = true;
  updateValues();
}

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

// steppers must not trigger a full re-render mid-hold (it would replace the
// button under the pointer and kill auto-repeat), so update values in place
function updateValues() {
  const ex = state.exercises[currentIndex];
  const w = document.getElementById("weight-value");
  const r = document.getElementById("reps-value");
  if (w) w.textContent = fmt(pending.weight);
  if (r) r.textContent = String(pending.reps);
  const big = view.querySelector(".big-value");
  if (big)
    big.innerHTML = `${fmt(pending.weight)}
      <button class="unit-chip" id="unit-chip" type="button">${ex.display_unit}</button>
      × ${pending.reps}`;
  const chip = document.getElementById("unit-chip");
  if (chip) chip.addEventListener("click", toggleUnit);
  const logBtn = document.getElementById("log-btn");
  if (logBtn && !inWarmup(ex))
    logBtn.textContent = pending.edited ? "LOG SET" : "DID AS SUGGESTED";
}

// ---- actions ----

async function logSet() {
  const ex = state.exercises[currentIndex];
  const warmup = inWarmup(ex);
  const setNumber = warmup ? ex.warmups_logged + 1 : ex.sets.length + 1;
  const weightKg = toKg(pending.weight, ex.display_unit);
  const wasSuggested = pending.edited ? 0 : 1;
  const btn = document.getElementById("log-btn");
  btn.disabled = true;
  try {
    await api(`/api/workout/${state.workout_id}/set`, {
      exercise_id: ex.exercise_id,
      set_number: setNumber,
      set_type: warmup ? "warmup" : "normal",
      weight_kg: weightKg,
      reps: pending.reps,
      was_suggested: wasSuggested,
    });
  } catch (err) {
    btn.disabled = false;
    btn.textContent = "retry — not saved";
    return;
  }
  if (warmup) {
    ex.warmups_logged += 1;
    startTimer(WARMUP_REST_SECONDS);
  } else {
    ex.sets.push({ set_number: setNumber, weight_kg: weightKg, reps: pending.reps });
    // carry what was actually done as the suggestion for the next set
    ex.suggest_weight_kg = weightKg;
    ex.suggest_reps = pending.reps;
    startTimer(ex.rest_seconds);
    if (ex.sets.length >= ex.target_sets) advance();
  }
  pending = null;
  render();
}

function advance() {
  const n = state.exercises.length;
  for (let offset = 1; offset <= n; offset++) {
    const i = (currentIndex + offset) % n;
    if (!exerciseDone(state.exercises[i])) {
      currentIndex = i;
      pending = null;
      return;
    }
  }
}

async function toggleUnit() {
  const ex = state.exercises[currentIndex];
  const next = ex.display_unit === "kg" ? "lbs" : "kg";
  const prev = ex.display_unit;
  ex.display_unit = next;
  pending.weight = roundLoad(toDisplay(toKg(pending.weight, prev), next), next);
  render();
  try {
    await api(`/api/exercise/${ex.exercise_id}/unit`, { unit: next });
  } catch (err) {
    /* persisted next time; display already flipped */
  }
}

async function finishWorkout() {
  const res = await fetch(`${BASE}/workout/${state.workout_id}/finish`, { method: "POST" });
  if (res.ok) window.location.href = `${BASE}/workout/${state.workout_id}/summary`;
}

// ---- rest timer ----

function startTimer(seconds) {
  stopTimer();
  timerBar.hidden = false;
  timerBar.classList.remove("done");
  const startedAt = Date.now();
  const tick = () => {
    const elapsed = (Date.now() - startedAt) / 1000;
    const remaining = Math.max(0, seconds - elapsed);
    const m = Math.floor(remaining / 60);
    const s = Math.floor(remaining % 60);
    timerCount.textContent = `${m}:${String(s).padStart(2, "0")}`;
    timerFill.style.width = `${(remaining / seconds) * 100}%`;
    if (remaining <= 0) {
      timerBar.classList.add("done");
      timerCount.textContent = "rest done";
      if (navigator.vibrate) navigator.vibrate([120, 60, 120]);
      clearInterval(timer.interval);
      timer.endTimeout = setTimeout(hideTimer, 4000);
    }
  };
  timer = { interval: setInterval(tick, 250), endTimeout: null };
  tick();
}

function stopTimer() {
  if (!timer) return;
  clearInterval(timer.interval);
  clearTimeout(timer.endTimeout);
  timer = null;
}

function hideTimer() {
  stopTimer();
  timerBar.hidden = true;
}

document.getElementById("timer-skip").addEventListener("click", hideTimer);

// ---- sheets ----

const sheet = document.getElementById("jump-sheet");
const backdrop = document.getElementById("sheet-backdrop");
const finishSheet = document.getElementById("finish-sheet");
const subSheet = document.getElementById("sub-sheet");

function closeAllSheets() {
  sheet.hidden = true;
  finishSheet.hidden = true;
  subSheet.hidden = true;
  backdrop.hidden = true;
}

// ---- jump sheet ----

function renderJumpList() {
  const list = document.getElementById("jump-list");
  list.innerHTML = state.exercises
    .map((ex, i) => {
      const status = ex.skipped
        ? `<span class="mono muted">skipped</span>`
        : exerciseDone(ex)
          ? `<span class="mono done">done</span>`
          : `<span class="mono muted">${ex.sets.length}/${ex.target_sets}</span>`;
      return `<button class="jump-row ${i === currentIndex ? "current" : ""}" data-jump="${i}" type="button">
        <span>${esc(ex.name)}</span>${status}</button>`;
    })
    .join("");
  list.querySelectorAll("[data-jump]").forEach((btn) =>
    btn.addEventListener("click", () => {
      currentIndex = Number(btn.dataset.jump);
      pending = null;
      closeAllSheets();
      render();
    })
  );
}

function openSheet() {
  closeAllSheets();
  sheet.hidden = false;
  backdrop.hidden = false;
  renderJumpList();
}

document.getElementById("jump-btn").addEventListener("click", openSheet);

// ---- substitution sheet ----

async function openSubSheet() {
  const ex = state.exercises[currentIndex];
  closeAllSheets();
  document.getElementById("sub-title").textContent = `swap ${ex.name.toLowerCase()}`;
  document.getElementById("sub-new-name").value = "";
  const list = document.getElementById("sub-list");
  list.innerHTML = `<div class="mono muted card-meta">finding alternatives…</div>`;
  subSheet.hidden = false;
  backdrop.hidden = false;
  const res = await fetch(
    `${BASE}/api/workout/${state.workout_id}/substitutes/${ex.planned_exercise_id}?current=${ex.exercise_id}`
  );
  if (!res.ok) {
    list.innerHTML = `<div class="mono muted card-meta">could not load alternatives</div>`;
    return;
  }
  const data = await res.json();
  list.innerHTML = data.candidates
    .map((c, i) => {
      const meta = c.from_catalog
        ? `${c.movement_pattern} · ${c.muscle_group} · not in library yet`
        : `${c.movement_pattern} · ${c.muscle_group} · ${c.last_used ? "used " + c.last_used.slice(0, 10) : "never used"}`;
      const attr = c.from_catalog ? `data-sub-new="${esc(c.name)}"` : `data-sub="${c.id}"`;
      return `<button class="jump-row" ${attr} type="button">
        <span>${esc(c.name)}<br>
          <span class="mono muted sub-meta">${meta}</span></span>
        ${c.from_catalog ? `<span class="mono muted sub-meta">new</span>` : ""}
      </button>`;
    })
    .join("") || `<div class="mono muted card-meta">no alternatives available</div>`;
  list.querySelectorAll("[data-sub]").forEach((btn) =>
    btn.addEventListener("click", () => applySubstitute({ actual_exercise_id: Number(btn.dataset.sub) }))
  );
  list.querySelectorAll("[data-sub-new]").forEach((btn) =>
    btn.addEventListener("click", () => applySubstitute({ new_name: btn.dataset.subNew }))
  );
}

async function applySubstitute(choice) {
  const ex = state.exercises[currentIndex];
  const body = { planned_exercise_id: ex.planned_exercise_id, ...choice };
  let data;
  try {
    data = await api(`/api/workout/${state.workout_id}/substitute`, body);
  } catch (err) {
    return;
  }
  if (data.skipped) {
    ex.skipped = true;
    if (!allDone()) advance();
  } else {
    data.exercise.warmupsSkipped = false;
    state.exercises[currentIndex] = data.exercise;
  }
  pending = null;
  closeAllSheets();
  render();
}

document.getElementById("sub-skip-btn").addEventListener("click", () => applySubstitute({ skip: true }));
document.getElementById("sub-new-btn").addEventListener("click", () => {
  const name = document.getElementById("sub-new-name").value.trim();
  if (name) applySubstitute({ new_name: name });
});
document.getElementById("sub-cancel-btn").addEventListener("click", closeAllSheets);

// ---- finish confirmation (only when the workout is incomplete) ----

function confirmFinish() {
  if (allDone()) {
    finishWorkout();
    return;
  }
  closeAllSheets();
  const done = state.exercises.filter(exerciseDone).length;
  const logged = state.exercises.reduce((n, ex) => n + ex.sets.length, 0);
  document.getElementById("finish-summary").textContent =
    `${done} of ${state.exercises.length} exercises done — ` +
    (logged === 0
      ? "no sets logged"
      : logged === 1
        ? "finish keeps the 1 logged set, discard deletes it"
        : `finish keeps the ${logged} logged sets, discard deletes them`);
  finishSheet.hidden = false;
  backdrop.hidden = false;
}

async function discardWorkout() {
  const res = await fetch(`${BASE}/workout/${state.workout_id}/discard`, { method: "POST" });
  if (res.ok) window.location.href = BASE + "/";
}

document.getElementById("finish-btn").addEventListener("click", confirmFinish);
document.getElementById("finish-anyway-btn").addEventListener("click", finishWorkout);
document.getElementById("finish-discard-btn").addEventListener("click", discardWorkout);
document.getElementById("finish-cancel-btn").addEventListener("click", closeAllSheets);
backdrop.addEventListener("click", closeAllSheets);

render();
