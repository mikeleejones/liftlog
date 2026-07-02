"use strict";

const state = JSON.parse(document.getElementById("state").textContent);

const KG_PER_LB = 0.45359237;
const STEP = { kg: 2.5, lbs: 5 };

const view = document.getElementById("exercise-view");
const progressEl = document.getElementById("workout-progress");
const timerBar = document.getElementById("timer-bar");
const timerFill = document.getElementById("timer-fill");
const timerCount = document.getElementById("timer-count");

let currentIndex = firstPendingIndex();
// pending set values, in display units; edited = stepper was touched
let pending = null;
let timer = null;

function firstPendingIndex() {
  const i = state.exercises.findIndex((ex) => ex.sets.length < ex.target_sets);
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
function fmt(value) {
  return (Math.round(value * 100) / 100).toString();
}

function resetPending(ex) {
  pending = {
    weight: roundLoad(toDisplay(ex.suggest_weight_kg, ex.display_unit), ex.display_unit),
    reps: ex.suggest_reps,
    edited: false,
  };
}

function allDone() {
  return state.exercises.every((ex) => ex.sets.length >= ex.target_sets);
}

async function api(path, body) {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error("request failed");
  return res.json();
}

// ---- render ----

function render() {
  const ex = state.exercises[currentIndex];
  if (!pending) resetPending(ex);
  const done = ex.sets.length;
  const exDone = done >= ex.target_sets;

  progressEl.textContent = allDone()
    ? "all exercises done"
    : `exercise ${currentIndex + 1} of ${state.exercises.length}`;

  const ytUrl =
    "https://www.youtube.com/results?search_query=" +
    encodeURIComponent(ex.youtube_query);

  let html = `
    <div class="exercise-panel">
      <div class="exercise-name">${esc(ex.name)}</div>
      <div class="exercise-cue">${esc(ex.cue)}</div>
      <div class="exercise-target">${ex.target_sets} × ${ex.rep_min}–${ex.rep_max}
        · rest ${ex.rest_seconds}s · <a href="${ytUrl}" target="_blank" rel="noopener">demo</a></div>
      <div class="done-sets">
        ${ex.sets
          .map(
            (s) => `<div class="done-set">
              <span>set ${s.set_number}</span>
              <span>${fmt(roundTo2(toDisplay(s.weight_kg, ex.display_unit)))} ${ex.display_unit} × ${s.reps}</span>
              <span class="check">done</span>
            </div>`
          )
          .join("")}
      </div>`;

  if (!exDone) {
    html += `
      <div class="current-set">
        <div class="section-label current-set-label">set ${done + 1} of ${ex.target_sets}</div>
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
          ${pending.edited ? "LOG SET" : "DID AS SUGGESTED"}</button>
      </div>`;
  } else if (allDone()) {
    html += `<button class="btn-primary accent-${state.accent}" id="finish-inline" type="button">FINISH WORKOUT</button>`;
  } else {
    html += `<div class="mono muted" style="margin-top:12px">exercise done</div>`;
  }
  html += `</div>`;
  view.innerHTML = html;

  if (!exDone) {
    document.getElementById("log-btn").addEventListener("click", logSet);
    document.getElementById("unit-chip").addEventListener("click", toggleUnit);
    view.querySelectorAll(".stepper-btn").forEach(bindStepper);
  }
  const finishInline = document.getElementById("finish-inline");
  if (finishInline) finishInline.addEventListener("click", finishWorkout);
  renderJumpList();
}

function roundTo2(v) {
  return Math.round(v * 100) / 100;
}

function esc(s) {
  const div = document.createElement("div");
  div.textContent = s;
  return div.innerHTML;
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
  const w = document.getElementById("weight-value");
  const r = document.getElementById("reps-value");
  if (w) w.textContent = fmt(pending.weight);
  if (r) r.textContent = String(pending.reps);
  const big = view.querySelector(".big-value");
  const ex = state.exercises[currentIndex];
  if (big)
    big.innerHTML = `${fmt(pending.weight)}
      <button class="unit-chip" id="unit-chip" type="button">${ex.display_unit}</button>
      × ${pending.reps}`;
  const chip = document.getElementById("unit-chip");
  if (chip) chip.addEventListener("click", toggleUnit);
  const logBtn = document.getElementById("log-btn");
  if (logBtn) logBtn.textContent = pending.edited ? "LOG SET" : "DID AS SUGGESTED";
}

// ---- actions ----

async function logSet() {
  const ex = state.exercises[currentIndex];
  const setNumber = ex.sets.length + 1;
  const weightKg = toKg(pending.weight, ex.display_unit);
  const wasSuggested = pending.edited ? 0 : 1;
  const btn = document.getElementById("log-btn");
  btn.disabled = true;
  try {
    await api(`/api/workout/${state.workout_id}/set`, {
      exercise_id: ex.exercise_id,
      set_number: setNumber,
      weight_kg: weightKg,
      reps: pending.reps,
      was_suggested: wasSuggested,
    });
  } catch (err) {
    btn.disabled = false;
    btn.textContent = "retry — not saved";
    return;
  }
  ex.sets.push({ set_number: setNumber, weight_kg: weightKg, reps: pending.reps });
  // carry what was actually done as the suggestion for the next set
  ex.suggest_weight_kg = weightKg;
  ex.suggest_reps = pending.reps;
  pending = null;
  startTimer(ex.rest_seconds);
  if (ex.sets.length >= ex.target_sets) advance();
  render();
}

function advance() {
  const n = state.exercises.length;
  for (let offset = 1; offset <= n; offset++) {
    const i = (currentIndex + offset) % n;
    if (state.exercises[i].sets.length < state.exercises[i].target_sets) {
      currentIndex = i;
      pending = null;
      return;
    }
  }
}

async function toggleUnit() {
  const ex = state.exercises[currentIndex];
  const next = ex.display_unit === "kg" ? "lbs" : "kg";
  ex.display_unit = next;
  pending.weight = roundLoad(toDisplay(toKg(pending.weight, next === "kg" ? "lbs" : "kg"), next), next);
  render();
  try {
    await api(`/api/exercise/${ex.exercise_id}/unit`, { unit: next });
  } catch (err) {
    /* persisted next time; display already flipped */
  }
}

async function finishWorkout() {
  const res = await fetch(`/workout/${state.workout_id}/finish`, { method: "POST" });
  if (res.ok) window.location.href = `/workout/${state.workout_id}/summary`;
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

// ---- jump sheet ----

const sheet = document.getElementById("jump-sheet");
const backdrop = document.getElementById("sheet-backdrop");

function renderJumpList() {
  const list = document.getElementById("jump-list");
  list.innerHTML = state.exercises
    .map((ex, i) => {
      const done = ex.sets.length >= ex.target_sets;
      const status = done
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
      closeSheet();
      render();
    })
  );
}

function openSheet() {
  sheet.hidden = false;
  backdrop.hidden = false;
  renderJumpList();
}
function closeSheet() {
  sheet.hidden = true;
  backdrop.hidden = true;
}

document.getElementById("jump-btn").addEventListener("click", openSheet);
backdrop.addEventListener("click", closeSheet);
document.getElementById("finish-btn").addEventListener("click", finishWorkout);

render();
