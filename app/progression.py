"""Derived-value rules per docs/schema.md: progression suggestion, stall
detection, warmup ramp, deload pre-fill. Computed, never stored."""

KG_PER_LB = 0.45359237
BAR_KG = 20.0

# progression steps for the single-axis, no-weight types (see suggest())
DURATION_STEP_S = 5.0     # +5 s when a duration hold is cleared cleanly
DISTANCE_STEP_M = 100.0   # +100 m (≈0.1 km) small distance bump

# (set_log column, progression step) for the three single-axis progressed types
_SINGLE_AXIS = {
    "reps_only": ("reps", 1),
    "duration": ("duration_seconds", DURATION_STEP_S),
    "distance": ("distance_m", DISTANCE_STEP_M),
}

_METRIC_KEYS = ("weight_kg", "reps", "duration_seconds", "distance_m")


def round_loadable(kg, unit):
    """Nearest loadable increment in the display unit, returned in kg. Used for
    the weight axis only; unit is 'kg' or 'lbs' (distance's km/mi never reach
    this — distance rounds to whole metres instead)."""
    if unit == "lbs":
        lbs = kg / KG_PER_LB
        return round(lbs / 5.0) * 5.0 * KG_PER_LB
    return round(kg / 2.5) * 2.5


def _blank(kind="same"):
    """A suggestion with every metric empty; callers fill the axes their type
    uses. Keeps the returned shape uniform across all exercise types."""
    return {"kind": kind, "weight_kg": None, "reps": None,
            "duration_seconds": None, "distance_m": None}


def _as_metric(key, value):
    return int(round(value)) if key == "reps" else float(value)


def recent_sessions(db, exercise_id, exclude_workout_id=None, limit=3, reset_at=None):
    """Working sets of the most recent non-deload workouts containing the
    exercise, newest first: [{'wid', 'sets': [{weight_kg, reps,
    duration_seconds, distance_m}, ...]}, ...]. Substituted/skipped sessions
    have no sets for the exercise, so they naturally don't appear (and don't
    advance the stall counter).

    reset_at (exercise.progress_reset_at) implements the soft progress reset:
    when set, only sets logged strictly after it are considered, so suggestions
    and stall detection start fresh. NULL scans all history unchanged. This does
    not affect charts/history, which query set_log directly and ignore it."""
    rows = db.execute(
        "SELECT w.id AS wid, s.weight_kg, s.reps, s.duration_seconds, s.distance_m "
        "FROM set_log s JOIN workout w ON w.id = s.workout_id "
        "WHERE s.exercise_id = ? AND s.set_type = 'normal' AND w.is_deload = 0 "
        "AND w.id != ? AND (? IS NULL OR s.logged_at > ?) "
        "ORDER BY w.started_at DESC, w.id DESC, s.set_number",
        (exercise_id, exclude_workout_id or 0, reset_at, reset_at),
    ).fetchall()
    sessions = []
    for r in rows:
        if not sessions or sessions[-1]["wid"] != r["wid"]:
            if len(sessions) == limit:
                break
            sessions.append({"wid": r["wid"], "sets": []})
        sessions[-1]["sets"].append({k: r[k] for k in _METRIC_KEYS})
    return sessions


def suggest(db, exercise, target_sets, rep_min, rep_max, exclude_workout_id=None):
    """Per-type suggestion/pre-fill. Always returns the uniform _blank() shape
    with the axes for this exercise_type filled and a `kind` of first / same /
    progress / stall / none.

    - weight_reps: unchanged double progression (all sets at rep_max, one weight
      -> +increment; 3 flat sessions -> 10% reset).
    - reps_only / duration / distance: single-axis version — clear the top of the
      range cleanly -> +1 rep / +5 s / +100 m; 3 flat sessions -> stall flag
      (no weight axis to reset, so the value is just repeated).
    - duration_weight / distance_weight: pre-fill from last session only, NO
      auto-progression this pass (no exercises of these types exist to tune
      against; see TODO in _suggest_passthrough).
    - none: pure completion record, never progressed."""
    etype = exercise["exercise_type"]
    if etype == "weight_reps":
        return _suggest_weight_reps(db, exercise, target_sets, rep_min, rep_max,
                                    exclude_workout_id)
    if etype in _SINGLE_AXIS:
        return _suggest_single_axis(db, exercise, etype, target_sets, rep_min,
                                    rep_max, exclude_workout_id)
    if etype in ("duration_weight", "distance_weight"):
        return _suggest_passthrough(db, exercise, etype, rep_min, exclude_workout_id)
    return _blank("none")  # etype == "none"


