"""Derived-value rules per docs/schema.md: progression suggestion, stall
detection, warmup ramp, deload pre-fill. Computed, never stored."""

KG_PER_LB = 0.45359237
BAR_KG = 20.0


def round_loadable(kg, unit):
    """Nearest loadable increment in the display unit, returned in kg."""
    if unit == "lbs":
        lbs = kg / KG_PER_LB
        return round(lbs / 5.0) * 5.0 * KG_PER_LB
    return round(kg / 2.5) * 2.5


def recent_sessions(db, exercise_id, exclude_workout_id=None, limit=3):
    """Working sets of the most recent non-deload workouts containing the
    exercise, newest first: [{'wid', 'sets': [(weight_kg, reps), ...]}, ...].
    Substituted/skipped sessions have no sets for the exercise, so they
    naturally don't appear (and don't advance the stall counter)."""
    rows = db.execute(
        "SELECT w.id AS wid, s.weight_kg, s.reps "
        "FROM set_log s JOIN workout w ON w.id = s.workout_id "
        "WHERE s.exercise_id = ? AND s.set_type = 'normal' AND w.is_deload = 0 "
        "AND w.id != ? "
        "ORDER BY w.started_at DESC, w.id DESC, s.set_number",
        (exercise_id, exclude_workout_id or 0),
    ).fetchall()
    sessions = []
    for r in rows:
        if not sessions or sessions[-1]["wid"] != r["wid"]:
            if len(sessions) == limit:
                break
            sessions.append({"wid": r["wid"], "sets": []})
        sessions[-1]["sets"].append((r["weight_kg"], r["reps"]))
    return sessions


def suggest(db, exercise, target_sets, rep_min, rep_max, exclude_workout_id=None):
    """Double progression: all working sets of the last non-deload session at
    rep_max and one weight -> +increment. Stall: 3 consecutive sessions at the
    same weight with no total-rep improvement -> 10% reset. Else same weight,
    nudging reps toward rep_max."""
    unit = exercise["display_unit"]
    sessions = recent_sessions(db, exercise["id"], exclude_workout_id)
    if not sessions:
        return {"weight_kg": BAR_KG, "reps": rep_min, "kind": "first"}
    last_sets = sessions[0]["sets"]
    weights = {w for w, _ in last_sets}
    if len(weights) == 1:
        w = last_sets[0][0]
        if len(last_sets) >= target_sets and all(r >= rep_max for _, r in last_sets):
            return {
                "weight_kg": round_loadable(w + exercise["increment_kg"], unit),
                "reps": rep_min,
                "kind": "progress",
            }
        if len(sessions) == 3:
            uniform = all(
                len({x for x, _ in s["sets"]}) == 1 and s["sets"][0][0] == w
                for s in sessions
            )
            totals = [sum(r for _, r in s["sets"]) for s in sessions]  # newest first
            if uniform and totals[0] <= totals[1] <= totals[2]:
                return {
                    "weight_kg": round_loadable(w * 0.9, unit),
                    "reps": rep_min,
                    "kind": "stall",
                }
        lowest = min(r for _, r in last_sets)
        return {
            "weight_kg": w,
            "reps": max(rep_min, min(rep_max, lowest + 1)),
            "kind": "same",
        }
    # mixed weights last time: repeat the final working set
    w, r = last_sets[-1]
    return {"weight_kg": w, "reps": max(rep_min, min(rep_max, r)), "kind": "same"}


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
    """60% of the last working weight, 2 x 10."""
    sessions = recent_sessions(db, exercise["id"], exclude_workout_id, limit=1)
    base = sessions[0]["sets"][-1][0] if sessions else BAR_KG
    weight = max(round_loadable(base * 0.6, exercise["display_unit"]), 2.5)
    return {"weight_kg": weight, "reps": 10, "kind": "deload"}


def deload_active(db, now_iso):
    """The 4th week (weeks_since_deload >= 3) is a deload week unless deferred."""
    state = db.execute("SELECT * FROM program_state WHERE id = 1").fetchone()
    if state["weeks_since_deload"] < 3:
        return False
    deferred = state["deload_deferred_until"]
    return not (deferred and deferred > now_iso)


def substitution_candidates(db, planned_exercise_id, routine_id, exclude_ids=(), limit=3):
    """The 3 best alternatives: same movement_pattern first, then same
    muscle_group, tie-broken by prior history then recency. Excluded:
    exercises in the routine and any explicitly excluded ids (the current
    exercise, earlier swap targets, anything already trained this workout)."""
    planned = db.execute(
        "SELECT * FROM exercise WHERE id = ?", (planned_exercise_id,)
    ).fetchone()
    excluded = {planned_exercise_id, *exclude_ids}
    placeholders = ",".join("?" * len(excluded))
    return db.execute(
        f"SELECT e.*, "
        f"(SELECT MAX(logged_at) FROM set_log WHERE exercise_id = e.id) AS last_used "
        f"FROM exercise e "
        f"WHERE e.id NOT IN ({placeholders}) AND e.is_archived = 0 "
        f"AND e.id NOT IN (SELECT exercise_id FROM routine_exercise WHERE routine_id = ?) "
        f"ORDER BY (e.movement_pattern = ?) DESC, (e.muscle_group = ?) DESC, "
        f"(last_used IS NOT NULL) DESC, last_used DESC, e.name "
        f"LIMIT ?",
        (*excluded, routine_id or 0, planned["movement_pattern"],
         planned["muscle_group"], limit),
    ).fetchall()
