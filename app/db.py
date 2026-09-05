"""SQLAlchemy-backed database access and domain-level persistence helpers.

Existing route/business code continues to use its verified SQL through the
small compatibility facade below while v0.6 moves screens to the JSON API.
The facade deliberately preserves sqlite3.Row access, qmark parameters,
`lastrowid`, and explicit commits, but each connection is now a SQLAlchemy
Session and schema ownership belongs exclusively to Alembic.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator, Sequence

from sqlalchemy import event
from sqlalchemy.engine import CursorResult, Engine, Row
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy import create_engine

from .config import DB_PATH

ALEMBIC_BASELINE = "20260828_02"
AI_CALLS_PER_DAY_LIMIT = 100


def _database_url(path: str) -> str:
    # SQLAlchemy's SQLite URL requires four slashes before an absolute path.
    return f"sqlite+pysqlite:///{Path(path).resolve()}"


engine: Engine = create_engine(_database_url(DB_PATH))


@event.listens_for(engine, "connect")
def _enable_foreign_keys(dbapi_connection: Any, _connection_record: Any) -> None:
    """SQLite does not enforce FKs unless every new connection enables them."""
    dbapi_connection.execute("PRAGMA foreign_keys = ON")


SessionFactory = sessionmaker(bind=engine, expire_on_commit=False)


class DatabaseRow:
    """Compatibility view over a SQLAlchemy Row.

    sqlite3.Row supports both named and positional indexing and can be passed
    to `dict()`. Existing behavior relies on all three, so preserve that while
    callers are moved incrementally to models/query results in API phases.
    """

    def __init__(self, row: Row[Any]):
        self._row = row

    def __getitem__(self, key: str | int) -> Any:
        return self._row[key] if isinstance(key, int) else self._row._mapping[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._row._mapping)

    def __len__(self) -> int:
        return len(self._row._mapping)

    def keys(self):
        return self._row._mapping.keys()


class DatabaseCursor:
    """Expose the sqlite cursor subset used by the existing application."""

    def __init__(self, result: CursorResult[Any]):
        self._result = result

    @property
    def lastrowid(self) -> int | None:
        return self._result.lastrowid

    def fetchone(self) -> DatabaseRow | None:
        row = self._result.fetchone()
        return DatabaseRow(row) if row is not None else None

    def fetchall(self) -> list[DatabaseRow]:
        return [DatabaseRow(row) for row in self._result.fetchall()]

    def __iter__(self) -> Iterator[DatabaseRow]:
        for row in self._result:
            yield DatabaseRow(row)


class DatabaseSession:
    """A SQLAlchemy Session with the legacy connection-shaped API.

    `exec_driver_sql` intentionally accepts the existing `?` placeholders and
    tuple parameters. Rewriting all 169 stable SQL statements to ORM syntax is
    deferred to the API resource work, where each endpoint can be parity-tested.
    """

    def __init__(self) -> None:
        self._session: Session = SessionFactory()

    def execute(self, statement: str, parameters: Sequence[Any] | dict[str, Any] = ()) -> DatabaseCursor:
        result = self._session.connection().exec_driver_sql(statement, parameters)
        return DatabaseCursor(result)

    def commit(self) -> None:
        self._session.commit()

    def rollback(self) -> None:
        self._session.rollback()

    def close(self) -> None:
        self._session.close()


# v0.1's starter routine remains for a newly created database only. Existing
# databases are stamped at the Alembic baseline and never seeded again.
SEED_ROUTINE = {
    "name": "Mon - Hinge + Horizontal",
    "exercises": [
        {"name": "Romanian Deadlift", "cue": "Hinge at hips, soft knees, neutral spine.", "youtube_query": "romanian deadlift form", "movement_pattern": "hinge", "muscle_group": "legs", "sets": 3, "rep_min": 8, "rep_max": 10, "rest_seconds": 120, "increment_kg": 2.5, "is_primary": True},
        {"name": "Barbell Bench Press", "cue": "Shoulder blades pinned, bar to mid-chest, feet planted.", "youtube_query": "barbell bench press form", "movement_pattern": "horizontal_push", "muscle_group": "chest", "sets": 3, "rep_min": 6, "rep_max": 8, "rest_seconds": 120, "increment_kg": 2.5, "is_primary": True},
        {"name": "Seated Cable Row", "cue": "Chest tall, pull to sternum, no torso swing.", "youtube_query": "seated cable row form", "movement_pattern": "horizontal_pull", "muscle_group": "back", "sets": 3, "rep_min": 8, "rep_max": 10, "rest_seconds": 90, "increment_kg": 2.5, "is_primary": False},
        {"name": "Dumbbell Shoulder Press", "cue": "Elbows slightly forward, press without arching.", "youtube_query": "seated dumbbell shoulder press form", "movement_pattern": "vertical_push", "muscle_group": "shoulders", "sets": 3, "rep_min": 8, "rep_max": 10, "rest_seconds": 90, "increment_kg": 2.5, "is_primary": False},
        {"name": "Lat Pulldown", "cue": "Pull to collarbone, elbows down and back.", "youtube_query": "lat pulldown form", "movement_pattern": "vertical_pull", "muscle_group": "back", "sets": 3, "rep_min": 8, "rep_max": 10, "rest_seconds": 90, "increment_kg": 2.5, "is_primary": False},
    ],
}


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def get_db() -> DatabaseSession:
    return DatabaseSession()


def init_db() -> None:
    """Validate Alembic ownership and initialize only required singleton data.

    This no longer creates or alters tables. Run `alembic upgrade head` for a
    new database, or `alembic stamp 20260827_01` once for an existing pre-v0.6 database
    that already matches this baseline.
    """
    db = get_db()
    try:
        version = db.execute("SELECT version_num FROM alembic_version").fetchone()
    except OperationalError as exc:
        raise RuntimeError(
            "LiftLog database is not under Alembic control. For an existing database, "
            f"run 'alembic stamp {ALEMBIC_BASELINE}'; for a new database, run 'alembic upgrade head'."
        ) from exc
    if version is None or version["version_num"] != ALEMBIC_BASELINE:
        raise RuntimeError(
            f"LiftLog database must be at Alembic revision {ALEMBIC_BASELINE}; "
            "run 'alembic upgrade head'."
        )
    try:
        now = utcnow()
        if db.execute("SELECT id FROM program_state WHERE id = 1").fetchone() is None:
            db.execute(
                "INSERT INTO program_state (id, completed_weeks, weeks_since_deload, week_anchor) "
                "VALUES (1, 0, 0, ?)",
                (now,),
            )
        if db.execute("SELECT COUNT(*) FROM routine").fetchone()[0] == 0:
            _seed(db, now)
        db.commit()
    finally:
        db.close()


def can_make_ai_call(db: DatabaseSession) -> bool:
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")
    count = db.execute("SELECT COUNT(*) FROM ai_call_log WHERE created_at > ?", (cutoff,)).fetchone()[0]
    return count < AI_CALLS_PER_DAY_LIMIT


def _seed(db: DatabaseSession, now: str) -> None:
    program_id = db.execute(
        "INSERT INTO program (name, weeks_count, is_active, created_at, updated_at) "
        "VALUES ('starter', 1, 1, ?, ?)",
        (now, now),
    ).lastrowid
    routine_id = db.execute(
        "INSERT INTO routine (program_id, name, week_number, position, created_at, updated_at) "
        "VALUES (?, ?, 1, 0, ?, ?)",
        (program_id, SEED_ROUTINE["name"], now, now),
    ).lastrowid
    for pos, exercise in enumerate(SEED_ROUTINE["exercises"]):
        exercise_id = db.execute(
            "INSERT INTO exercise (name, cue, youtube_query, movement_pattern, muscle_group, "
            "increment_kg, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (exercise["name"], exercise["cue"], exercise["youtube_query"], exercise["movement_pattern"],
             exercise["muscle_group"], exercise["increment_kg"], now),
        ).lastrowid
        db.execute(
            "INSERT INTO routine_exercise (routine_id, exercise_id, position, target_sets, "
            "rep_min, rep_max, rest_seconds, is_primary) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (routine_id, exercise_id, pos, exercise["sets"], exercise["rep_min"], exercise["rep_max"],
             exercise["rest_seconds"], 1 if exercise["is_primary"] else 0),
        )


def sessions_required(db: DatabaseSession, program_week: int) -> tuple[int, int | None]:
    active = db.execute("SELECT id FROM program WHERE is_active = 1").fetchone()
    if active is None:
        return 3, None
    count = db.execute(
        "SELECT COUNT(*) FROM routine WHERE program_id = ? AND week_number = ? AND is_archived = 0",
        (active["id"], program_week),
    ).fetchone()[0]
    return (count if count > 0 else 3), active["id"]


def run_week_completion(db: DatabaseSession) -> None:
    """Advance completed training weeks; semantics are unchanged from v0.2.5."""
    state = db.execute("SELECT * FROM program_state WHERE id = 1").fetchone()
    anchor = datetime.strptime(state["week_anchor"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    completed, since_deload = state["completed_weeks"], state["weeks_since_deload"]
    deferred, program_week, changed = state["deload_deferred_until"], state["program_week"], False
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
                weeks_count = db.execute("SELECT weeks_count FROM program WHERE id = ?", (program_id,)).fetchone()[0]
                program_week = program_week % weeks_count + 1
        if db.execute(
            "SELECT COUNT(*) FROM workout WHERE finished_at IS NOT NULL AND is_deload = 1 "
            "AND started_at >= ? AND started_at < ?", window,
        ).fetchone()[0] > 0:
            since_deload, deferred = 0, None
        anchor, changed = window_end, True
    if changed:
        db.execute(
            "UPDATE program_state SET completed_weeks = ?, weeks_since_deload = ?, "
            "deload_deferred_until = ?, week_anchor = ?, program_week = ? WHERE id = 1",
            (completed, since_deload, deferred, anchor.strftime("%Y-%m-%dT%H:%M:%SZ"), program_week),
        )
        db.commit()
