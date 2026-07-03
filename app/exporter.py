"""Full-database JSON export per docs/schema.md: the import v2 shape (programs
with routines + exercises) plus the full exercise library and the history
tables (workouts, set_logs, substitutions, program_state). Restorable backup
and data portability — exportable at any time."""


def _rows(db, sql, params=()):
    return [dict(r) for r in db.execute(sql, params).fetchall()]


def _routine_exercises(db, routine_id):
    """Exercises for one routine in the import-file shape (tags + targets, no
    history). Shared by the full export and the program-only export."""
    exercises = []
    for re in db.execute(
        "SELECT re.*, e.name, e.cue, e.youtube_query, e.movement_pattern, "
        "e.muscle_group, e.exercise_type, e.equipment, e.display_unit, e.increment_kg "
        "FROM routine_exercise re "
        "JOIN exercise e ON e.id = re.exercise_id "
        "WHERE re.routine_id = ? ORDER BY re.position",
        (routine_id,),
    ):
        exercises.append({
            "name": re["name"],
            "cue": re["cue"],
            "youtube_query": re["youtube_query"],
            "movement_pattern": re["movement_pattern"],
            "muscle_group": re["muscle_group"],
            "exercise_type": re["exercise_type"],
            "equipment": re["equipment"],
            "display_unit": re["display_unit"],
            "sets": re["target_sets"],
            "rep_min": re["rep_min"],
            "rep_max": re["rep_max"],
            "rest_seconds": re["rest_seconds"],
            "increment_kg": re["increment_kg"],
            "is_primary": bool(re["is_primary"]),
        })
    return exercises


def export_program(db):
    """The active program alone, in the exact v2 import-envelope shape — no
    workout/set_log/substitution history at all. Byte-for-byte re-importable
    through the Import screen with no transformation (BACKLOG item 9). Only
    live (non-archived) routines are included, so a round-trip doesn't drag
    dropped routines back in. Returns None when there is no active program."""
    p = db.execute("SELECT * FROM program WHERE is_active = 1").fetchone()
    if p is None:
        return None
    routines = []
    for r in db.execute(
        "SELECT * FROM routine WHERE program_id = ? AND is_archived = 0 "
        "ORDER BY week_number, position, id",
        (p["id"],),
    ):
        routines.append({
            "name": r["name"],
            "week": r["week_number"],
            "exercises": _routine_exercises(db, r["id"]),
        })
    return {
        "version": 2,
        "program": {
            "name": p["name"],
            "weeks": p["weeks_count"],
            "routines": routines,
        },
    }


def export_all(db, exported_at):
    programs = []
    for p in db.execute("SELECT * FROM program ORDER BY id"):
        routines = []
        for r in db.execute(
            "SELECT * FROM routine WHERE program_id = ? ORDER BY week_number, position, id",
            (p["id"],),
        ):
            routines.append({
                "name": r["name"],
                "week": r["week_number"],
                "is_archived": bool(r["is_archived"]),
                "exercises": _routine_exercises(db, r["id"]),
            })
        programs.append({
            "name": p["name"],
            "weeks": p["weeks_count"],
            "is_active": bool(p["is_active"]),
            "routines": routines,
        })

    return {
        "version": 2,
        "exported_at": exported_at,
        "programs": programs,
        "exercises": _rows(db, "SELECT * FROM exercise ORDER BY id"),
        "workouts": _rows(db, "SELECT * FROM workout ORDER BY id"),
        "set_logs": _rows(db, "SELECT * FROM set_log ORDER BY id"),
        "substitutions": _rows(db, "SELECT * FROM substitution ORDER BY id"),
        "program_state": dict(
            db.execute("SELECT * FROM program_state WHERE id = 1").fetchone()
        ),
    }