def _suggest_weight_reps(db, exercise, target_sets, rep_min, rep_max, exclude_workout_id):
    unit = exercise["display_unit"]
    # increment_kg == 0 means a bodyweight / no-load exercise: no weight to add,
    # so load progression and 10% stall resets don't apply — it just tracks reps.
    loaded = exercise["increment_kg"] > 0
    sessions = recent_sessions(
        db, exercise["id"], exclude_workout_id, reset_at=exercise["progress_reset_at"]
    )
    if not sessions:
        s = _blank("first")
        s["weight_kg"], s["reps"] = (BAR_KG if loaded else 0.0), rep_min
        return s
    last_sets = sessions[0]["sets"]
    weights = {x["weight_kg"] for x in last_sets}
    if len(weights) == 1:
        w = last_sets[0]["weight_kg"]
        if loaded:
            if len(last_sets) >= target_sets and all(x["reps"] >= rep_max for x in last_sets):
                s = _blank("progress")
                s["weight_kg"] = round_loadable(w + exercise["increment_kg"], unit)
                s["reps"] = rep_min
                return s
            if len(sessions) == 3:
                uniform = all(
                    len({x["weight_kg"] for x in ss["sets"]}) == 1
                    and ss["sets"][0]["weight_kg"] == w
                    for ss in sessions
                )
                totals = [sum(x["reps"] for x in ss["sets"]) for ss in sessions]  # newest first
                if uniform and totals[0] <= totals[1] <= totals[2]:
                    s = _blank("stall")
                    s["weight_kg"] = round_loadable(w * 0.9, unit)
                    s["reps"] = rep_min
                    return s
        lowest = min(x["reps"] for x in last_sets)
        s = _blank("same")
        s["weight_kg"], s["reps"] = w, max(rep_min, min(rep_max, lowest + 1))
        return s
    # mixed weights last time: repeat the final working set
    s = _blank("same")
    last = last_sets[-1]
    s["weight_kg"] = last["weight_kg"]
    s["reps"] = max(rep_min, min(rep_max, last["reps"]))
    return s


def _suggest_single_axis(db, exercise, etype, target_sets, rep_min, rep_max, exclude_workout_id):
    """reps_only / duration / distance: the routine's rep_min/rep_max are read as
    the target range for the type's own metric (reps, seconds, or metres). Clear
    the top across all sets -> bump by the step; otherwise nudge up toward it."""
    key, inc = _SINGLE_AXIS[etype]
    top, first = float(rep_max), float(rep_min)
    sessions = recent_sessions(
        db, exercise["id"], exclude_workout_id, reset_at=exercise["progress_reset_at"]
    )
    s = _blank()
    if not sessions:
        s["kind"] = "first"
        s[key] = _as_metric(key, first)
        return s
    last = [x[key] for x in sessions[0]["sets"] if x[key] is not None]
    if not last:
        s["kind"] = "same"
        s[key] = _as_metric(key, first)
        return s
    v = last[0]
    if len(set(last)) == 1 and len(sessions[0]["sets"]) >= target_sets and v >= top:
        s["kind"] = "progress"
        s[key] = _as_metric(key, v + inc)
        return s
    if len(sessions) == 3:
        def uniform_at(sess, val):
            vals = {x[key] for x in sess["sets"] if x[key] is not None}
            return len(vals) == 1 and next(iter(vals)) == val
        totals = [sum(x[key] for x in ss["sets"] if x[key] is not None) for ss in sessions]
        if all(uniform_at(ss, v) for ss in sessions) and totals[0] <= totals[1] <= totals[2]:
            s["kind"] = "stall"
            s[key] = _as_metric(key, v)
            return s
    nudged = max(first, min(top, min(last) + inc))
    s["kind"] = "same"
    s[key] = _as_metric(key, nudged)
    return s


