"""Claude JSON import (format v1) — validation, preview plan, and apply.

Dedupe semantics per docs/schema.md: routine matched by name -> replace its
routine_exercise rows; exercise matched by name (case-insensitive) -> update
cue/query/tags, never touch history; unknown exercise -> create.
"""

MOVEMENT_PATTERNS = {
    "horizontal_pull", "vertical_pull", "hinge", "squat",
    "horizontal_push", "vertical_push", "isolation", "core",
}
MUSCLE_GROUPS = {"back", "chest", "shoulders", "legs", "glutes", "arms", "core"}

EXERCISE_DEFAULTS = {
    "cue": "",
    "youtube_query": "",
    "rest_seconds": 90,
    "increment_kg": 2.5,
    "is_primary": False,
}


def validate(payload):
    """Return a list of human-readable problems; empty list = importable."""
    errors = []
    if not isinstance(payload, dict):
        return ["top level must be a JSON object"]
    if payload.get("version") != 1:
        errors.append("version must be 1")
    routines = payload.get("routines")
    if not isinstance(routines, list) or not routines:
        return errors + ["routines must be a non-empty list"]
    seen_routines = set()
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
        if name.lower() in seen_routines:
            errors.append(f"{where}: duplicate routine name in import")
        seen_routines.add(name.lower())
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
    for field, kind in (("rest_seconds", int), ("increment_kg", (int, float))):
        if field in ex and (not isinstance(ex[field], kind) or ex[field] <= 0):
            errors.append(f"{where}: {field} must be a positive number")
    return errors


def _with_defaults(ex):
    merged = dict(EXERCISE_DEFAULTS)
    merged.update(ex)
    merged["name"] = merged["name"].strip()
    return merged


def plan(db, payload):
    """Human-readable preview of what apply() will do. Read-only."""
    routines = []
    for routine in payload["routines"]:
        existing = db.execute(
            "SELECT id FROM routine WHERE name = ?", (routine["name"].strip(),)
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
                "sets": ex["sets"],
                "rep_min": ex["rep_min"],
                "rep_max": ex["rep_max"],
                "is_primary": bool(ex["is_primary"]),
            })
        routines.append({
            "name": routine["name"].strip(),
            "action": "replace" if existing else "create",
            "exercises": exercises,
        })
    return routines


def apply_import(db, payload, now):
    """Write the import. Caller commits."""
    for routine in payload["routines"]:
        name = routine["name"].strip()
        existing = db.execute("SELECT id FROM routine WHERE name = ?", (name,)).fetchone()
        if existing:
            routine_id = existing["id"]
            db.execute("UPDATE routine SET updated_at = ? WHERE id = ?", (now, routine_id))
            db.execute("DELETE FROM routine_exercise WHERE routine_id = ?", (routine_id,))
        else:
            position = db.execute(
                "SELECT COALESCE(MAX(position), -1) + 1 FROM routine"
            ).fetchone()[0]
            routine_id = db.execute(
                "INSERT INTO routine (name, position, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (name, position, now, now),
            ).lastrowid
        for pos, ex in enumerate(routine["exercises"]):
            ex = _with_defaults(ex)
            exercise_id = _upsert_exercise(db, ex, now)
            db.execute(
                "INSERT INTO routine_exercise (routine_id, exercise_id, position, target_sets, "
                "rep_min, rep_max, rest_seconds, is_primary) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (routine_id, exercise_id, pos, ex["sets"], ex["rep_min"], ex["rep_max"],
                 ex["rest_seconds"], 1 if ex["is_primary"] else 0),
            )


def _upsert_exercise(db, ex, now):
    known = db.execute(
        "SELECT id FROM exercise WHERE name = ? COLLATE NOCASE", (ex["name"],)
    ).fetchone()
    if known:
        db.execute(
            "UPDATE exercise SET cue = ?, youtube_query = ?, movement_pattern = ?, "
            "muscle_group = ?, increment_kg = ? WHERE id = ?",
            (ex["cue"], ex["youtube_query"], ex["movement_pattern"],
             ex["muscle_group"], float(ex["increment_kg"]), known["id"]),
        )
        return known["id"]
    return db.execute(
        "INSERT INTO exercise (name, cue, youtube_query, movement_pattern, muscle_group, "
        "increment_kg, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (ex["name"], ex["cue"], ex["youtube_query"], ex["movement_pattern"],
         ex["muscle_group"], float(ex["increment_kg"]), now),
    ).lastrowid
