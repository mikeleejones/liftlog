"""Claude JSON import (v1 bare routines, v2 program envelope) — validation,
preview plan, and apply.

Semantics per docs/schema.md: v2 program matched by name -> replace (routines
matched by name within the program get their prescription replaced; routines
absent from the import are archived) and the program becomes active. v1
routines are upserted into the active program at week 1, nothing archived.
Exercises always: match by name case-insensitively -> update cue/query/tags,
never touch history; unknown -> create.
"""

MOVEMENT_PATTERNS = {
    "horizontal_pull", "vertical_pull", "hinge", "squat",
    "horizontal_push", "vertical_push", "isolation", "core",
}
MUSCLE_GROUPS = {"back", "chest", "shoulders", "legs", "glutes", "arms", "core"}
EXERCISE_TYPES = {
    "weight_reps", "reps_only", "duration", "duration_weight",
    "distance", "distance_weight", "none",
}
DISPLAY_UNITS = {"kg", "lbs", "km", "mi"}
DISTANCE_TYPES = {"distance", "distance_weight"}

EXERCISE_DEFAULTS = {
    "cue": "",
    "youtube_query": "",
    "rest_seconds": 90,
    "increment_kg": 2.5,
    "is_primary": False,
    "exercise_type": "weight_reps",
    "equipment": None,
}

FALLBACK_PROGRAM_NAME = "current program"


def normalize(payload):
    """Convert a valid v1 or v2 payload into one shape:
    {"program": {"name", "weeks"} | None, "routines": [{name, week, exercises}]}
    """
    if payload["version"] == 1:
        return {
            "program": None,
            "routines": [
                {"name": r["name"].strip(), "week": 1, "exercises": r["exercises"]}
                for r in payload["routines"]
            ],
        }
    program = payload["program"]
    routines = [
        {"name": r["name"].strip(), "week": r.get("week", 1), "exercises": r["exercises"]}
        for r in program["routines"]
    ]
    weeks = program.get("weeks", max(r["week"] for r in routines))
    return {
        "program": {"name": program["name"].strip(), "weeks": weeks},
        "routines": routines,
    }


def validate(payload):
    """Return a list of human-readable problems; empty list = importable."""
    if not isinstance(payload, dict):
        return ["top level must be a JSON object"]
    version = payload.get("version")
    if version == 1:
        return _validate_routines(payload.get("routines"), max_week=1)
    if version == 2:
        return _validate_program(payload.get("program"))
    return ["version must be 1 or 2"]


def _validate_program(program):
    if not isinstance(program, dict):
        return ["program must be an object"]
    errors = []
    name = program.get("name")
    if not isinstance(name, str) or not name.strip():
        errors.append("program: missing name")
    weeks = program.get("weeks", 1)
    if not isinstance(weeks, int) or weeks < 1:
        errors.append("program: weeks must be a positive integer")
        weeks = None
    errors.extend(_validate_routines(program.get("routines"), max_week=weeks))
    return errors


def _validate_routines(routines, max_week):
    if not isinstance(routines, list) or not routines:
        return ["routines must be a non-empty list"]
    errors = []
    seen = set()
    for i, routine in enumerate(routines):
        where = f"routine {i + 1}"
        if not isinstance(routine, dict):
            errors.append(f"{where}: must be an object")
            continue
        name = routine.get("name")
        if not isinstance(name, str) or not name.strip():
            errors.append(f"{where}: missing name")
            continue
        where = f"routine '{name}'"
        if name.strip().lower() in seen:
            errors.append(f"{where}: duplicate routine name in import")
        seen.add(name.strip().lower())
        week = routine.get("week", 1)
        if not isinstance(week, int) or week < 1 or (max_week and week > max_week):
            errors.append(f"{where}: week must be an integer between 1 and weeks")
        exercises = routine.get("exercises")
        if not isinstance(exercises, list) or not exercises:
            errors.append(f"{where}: exercises must be a non-empty list")
            continue
        for j, ex in enumerate(exercises):
            errors.extend(_validate_exercise(ex, f"{where}, exercise {j + 1}"))
    return errors


