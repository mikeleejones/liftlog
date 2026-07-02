import sqlite3
from datetime import datetime, timedelta, timezone

from .config import DB_PATH

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

CREATE TABLE IF NOT EXISTS routine (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    position    INTEGER NOT NULL DEFAULT 0,
    is_archived INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
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
    week_anchor            TEXT NOT NULL
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
    db.executescript(SCHEMA)
    now = utcnow()
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


def _seed(db, now):
    cur = db.execute(
        "INSERT INTO routine (name, position, created_at, updated_at) VALUES (?, 0, ?, ?)",
        (SEED_ROUTINE["name"], now, now),
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


def run_week_completion(db):
    """Per docs/schema.md: on app load, roll week_anchor forward one week at a
    time, crediting weeks that had >= 3 finished non-deload workouts."""
    state = db.execute("SELECT * FROM program_state WHERE id = 1").fetchone()
    anchor = datetime.strptime(state["week_anchor"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    completed = state["completed_weeks"]
    since_deload = state["weeks_since_deload"]
    changed = False
    while anchor + timedelta(days=7) <= now:
        window_end = anchor + timedelta(days=7)
        count = db.execute(
            "SELECT COUNT(*) FROM workout WHERE finished_at IS NOT NULL AND is_deload = 0 "
            "AND started_at >= ? AND started_at < ?",
            (anchor.strftime("%Y-%m-%dT%H:%M:%SZ"), window_end.strftime("%Y-%m-%dT%H:%M:%SZ")),
        ).fetchone()[0]
        if count >= 3:
            completed += 1
            since_deload += 1
        anchor = window_end
        changed = True
    if changed:
        db.execute(
            "UPDATE program_state SET completed_weeks = ?, weeks_since_deload = ?, week_anchor = ? "
            "WHERE id = 1",
            (completed, since_deload, anchor.strftime("%Y-%m-%dT%H:%M:%SZ")),
        )
        db.commit()
