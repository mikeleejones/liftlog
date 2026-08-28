"""Baseline the current LiftLog SQLite schema.

Revision ID: 20260827_01
Revises:
Create Date: 2026-08-27

This migration is intentionally a baseline, not a translation of the legacy
`db.py` upgrade chain. Existing databases already have this schema and must be
marked with `alembic stamp 20260827_01`; applying this revision is only for a
new, empty SQLite file.
"""

from alembic import op


revision = "20260827_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE exercise (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL UNIQUE COLLATE NOCASE,
            cue TEXT NOT NULL DEFAULT '',
            youtube_query TEXT NOT NULL DEFAULT '',
            movement_pattern TEXT NOT NULL,
            muscle_group TEXT NOT NULL,
            exercise_type TEXT NOT NULL DEFAULT 'weight_reps'
                CHECK (exercise_type IN ('weight_reps','reps_only','duration','duration_weight',
                    'distance','distance_weight','none')),
            display_unit TEXT NOT NULL DEFAULT 'kg' CHECK (display_unit IN ('kg','lbs','km','mi')),
            increment_kg REAL NOT NULL DEFAULT 2.5,
            is_archived INTEGER NOT NULL DEFAULT 0,
            progress_reset_at TEXT,
            equipment TEXT,
            created_at TEXT NOT NULL
        )
    """)
    op.execute("""
        CREATE TABLE program (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            weeks_count INTEGER NOT NULL DEFAULT 1,
            is_active INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    op.execute("""
        CREATE TABLE routine (
            id INTEGER PRIMARY KEY,
            program_id INTEGER REFERENCES program(id),
            name TEXT NOT NULL,
            week_number INTEGER NOT NULL DEFAULT 1,
            position INTEGER NOT NULL DEFAULT 0,
            is_archived INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE (program_id, name)
        )
    """)
    op.execute("""
        CREATE TABLE routine_exercise (
            id INTEGER PRIMARY KEY,
            routine_id INTEGER NOT NULL REFERENCES routine(id) ON DELETE CASCADE,
            exercise_id INTEGER NOT NULL REFERENCES exercise(id),
            position INTEGER NOT NULL,
            target_sets INTEGER NOT NULL,
            rep_min INTEGER NOT NULL,
            rep_max INTEGER NOT NULL,
            rest_seconds INTEGER NOT NULL DEFAULT 90,
            is_primary INTEGER NOT NULL DEFAULT 0
        )
    """)
    op.execute("""
        CREATE TABLE workout (
            id INTEGER PRIMARY KEY,
            routine_id INTEGER REFERENCES routine(id) ON DELETE SET NULL,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            is_deload INTEGER NOT NULL DEFAULT 0,
            note TEXT NOT NULL DEFAULT ''
        )
    """)
    op.execute("""
        CREATE TABLE set_log (
            id INTEGER PRIMARY KEY,
            workout_id INTEGER NOT NULL REFERENCES workout(id) ON DELETE CASCADE,
            exercise_id INTEGER NOT NULL REFERENCES exercise(id),
            set_number INTEGER NOT NULL,
            set_type TEXT NOT NULL DEFAULT 'normal' CHECK (set_type IN ('normal','warmup','failure')),
            weight_kg REAL,
            reps INTEGER,
            duration_seconds REAL,
            distance_m REAL,
            was_suggested INTEGER NOT NULL DEFAULT 0,
            logged_at TEXT NOT NULL
        )
    """)
    op.execute("CREATE INDEX idx_setlog_exercise ON set_log(exercise_id, logged_at)")
    op.execute("CREATE INDEX idx_setlog_workout ON set_log(workout_id)")
    op.execute("""
        CREATE TABLE substitution (
            id INTEGER PRIMARY KEY,
            workout_id INTEGER NOT NULL REFERENCES workout(id) ON DELETE CASCADE,
            planned_exercise_id INTEGER NOT NULL REFERENCES exercise(id),
            actual_exercise_id INTEGER REFERENCES exercise(id),
            reason TEXT NOT NULL DEFAULT ''
        )
    """)
    op.execute("""
        CREATE TABLE program_state (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            completed_weeks INTEGER NOT NULL DEFAULT 0,
            weeks_since_deload INTEGER NOT NULL DEFAULT 0,
            deload_deferred_until TEXT,
            week_anchor TEXT NOT NULL,
            program_week INTEGER NOT NULL DEFAULT 1,
            objective TEXT,
            bodyweight_kg REAL
        )
    """)
    op.execute("""
        CREATE TABLE ai_suggestion_cache (
            id INTEGER PRIMARY KEY,
            planned_exercise_id INTEGER NOT NULL REFERENCES exercise(id),
            suggestion_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            shown_at TEXT
        )
    """)
    op.execute("""
        CREATE TABLE ai_call_log (
            id INTEGER PRIMARY KEY,
            created_at TEXT NOT NULL
        )
    """)
    op.execute("""
        CREATE TABLE api_token (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            token TEXT NOT NULL UNIQUE,
            scope TEXT NOT NULL DEFAULT 'read_only' CHECK (scope IN ('read_only')),
            created_at TEXT NOT NULL,
            last_used_at TEXT
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE api_token")
    op.execute("DROP TABLE ai_call_log")
    op.execute("DROP TABLE ai_suggestion_cache")
    op.execute("DROP TABLE program_state")
    op.execute("DROP TABLE substitution")
    op.execute("DROP TABLE set_log")
    op.execute("DROP TABLE workout")
    op.execute("DROP TABLE routine_exercise")
    op.execute("DROP TABLE routine")
    op.execute("DROP TABLE program")
    op.execute("DROP TABLE exercise")
