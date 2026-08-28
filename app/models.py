"""SQLAlchemy models for LiftLog's SQLite schema.

The v0.6 migration deliberately keeps SQLite's existing physical conventions:
integer primary keys, 0/1 flags, and ISO-8601 timestamps stored as TEXT. The
application still uses SQL text through the compatibility session in `db.py`
while its routes are converted to the JSON API; these models are the schema
authority for Alembic and all new persistence code.
"""

from __future__ import annotations

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, REAL, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Exercise(Base):
    __tablename__ = "exercise"
    __table_args__ = (
        CheckConstraint(
            "exercise_type IN "
            "('weight_reps','reps_only','duration','duration_weight','distance','distance_weight','none')"
        ),
        CheckConstraint("display_unit IN ('kg','lbs','km','mi')"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=True)
    name: Mapped[str] = mapped_column(Text(collation="NOCASE"), unique=True)
    cue: Mapped[str] = mapped_column(Text, default="")
    youtube_query: Mapped[str] = mapped_column(Text, default="")
    movement_pattern: Mapped[str] = mapped_column(Text)
    muscle_group: Mapped[str] = mapped_column(Text)
    exercise_type: Mapped[str] = mapped_column(Text, default="weight_reps")
    display_unit: Mapped[str] = mapped_column(Text, default="kg")
    increment_kg: Mapped[float] = mapped_column(REAL, default=2.5)
    is_archived: Mapped[int] = mapped_column(Integer, default=0)
    progress_reset_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    equipment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(Text)


class Program(Base):
    __tablename__ = "program"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=True)
    name: Mapped[str] = mapped_column(Text, unique=True)
    weeks_count: Mapped[int] = mapped_column(Integer, default=1)
    is_active: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[str] = mapped_column(Text)


class Routine(Base):
    __tablename__ = "routine"
    __table_args__ = (UniqueConstraint("program_id", "name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=True)
    program_id: Mapped[int | None] = mapped_column(ForeignKey("program.id"), nullable=True)
    name: Mapped[str] = mapped_column(Text)
    week_number: Mapped[int] = mapped_column(Integer, default=1)
    position: Mapped[int] = mapped_column(Integer, default=0)
    is_archived: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[str] = mapped_column(Text)


class RoutineExercise(Base):
    __tablename__ = "routine_exercise"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=True)
    routine_id: Mapped[int] = mapped_column(ForeignKey("routine.id", ondelete="CASCADE"))
    exercise_id: Mapped[int] = mapped_column(ForeignKey("exercise.id"))
    position: Mapped[int] = mapped_column(Integer)
    target_sets: Mapped[int] = mapped_column(Integer)
    rep_min: Mapped[int] = mapped_column(Integer)
    rep_max: Mapped[int] = mapped_column(Integer)
    rest_seconds: Mapped[int] = mapped_column(Integer, default=90)
    is_primary: Mapped[int] = mapped_column(Integer, default=0)


class Workout(Base):
    __tablename__ = "workout"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=True)
    routine_id: Mapped[int | None] = mapped_column(ForeignKey("routine.id", ondelete="SET NULL"), nullable=True)
    started_at: Mapped[str] = mapped_column(Text)
    finished_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_deload: Mapped[int] = mapped_column(Integer, default=0)
    note: Mapped[str] = mapped_column(Text, default="")


class SetLog(Base):
    __tablename__ = "set_log"
    __table_args__ = (
        CheckConstraint("set_type IN ('normal','warmup','failure')"),
        Index("idx_setlog_exercise", "exercise_id", "logged_at"),
        Index("idx_setlog_workout", "workout_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=True)
    workout_id: Mapped[int] = mapped_column(ForeignKey("workout.id", ondelete="CASCADE"))
    exercise_id: Mapped[int] = mapped_column(ForeignKey("exercise.id"))
    set_number: Mapped[int] = mapped_column(Integer)
    set_type: Mapped[str] = mapped_column(Text, default="normal")
    weight_kg: Mapped[float | None] = mapped_column(REAL, nullable=True)
    reps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(REAL, nullable=True)
    distance_m: Mapped[float | None] = mapped_column(REAL, nullable=True)
    was_suggested: Mapped[int] = mapped_column(Integer, default=0)
    logged_at: Mapped[str] = mapped_column(Text)


class Substitution(Base):
    __tablename__ = "substitution"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=True)
    workout_id: Mapped[int] = mapped_column(ForeignKey("workout.id", ondelete="CASCADE"))
    planned_exercise_id: Mapped[int] = mapped_column(ForeignKey("exercise.id"))
    actual_exercise_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reason: Mapped[str] = mapped_column(Text, default="")


class ProgramState(Base):
    __tablename__ = "program_state"
    __table_args__ = (CheckConstraint("id = 1"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=True)
    completed_weeks: Mapped[int] = mapped_column(Integer, default=0)
    weeks_since_deload: Mapped[int] = mapped_column(Integer, default=0)
    deload_deferred_until: Mapped[str | None] = mapped_column(Text, nullable=True)
    week_anchor: Mapped[str] = mapped_column(Text)
    program_week: Mapped[int] = mapped_column(Integer, default=1)
    objective: Mapped[str | None] = mapped_column(Text, nullable=True)
    bodyweight_kg: Mapped[float | None] = mapped_column(REAL, nullable=True)


class AiSuggestionCache(Base):
    __tablename__ = "ai_suggestion_cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=True)
    planned_exercise_id: Mapped[int] = mapped_column(ForeignKey("exercise.id"))
    suggestion_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(Text)
    shown_at: Mapped[str | None] = mapped_column(Text, nullable=True)


class AiCallLog(Base):
    __tablename__ = "ai_call_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=True)
    created_at: Mapped[str] = mapped_column(Text)


class ApiToken(Base):
    __tablename__ = "api_token"
    __table_args__ = (CheckConstraint("scope IN ('read_only')"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=True)
    name: Mapped[str] = mapped_column(Text)
    token: Mapped[str] = mapped_column(Text, unique=True)
    scope: Mapped[str] = mapped_column(Text, default="read_only")
    created_at: Mapped[str] = mapped_column(Text)
    last_used_at: Mapped[str | None] = mapped_column(Text, nullable=True)