def _suggest_passthrough(db, exercise, etype, rep_min, exclude_workout_id):
    """duration_weight / distance_weight: repeat last session's effort as a
    pre-fill, no progression or stall. TODO(hyrox): implement real double
    progression on the loaded axis once loaded-carry exercises exist to test it."""
    loaded = exercise["increment_kg"] > 0
    other = "duration_seconds" if etype == "duration_weight" else "distance_m"
    sessions = recent_sessions(
        db, exercise["id"], exclude_workout_id, limit=1, reset_at=exercise["progress_reset_at"]
    )
    if sessions:
        last = sessions[0]["sets"][-1]
        s = _blank("same")
        s["weight_kg"] = last["weight_kg"]
        s[other] = last[other]
        return s
    s = _blank("first")
    s["weight_kg"] = BAR_KG if loaded else 0.0
    s[other] = float(rep_min)
    return s


def warmup_ramp(weight_kg, unit):
    """bar x10, 50% x6, 75% x3 — steps only included when they land above the
    bar and below the working weight. No ramp at all when the working weight
    doesn't exceed the bar."""
    if weight_kg <= BAR_KG:
        return []
    ramp = [{"weight_kg": BAR_KG, "reps": 10}]
    for fraction, reps in ((0.5, 6), (0.75, 3)):
        w = round_loadable(weight_kg * fraction, unit)
        if w > ramp[-1]["weight_kg"] and w < weight_kg:
            ramp.append({"weight_kg": w, "reps": reps})
    return ramp


def deload_prefill(db, exercise, exclude_workout_id=None):
    """Deload pre-fill: ~60% of the last working effort. weight_reps keeps the
    classic 60% x 2x10; single-axis types drop their metric to ~60%; the loaded
    two-axis types drop the weight to 60% and keep the other axis; none is a
    plain completion record. Bodyweight/no-load (increment_kg == 0) weights stay
    at 0 rather than floating up to the 2.5 kg floor."""
    etype = exercise["exercise_type"]
    s = _blank("deload")
    if etype == "none":
        return s
    loaded = exercise["increment_kg"] > 0
    sessions = recent_sessions(
        db, exercise["id"], exclude_workout_id, limit=1,
        reset_at=exercise["progress_reset_at"],
    )
    last = sessions[0]["sets"][-1] if sessions else None

    if etype in ("weight_reps", "duration_weight", "distance_weight"):
        # distance_weight has no weight unit field (display_unit is km/mi), so its
        # weight axis rounds in kg; the others use their kg/lbs display_unit.
        weight_unit = "kg" if etype == "distance_weight" else exercise["display_unit"]
        base = last["weight_kg"] if last and last["weight_kg"] is not None else (BAR_KG if loaded else 0.0)
        floor = 2.5 if loaded else 0.0
        s["weight_kg"] = max(round_loadable(base * 0.6, weight_unit), floor)

    if etype == "weight_reps":
        s["reps"] = 10
    elif etype == "reps_only":
        base = last["reps"] if last and last["reps"] is not None else 10
        s["reps"] = max(1, int(round(base * 0.6)))
    elif etype in ("duration", "duration_weight"):
        base = last["duration_seconds"] if last and last["duration_seconds"] is not None else 30.0
        s["duration_seconds"] = float(max(5, round(base * 0.6 / 5.0) * 5))  # nearest 5 s
    elif etype in ("distance", "distance_weight"):
        base = last["distance_m"] if last and last["distance_m"] is not None else 100.0
        s["distance_m"] = float(max(0.0, round(base * 0.6)))
    return s


def deload_active(db, now_iso):
    """The 4th week (weeks_since_deload >= 3) is a deload week unless deferred."""
    state = db.execute("SELECT * FROM program_state WHERE id = 1").fetchone()
    if state["weeks_since_deload"] < 3:
        return False
    deferred = state["deload_deferred_until"]
    return not (deferred and deferred > now_iso)
