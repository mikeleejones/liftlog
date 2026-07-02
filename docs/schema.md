# Workout Tracker — Data Model (Step 4)

Storage: SQLite, single file, server-side on ultra.cc. All weights stored
canonically in kg as REAL. All timestamps stored as ISO 8601 UTC strings.
IDs are INTEGER PRIMARY KEY (SQLite rowid aliases) — no UUIDs needed for a
single-user, single-database app.

---

## Tables

### exercise
The library. One row per distinct movement, created via import or on-the-fly
substitution. Never deleted if it has history (soft-flag instead).

```sql
CREATE TABLE exercise (
    id               INTEGER PRIMARY KEY,
    name             TEXT NOT NULL UNIQUE COLLATE NOCASE,
    cue              TEXT NOT NULL DEFAULT '',
    youtube_query    TEXT NOT NULL DEFAULT '',      -- e.g. 'romanian deadlift form'
    movement_pattern TEXT NOT NULL,                 -- see enum below
    muscle_group     TEXT NOT NULL,                 -- see enum below
    display_unit     TEXT NOT NULL DEFAULT 'kg'
                     CHECK (display_unit IN ('kg','lbs')),
    increment_kg     REAL NOT NULL DEFAULT 2.5,     -- progression step, canonical kg
    is_archived      INTEGER NOT NULL DEFAULT 0,    -- hidden from pickers, history kept
    created_at       TEXT NOT NULL
);
```

`movement_pattern` enum (app-enforced): `horizontal_pull`, `vertical_pull`,
`hinge`, `squat`, `horizontal_push`, `vertical_push`, `isolation`, `core`.

`muscle_group` enum (app-enforced): `back`, `chest`, `shoulders`, `legs`,
`glutes`, `arms`, `core`.

Substitution ranking uses: same `movement_pattern` first, then same
`muscle_group`, tie-broken by "has prior set_log history" then recency.

### routine
```sql
CREATE TABLE routine (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,       -- 'Mon - Hinge + Horizontal'
    position    INTEGER NOT NULL DEFAULT 0, -- display order on Routines screen
    is_archived INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL               -- bumped on re-import (dedupe by name = replace)
);
```

### routine_exercise
The prescription: what a routine asks for. Replaced wholesale when a routine
is re-imported; history is unaffected because history hangs off `exercise`,
not off this table.

```sql
CREATE TABLE routine_exercise (
    id            INTEGER PRIMARY KEY,
    routine_id    INTEGER NOT NULL REFERENCES routine(id) ON DELETE CASCADE,
    exercise_id   INTEGER NOT NULL REFERENCES exercise(id),
    position      INTEGER NOT NULL,          -- order within the routine
    target_sets   INTEGER NOT NULL,
    rep_min       INTEGER NOT NULL,
    rep_max       INTEGER NOT NULL,
    rest_seconds  INTEGER NOT NULL DEFAULT 90,
    is_primary    INTEGER NOT NULL DEFAULT 0 -- triggers warmup ramp suggestion
);
```

### workout
A performed session.

```sql
CREATE TABLE workout (
    id           INTEGER PRIMARY KEY,
    routine_id   INTEGER REFERENCES routine(id),  -- nullable: ad-hoc session
    started_at   TEXT NOT NULL,
    finished_at  TEXT,                            -- NULL = in progress / abandoned
    is_deload    INTEGER NOT NULL DEFAULT 0,      -- excluded from stall detection
    note         TEXT NOT NULL DEFAULT ''
);
```

Abandoned-session rule: a workout with `finished_at IS NULL` older than 12h
is shown as "incomplete" and its sets still count in exercise history, but
the session doesn't count toward weekly compliance.

### set_log
The atomic record. Everything downstream (history, charts, progression,
volume) is computed from here.

```sql
CREATE TABLE set_log (
    id          INTEGER PRIMARY KEY,
    workout_id  INTEGER NOT NULL REFERENCES workout(id) ON DELETE CASCADE,
    exercise_id INTEGER NOT NULL REFERENCES exercise(id),
    set_number  INTEGER NOT NULL,               -- 1-based within exercise within workout
    set_type    TEXT NOT NULL DEFAULT 'normal'
                CHECK (set_type IN ('normal','warmup','failure')),
    weight_kg   REAL NOT NULL,                  -- canonical, always kg
    reps        INTEGER NOT NULL,
    was_suggested INTEGER NOT NULL DEFAULT 0,   -- 1 = accepted via 'did as suggested'
    logged_at   TEXT NOT NULL
);
CREATE INDEX idx_setlog_exercise ON set_log(exercise_id, logged_at);
CREATE INDEX idx_setlog_workout  ON set_log(workout_id);
```