def _validate_exercise(ex, where):
    errors = []
    if not isinstance(ex, dict):
        return [f"{where}: must be an object"]
    name = ex.get("name")
    if not isinstance(name, str) or not name.strip():
        errors.append(f"{where}: missing name")
    else:
        where = f"{where} ('{name}')"
    if ex.get("movement_pattern") not in MOVEMENT_PATTERNS:
        errors.append(f"{where}: movement_pattern must be one of "
                      + ", ".join(sorted(MOVEMENT_PATTERNS)))
    if ex.get("muscle_group") not in MUSCLE_GROUPS:
        errors.append(f"{where}: muscle_group must be one of "
                      + ", ".join(sorted(MUSCLE_GROUPS)))
    if not isinstance(ex.get("sets"), int) or ex["sets"] < 1:
        errors.append(f"{where}: sets must be a positive integer")
    rep_min, rep_max = ex.get("rep_min"), ex.get("rep_max")
    if not isinstance(rep_min, int) or not isinstance(rep_max, int) \
            or rep_min < 1 or rep_min > rep_max:
        errors.append(f"{where}: rep_min/rep_max must be integers with rep_min <= rep_max")
    if "rest_seconds" in ex and (not isinstance(ex["rest_seconds"], int) or ex["rest_seconds"] <= 0):
        errors.append(f"{where}: rest_seconds must be a positive integer")
    # increment_kg may be 0 for bodyweight / no-load exercises (no progression step)
    if "increment_kg" in ex and (not isinstance(ex["increment_kg"], (int, float)) or ex["increment_kg"] < 0):
        errors.append(f"{where}: increment_kg must be zero or a positive number")
    # exercise_type/display_unit are optional; default weight_reps + type-appropriate unit
    if "exercise_type" in ex and ex["exercise_type"] not in EXERCISE_TYPES:
        errors.append(f"{where}: exercise_type must be one of " + ", ".join(sorted(EXERCISE_TYPES)))
    if "display_unit" in ex and ex["display_unit"] not in DISPLAY_UNITS:
        errors.append(f"{where}: display_unit must be one of kg, lbs, km, mi")
    # equipment is optional free text (update-on-name-match, like cue/youtube_query)
    if "equipment" in ex and ex["equipment"] is not None and not isinstance(ex["equipment"], str):
        errors.append(f"{where}: equipment must be a string")
    return errors


def _with_defaults(ex):
    merged = dict(EXERCISE_DEFAULTS)
    merged.update(ex)
    merged["name"] = merged["name"].strip()
    return merged


def _target_program(db, norm):
    """(program_row_or_None, display_name). For v1 the target is the active
    program, which may not exist yet."""
    if norm["program"]:
        row = db.execute(
            "SELECT * FROM program WHERE name = ?", (norm["program"]["name"],)
        ).fetchone()
        return row, norm["program"]["name"]
    row = db.execute("SELECT * FROM program WHERE is_active = 1").fetchone()
    return row, (row["name"] if row else FALLBACK_PROGRAM_NAME)


def plan(db, norm):
    """Human-readable preview of what apply() will do. Read-only."""
    program_row, program_name = _target_program(db, norm)
    is_v2 = norm["program"] is not None
    routines = []
    for routine in norm["routines"]:
        existing = program_row and db.execute(
            "SELECT id FROM routine WHERE program_id = ? AND name = ?",
            (program_row["id"], routine["name"]),
        ).fetchone()
        exercises = []
        for ex in routine["exercises"]:
            ex = _with_defaults(ex)
            known = db.execute(
                "SELECT id FROM exercise WHERE name = ? COLLATE NOCASE", (ex["name"],)
            ).fetchone()
            exercises.append({
                "name": ex["name"],
                "action": "update" if known else "create",
                "type": ex["exercise_type"],
                "sets": ex["sets"],
                "rep_min": ex["rep_min"],
                "rep_max": ex["rep_max"],
                "is_primary": bool(ex["is_primary"]),
            })
        routines.append({
            "name": routine["name"],
            "week": routine["week"],
            "action": "replace" if existing else "create",
            "exercises": exercises,
        })
    archived = []
    if is_v2 and program_row:
        imported_names = {r["name"] for r in norm["routines"]}
        for row in db.execute(
            "SELECT name FROM routine WHERE program_id = ? AND is_archived = 0",
            (program_row["id"],),
        ):
            if row["name"] not in imported_names:
                archived.append(row["name"])
    return {
        "program": {
            "name": program_name,
            "weeks": norm["program"]["weeks"] if is_v2 else (
                program_row["weeks_count"] if program_row else 1),
            "action": ("replace" if program_row else "create") if is_v2 else "into",
        },
        "routines": routines,
        "archived": archived,
    }


