"""Full-database JSON export per docs/schema.md: the import v2 shape (programs
with routines + exercises) plus the full exercise library and the history
tables (workouts, set_logs, substitutions, program_state). Restorable backup
and data portability — exportable at any time."""


def _rows(db, sql, params=()):
    return [dict(r) for r in db.execute(sql, params).fetchall()]


def export_all(db, exported_at):
    programs = []
    for p in db.execute("SELECT * FROM program ORDER BY id"):
        routines = []
        for r in db.execute(
            "SELECT * FROM routine WHERE program_id = ? ORDER BY week_number, position, id",
            (p["id"],),
        ):
            exercises = []
            for re in db.execute(
                "SELECT re.*, e.name, e.cue, e.youtube_query, e.movement_pattern, "
                "e.muscle_group, e.exercise_type, e.equipment, e.display_unit, e.increment_kg "
                "FROM routine_exercise re "
                "JOIN exercise e ON e.id = re.exercise_id "
                "WHERE re.routine_id = ? ORDER BY re.position",
                (r["id"],),
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
            routines.append({
                "name": r["name"],
                "week": r["week_number"],
                "is_archived": bool(r["is_archived"]),
                "exercises": exercises,
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