`was_suggested` exists for honesty auditing: if months of sets are 100%
one-tap accepts, that's a signal (to you, via the Progress screen) that
logging may have gone lazy.

### substitution
Records a mid-workout swap so the progression engine knows the planned
exercise was neither done nor stalled, and so frequently-subbed pairs can
be surfaced later ("you swap upright rows 50% of the time — replace it?").

```sql
CREATE TABLE substitution (
    id                   INTEGER PRIMARY KEY,
    workout_id           INTEGER NOT NULL REFERENCES workout(id) ON DELETE CASCADE,
    planned_exercise_id  INTEGER NOT NULL REFERENCES exercise(id),
    actual_exercise_id   INTEGER,               -- NULL = skipped outright
    reason               TEXT NOT NULL DEFAULT ''  -- optional, one-tap tags later
);
```

### program_state
Single-row table for program-level counters. Deliberately not derived on the
fly so that "defer deload" is a stored decision, not a recomputation.

```sql
CREATE TABLE program_state (
    id                     INTEGER PRIMARY KEY CHECK (id = 1),
    completed_weeks        INTEGER NOT NULL DEFAULT 0,  -- weeks with 3 finished sessions
    weeks_since_deload     INTEGER NOT NULL DEFAULT 0,
    deload_deferred_until  TEXT,                        -- NULL = not deferred
    week_anchor            TEXT NOT NULL                -- date the current week started
);
```

Week completion job (runs on each app load): if `week_anchor` + 7 days has
passed, count finished non-deload workouts in that window; if >= 3, increment
both counters; roll `week_anchor` forward. `weeks_since_deload >= 3` triggers
the deload banner for the next week (making deload every 4th completed week).

---

## Derived values (computed, never stored)

- **Progression suggestion** per exercise: look at working sets (`set_type =
  'normal'`) from the most recent non-deload workout containing that exercise.
  If all sets hit `rep_max` at the same weight -> suggest `weight + increment_kg`
  (rounded to loadable increment in `display_unit`). Else -> same weight.
- **Stall**: 3 consecutive non-deload workouts of an exercise at the same
  weight with no total-rep improvement -> suggest 10% reset. Skips and
  substitutions do not advance the stall counter.
- **Warmup ramp** (primary exercises): from working weight W ->
  `empty bar x 10`, `0.5W x 6`, `0.75W x 3`, rounded to loadable increments.
  Logged as `set_type = 'warmup'`; never feeds progression or stall logic.
- **Volume, PRs, charts**: straight aggregation over `set_log`.

## Unit handling rule

Store kg. Render and step in `exercise.display_unit`: stepper = 2.5 kg or
5 lbs; suggestions round to nearest loadable increment in display unit; the
rounded value converts back to kg for storage. Tapping the unit chip on the
Active Workout screen updates `exercise.display_unit` persistently.

## Claude import format (v1)

```json
{
  "version": 1,
  "routines": [
    {
      "name": "Mon - Hinge + Horizontal",
      "exercises": [
        {
          "name": "Romanian Deadlift",
          "cue": "Hinge at hips, soft knees, neutral spine.",
          "youtube_query": "romanian deadlift form",
          "movement_pattern": "hinge",
          "muscle_group": "legs",
          "sets": 3, "rep_min": 8, "rep_max": 10,
          "rest_seconds": 120,
          "increment_kg": 2.5,
          "is_primary": true
        }
      ]
    }
  ]
}
```

Import semantics: routine matched by name -> replace its routine_exercise
rows; exercise matched by name (case-insensitive) -> update cue/query/tags,
never touch history; unknown exercise -> create. Full-database export is the
same shape plus `workouts`, `set_logs`, `substitutions`, `program_state`.

## Non-goals encoded in this schema

No users table (single user; the shared secret lives in server config, not
the database). No exercise media storage (YouTube queries only). No
supersets, no body measurements, no per-set RPE — all addable later without
breaking this schema, which is the test that scope is right.