def apply_import(db, norm, now):
    """Write the import. Caller commits."""
    program_row, program_name = _target_program(db, norm)
    is_v2 = norm["program"] is not None

    if program_row is None:
        weeks = norm["program"]["weeks"] if is_v2 else 1
        program_id = db.execute(
            "INSERT INTO program (name, weeks_count, is_active, created_at, updated_at) "
            "VALUES (?, ?, 0, ?, ?)",
            (program_name, weeks, now, now),
        ).lastrowid
    else:
        program_id = program_row["id"]
        if is_v2:
            db.execute(
                "UPDATE program SET weeks_count = ?, updated_at = ? WHERE id = ?",
                (norm["program"]["weeks"], now, program_id),
            )

    if is_v2 or program_row is None:
        _activate(db, program_id, was_active=bool(program_row and program_row["is_active"]))

    for pos, routine in enumerate(norm["routines"]):
        existing = db.execute(
            "SELECT id FROM routine WHERE program_id = ? AND name = ?",
            (program_id, routine["name"]),
        ).fetchone()
        if existing:
            routine_id = existing["id"]
            db.execute(
                "UPDATE routine SET week_number = ?, position = ?, is_archived = 0, "
                "updated_at = ? WHERE id = ?",
                (routine["week"], pos, now, routine_id),
            )
            db.execute("DELETE FROM routine_exercise WHERE routine_id = ?", (routine_id,))
        else:
            routine_id = db.execute(
                "INSERT INTO routine (program_id, name, week_number, position, created_at, "
                "updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (program_id, routine["name"], routine["week"], pos, now, now),
            ).lastrowid
        for ex_pos, ex in enumerate(routine["exercises"]):
            ex = _with_defaults(ex)
            exercise_id = _upsert_exercise(db, ex, now)
            db.execute(
                "INSERT INTO routine_exercise (routine_id, exercise_id, position, target_sets, "
                "rep_min, rep_max, rest_seconds, is_primary) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (routine_id, exercise_id, ex_pos, ex["sets"], ex["rep_min"], ex["rep_max"],
                 ex["rest_seconds"], 1 if ex["is_primary"] else 0),
            )

    if is_v2:
        imported_names = {r["name"] for r in norm["routines"]}
        for row in db.execute(
            "SELECT id, name FROM routine WHERE program_id = ? AND is_archived = 0",
            (program_id,),
        ).fetchall():
            if row["name"] not in imported_names:
                db.execute(
                    "UPDATE routine SET is_archived = 1, updated_at = ? WHERE id = ?",
                    (now, row["id"]),
                )
        # keep program_week valid if the cycle shrank
        db.execute(
            "UPDATE program_state SET program_week = 1 WHERE id = 1 AND program_week > ?",
            (norm["program"]["weeks"],),
        )


def _activate(db, program_id, was_active):
    db.execute("UPDATE program SET is_active = 0 WHERE id != ?", (program_id,))
    db.execute("UPDATE program SET is_active = 1 WHERE id = ?", (program_id,))
    if not was_active:
        db.execute("UPDATE program_state SET program_week = 1 WHERE id = 1")


def _default_unit(ex):
    """Explicit display_unit wins; otherwise distance types default to km and
    everything else to kg (kg is harmless/ignored for reps_only/duration/none)."""
    unit = ex.get("display_unit")
    if unit in DISPLAY_UNITS:
        return unit
    return "km" if ex["exercise_type"] in DISTANCE_TYPES else "kg"


def _upsert_exercise(db, ex, now):
    etype = ex["exercise_type"]
    equipment = ex.get("equipment")
    provided_unit = ex.get("display_unit") if ex.get("display_unit") in DISPLAY_UNITS else None
    known = db.execute(
        "SELECT id FROM exercise WHERE name = ? COLLATE NOCASE", (ex["name"],)
    ).fetchone()
    if known:
        # update tags + type + equipment; only override display_unit when the import
        # states one, otherwise preserve the user's kg/lbs (or km/mi) toggle
        if provided_unit:
            db.execute(
                "UPDATE exercise SET cue = ?, youtube_query = ?, movement_pattern = ?, "
                "muscle_group = ?, exercise_type = ?, equipment = ?, display_unit = ?, "
                "increment_kg = ? WHERE id = ?",
                (ex["cue"], ex["youtube_query"], ex["movement_pattern"], ex["muscle_group"],
                 etype, equipment, provided_unit, float(ex["increment_kg"]), known["id"]),
            )
        else:
            db.execute(
                "UPDATE exercise SET cue = ?, youtube_query = ?, movement_pattern = ?, "
                "muscle_group = ?, exercise_type = ?, equipment = ?, increment_kg = ? WHERE id = ?",
                (ex["cue"], ex["youtube_query"], ex["movement_pattern"], ex["muscle_group"],
                 etype, equipment, float(ex["increment_kg"]), known["id"]),
            )
        return known["id"]
    return db.execute(
        "INSERT INTO exercise (name, cue, youtube_query, movement_pattern, muscle_group, "
        "exercise_type, equipment, display_unit, increment_kg, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (ex["name"], ex["cue"], ex["youtube_query"], ex["movement_pattern"],
         ex["muscle_group"], etype, equipment, _default_unit(ex), float(ex["increment_kg"]), now),
    ).lastrowid
