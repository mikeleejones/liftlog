import sqlite3
from datetime import datetime, timedelta, timezone

from .config import DB_PATH

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS exercise (
    id               INTEGER PRIMARY KEY,
    name             TEXT NOT NULL UNIQUE COLLATE NOCASE,
    cue              TEXT NOT NULL DEFAULT '',
    youtube_query    TEXT NOT NULL DEFAULT '',
    movement_pattern TEXT NOT NULL,
    muscle_group     TEXT NOT NULL,
    display_unit     TEXT NOT NULL DEFAULT 'kg'
                     CHECK (display_unit IN ('kg','lbs')),
    increment_kg     REAL NOT NULL DEFAULT 2.5,
    is_archived      INTEGER NOT NULL DEFAULT 0,
    created_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS program (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    weeks_count INTEGER NOT NULL DEFAULT 1,
    is_active   INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS routine (
    id          INTEGER PRIMARY KEY,
    program_id  INTEGER REFERENCES program(id),
    name        TEXT NOT NULL,
    week_number INTEGER NOT NULL DEFAULT 1,
    position    INTEGER NOT NULL DEFAULT 0,
    is_archived INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    UNIQUE (program_id, name)
);

CREATE TABLE IF NOT EXISTS routine_exercise (
    id            INTEGER PRIMARY KEY,
    routine_id    INTEGER NOT NULL REFERENCES routine(id) ON DELETE CASCADE,
    exercise_id   INTEGER NOT NULL REFERENCES exercise(id),
    position      INTEGER NOT NULL,
    target_sets   INTEGER NOT NULL,
    rep_min       INTEGER NOT NULL,
    rep_max       INTEGER NOT NULL,
    rest_seconds  INTEGER NOT NULL DEFAULT 90,
    is_primary    INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS workout (
    id           INTEGER PRIMARY KEY,
    routine_id   INTEGER REFERENCES routine(id),
    started_at   TEXT NOT NULL,
    finished_at  TEXT,
    is_deload    INTEGER NOT NULL DEFAULT 0,
    note         TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS set_log (
    id          INTEGER PRIMARY KEY,
    workout_id  INTEGER NOT NULL REFERENCES workout(id) ON DELETE CASCADE,
    exercise_id INTEGER NOT NULL REFERENCES exercise(id),
    set_number  INTEGER NOT NULL,
    set_type    TEXT NOT NULL DEFAULT 'normal'
                CHECK (set_type IN ('normal','warmup','failure')),
    weight_kg   REAL NOT NULL,
    reps        INTEGER NOT NULL,
    was_suggested INTEGER NOT NULL DEFAULT 0,
    logged_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_setlog_exercise ON set_log(exercise_id, logged_at);
CREATE INDEX IF NOT EXISTS idx_setlog_workout  ON set_log(workout_id);

CREATE TABLE IF NOT EXISTS substitution (
    id                   INTEGER PRIMARY KEY,
    workout_id           INTEGER NOT NULL REFERENCES workout(id) ON DELETE CASCADE,
    planned_exercise_id  INTEGER NOT NULL REFERENCES exercise(id),
    actual_exercise_id   INTEGER,
    reason               TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS program_state (
    id                     INTEGER PRIMARY KEY CHECK (id = 1),
    completed_weeks        INTEGER NOT NULL DEFAULT 0,
    weeks_since_deload     INTEGER NOT NULL DEFAULT 0,
    deload_deferred_until  TEXT,
    week_anchor            TEXT NOT NULL,
    program_week           INTEGER NOT NULL DEFAULT 1
);
"""

# v0.1: the one hardcoded routine for gym testing. Replaced by JSON import in v0.2.
SEED_ROUTINE = {
    "name": "Mon - Hinge + Horizontal",
    "exercises": [
        {
            "name": "Romanian Deadlift",
            "cue": "Hinge at hips, soft knees, neutral spine.",
            "youtube_query": "romanian deadlift form",
            "movement_pattern": "hinge",
            "muscle_group": "legs",
            "sets": 3, "rep_min": 8, "rep_max": 10,
            "rest_seconds": 120, "increment_kg": 2.5, "is_primary": True,
        },
        {
            "name": "Barbell Bench Press",
            "cue": "Shoulder blades pinned, bar to mid-chest, feet planted.",
            "youtube_query": "barbell bench press form",
            "movement_pattern": "horizontal_push",
            "muscle_group": "chest",
            "sets": 3, "rep_min": 6, "rep_max": 8,
            "rest_seconds": 120, "increment_kg": 2.5, "is_primary": True,
        },
        {
            "name": "Seated Cable Row",
            "cue": "Chest tall, pull to sternum, no torso swing.",
            "youtube_query": "seated cable row form",
            "movement_pattern": "horizontal_pull",
            "muscle_group": "back",
            "sets": 3, "rep_min": 8, "rep_max": 10,
            "rest_seconds": 90, "increment_kg": 2.5, "is_primary": False,
        },
        {
            "name": "Dumbbell Shoulder Press",
            "cue": "Elbows slightly forward, press without arching.",
            "youtube_query": "seated dumbbell shoulder press form",
            "movement_pattern": "vertical_push",
            "muscle_group": "shoulders",
            "sets": 3, "rep_min": 8, "rep_max": 10,
            "rest_seconds": 90, "increment_kg": 2.5, "is_primary": False,
        },
        {
            "name": "Lat Pulldown",
            "cue": "Pull to collarbone, elbows down and back.",
            "youtube_query": "lat pulldown form",
            "movement_pattern": "vertical_pull",
            "muscle_group": "back",
            "sets": 3, "rep_min": 8, "rep_max": 10,
            "rest_seconds": 90, "increment_kg": 2.5, "is_primary": False,
        },
    ],
}


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    db = get_db()
    now = utcnow()
    if _needs_program_migration(db):
        _migrate_to_programs(db, now)
    db.executescript(SCHEMA)
    db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    row = db.execute("SELECT id FROM program_state WHERE id = 1").fetchone()
    if row is None:
        db.execute(
            "INSERT INTO program_state (id, completed_weeks, weeks_since_deload, week_anchor) "
            "VALUES (1, 0, 0, ?)",
            (now,),
        )
    if db.execute("SELECT COUNT(*) FROM routine").fetchone()[0] == 0:
        _seed(db, now)
    db.commit()
    db.close()


def _needs_program_migration(db):
    """True for a pre-v0.2.5 database: routine table exists without program_id."""
    if db.execute("PRAGMA user_version").fetchone()[0] >= SCHEMA_VERSION:
        return False
    has_routine = db.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'routine'"
    ).fetchone()
    if not has_routine:
        return False
    columns = {r["name"] for r in db.execute("PRAGMA table_info(routine)")}
    return "program_id" not in columns


def _migrate_to_programs(db, now):
    """Rebuild routine with program scoping; wrap existing routines in an
    active 'current program' so weekly compliance keeps working."""
    db.execute("PRAGMA foreign_keys = OFF")
    db.executescript("""
        CREATE TABLE program (
            id          INTEGER PRIMARY KEY,
            name        TEXT NOT NULL UNIQUE,
            weeks_count INTEGER NOT NULL DEFAULT 1,
            is_active   INTEGER NOT NULL DEFAULT 0,
            created_at  TEXT NOT NULL,
            updated_at  TEXT NOT NULL
        );
    """)
    program_id = None
    if db.execute("SELECT COUNT(*) FROM routine").fetchone()[0] > 0:
        program_id = db.execute(
            "INSERT INTO program (name, weeks_count, is_active, created_at, updated_at) "
            "VALUES ('current program', 1, 1, ?, ?)",
            (now, now),
        ).lastrowid
    db.executescript("""
        CREATE TABLE routine_new (
            id          INTEGER PRIMARY KEY,
            program_id  INTEGER REFERENCES program(id),
            name        TEXT NOT NULL,
            week_number INTEGER NOT NULL DEFAULT 1,
            position    INTEGER NOT NULL DEFAULT 0,
            is_archived INTEGER NOT NULL DEFAULT 0,
            created_at  TEXT NOT NULL,
            updated_at  TEXT NOT NULL,
            UNIQUE (program_id, name)
        );
    """)
    db.execute(
        "INSERT INTO routine_new (id, program_id, name, week_number, position, is_archived, "
        "created_at, updated_at) SELECT id, ?, name, 1, position, is_archived, created_at, "
        "updated_at FROM routine",
        (program_id,),
    )
    db.executescript("""
        DROP TABLE routine;
        ALTER TABLE routine_new RENAME TO routine;
        ALTER TABLE program_state ADD COLUMN program_week INTEGER NOT NULL DEFAULT 1;
    """)
    db.execute("PRAGMA foreign_keys = ON")


def _seed(db, now):
    program_id = db.execute(
        "INSERT INTO program (name, weeks_count, is_active, created_at, updated_at) "
        "VALUES ('starter', 1, 1, ?, ?)",
        (now, now),
    ).lastrowid
    cur = db.execute(
        "INSERT INTO routine (program_id, name, week_number, position, created_at, updated_at) "
        "VALUES (?, ?, 1, 0, ?, ?)",
        (program_id, SEED_ROUTINE["name"], now, now),
    )
    routine_id = cur.lastrowid
    for pos, ex in enumerate(SEED_ROUTINE["exercises"]):
        cur = db.execute(
            "INSERT INTO exercise (name, cue, youtube_query, movement_pattern, muscle_group, "
            "increment_kg, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (ex["name"], ex["cue"], ex["youtube_query"], ex["movement_pattern"],
             ex["muscle_group"], ex["increment_kg"], now),
        )
        db.execute(
            "INSERT INTO routine_exercise (routine_id, exercise_id, position, target_sets, "
            "rep_min, rep_max, rest_seconds, is_primary) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (routine_id, cur.lastrowid, pos, ex["sets"], ex["rep_min"], ex["rep_max"],
             ex["rest_seconds"], 1 if ex["is_primary"] else 0),
        )


def sessions_required(db, program_week):
    """Prescribed sessions for the active program's given week; 3 if no
    active program (per docs/schema.md)."""
    active = db.execute("SELECT id FROM program WHERE is_active = 1").fetchone()
    if active is None:
        return 3, None
    count = db.execute(
        "SELECT COUNT(*) FROM routine WHERE program_id = ? AND week_number = ? "
        "AND is_archived = 0",
        (active["id"], program_week),
    ).fetchone()[0]
    return (count if count > 0 else 3), active["id"]


def run_week_completion(db):
    """Per docs/schema.md: on app load, roll week_anchor forward one week at a
    time. A week completes when all sessions prescribed by the active program
    week are finished; program_week advances (wrapping) only on completion."""
    state = db.execute("SELECT * FROM program_state WHERE id = 1").fetchone()
    anchor = datetime.strptime(state["week_anchor"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    completed = state["completed_weeks"]
    since_deload = state["weeks_since_deload"]
    deferred = state["deload_deferred_until"]
    program_week = state["program_week"]
    changed = False
    while anchor + timedelta(days=7) <= now:
        window_end = anchor + timedelta(days=7)
        window = (anchor.strftime("%Y-%m-%dT%H:%M:%SZ"), window_end.strftime("%Y-%m-%dT%H:%M:%SZ"))
        count = db.execute(
            "SELECT COUNT(*) FROM workout WHERE finished_at IS NOT NULL AND is_deload = 0 "
            "AND started_at >= ? AND started_at < ?", window,
        ).fetchone()[0]
        required, program_id = sessions_required(db, program_week)
        if count >= required:
            completed += 1
            since_deload += 1
            if program_id is not None:
                weeks_count = db.execute(
                    "SELECT weeks_count FROM program WHERE id = ?", (program_id,)
                ).fetchone()[0]
                program_week = program_week % weeks_count + 1
        # a week in which deload sessions were finished resets the deload clock;
        # deload weeks add nothing to completed_weeks and leave program_week alone
        deload_count = db.execute(
            "SELECT COUNT(*) FROM workout WHERE finished_at IS NOT NULL AND is_deload = 1 "
            "AND started_at >= ? AND started_at < ?", window,
        ).fetchone()[0]
        if deload_count > 0:
            since_deload = 0
            deferred = None
        anchor = window_end
        changed = True
    if changed:
        db.execute(
            "UPDATE program_state SET completed_weeks = ?, weeks_since_deload = ?, "
            "deload_deferred_until = ?, week_anchor = ?, program_week = ? WHERE id = 1",
            (completed, since_deload, deferred,
             anchor.strftime("%Y-%m-%dT%H:%M:%SZ"), program_week),
        )
        db.commit()
