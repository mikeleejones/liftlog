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
    exercise_type    TEXT NOT NULL DEFAULT 'weight_reps'
                     CHECK (exercise_type IN
                       ('weight_reps','reps_only','duration','duration_weight',
                        'distance','distance_weight','none')),
    display_unit     TEXT NOT NULL DEFAULT 'kg'
                     CHECK (display_unit IN ('kg','lbs','km','mi')),
    increment_kg     REAL NOT NULL DEFAULT 2.5,     -- progression step in kg; 0 = bodyweight / no-load (no load progression or stall reset)
    is_archived      INTEGER NOT NULL DEFAULT 0,    -- hidden from pickers, history kept
    progress_reset_at TEXT,                          -- NULL = never reset; soft reset marker (see below)
    equipment        TEXT,                           -- nullable; free text (e.g. 'barbell', 'cable'). AI-created exercises always populate this; existing exercises pick it up on next JSON re-import (import updates it on name-match, like cue/youtube_query). Sent to Haiku as context for AI substitution suggestions.
    created_at       TEXT NOT NULL
);
```

`exercise_type` decides which `set_log` columns are populated and which input
control Active Workout shows. Every exercise in the pre-v0.5 database migrates
to the `weight_reps` default, so the existing program is unchanged.

| `exercise_type`   | set_log fields used            | `display_unit`        | example                    |
|-------------------|--------------------------------|-----------------------|----------------------------|
| `weight_reps`     | `weight_kg` + `reps`           | `kg`/`lbs`            | barbell bench press        |
| `reps_only`       | `reps`                         | none (ignored)        | bodyweight push-ups, cat-cow |
| `duration`        | `duration_seconds`             | none (mm:ss)          | plank, dead hang           |
| `duration_weight` | `duration_seconds` + `weight_kg` | `kg`/`lbs` (weight) | weighted plank, farmer hold |
| `distance`        | `distance_m`                   | `km`/`mi`             | run interval, row erg      |
| `distance_weight` | `distance_m` + `weight_kg`     | `km`/`mi` (distance)  | loaded carry (future HYROX) |
| `none`            | nothing (completion record)    | none                  | doorway chest stretch      |

`display_unit` is one field, so for the two-axis loaded types it names the
*primary* axis unit: `duration_weight` uses it for the weight (`kg`/`lbs`;
duration always renders mm:ss with no toggle), while `distance_weight` uses it
for the distance (`km`/`mi`; its weight axis is stored/shown in kg with no
toggle, since there is no second unit field — schema-ready types with no current
data). `reps_only`, `duration`, and `none` have no unit at all.

`movement_pattern` enum (app-enforced): `horizontal_pull`, `vertical_pull`,
`hinge`, `squat`, `horizontal_push`, `vertical_push`, `isolation`, `core`.

`muscle_group` enum (app-enforced): `back`, `chest`, `shoulders`, `legs`,
`glutes`, `arms`, `core`.

The swap sheet surfaces `substitution` history ("previously used") plus
AI-suggested alternatives (Claude Haiku, cached per exercise in
`ai_suggestion_cache`) — there is no rule-based movement_pattern/muscle_group
ranking (superseded per CLAUDE.md decision log item 5 / BACKLOG item 4).

### program
A named set of routines spanning one or more weeks, repeated on a weekly
cycle. Several programs may be stored; exactly one is active at a time
(app-enforced). The active program's current week (see `program_state`)
drives Home and weekly compliance.

```sql
CREATE TABLE program (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    weeks_count INTEGER NOT NULL DEFAULT 1, -- length of the cycle in weeks
    is_active   INTEGER NOT NULL DEFAULT 0, -- at most one row = 1
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL               -- bumped on re-import
);
```

### routine
```sql
CREATE TABLE routine (
    id          INTEGER PRIMARY KEY,
    program_id  INTEGER REFERENCES program(id), -- nullable: standalone routine
    name        TEXT NOT NULL,                  -- 'Mon - Hinge + Horizontal'
    week_number INTEGER NOT NULL DEFAULT 1,     -- 1..program.weeks_count
    position    INTEGER NOT NULL DEFAULT 0,     -- display order within program
    is_archived INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,                  -- bumped on re-import
    UNIQUE (program_id, name)                   -- dedupe scope is the program
);
```

Routines dropped by a program re-import are archived (`is_archived = 1`),
never deleted — `workout.routine_id` may reference them.

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
    routine_id   INTEGER REFERENCES routine(id) ON DELETE SET NULL,  -- nullable: ad-hoc session
    started_at   TEXT NOT NULL,
    finished_at  TEXT,                            -- NULL = in progress / abandoned
    is_deload    INTEGER NOT NULL DEFAULT 0,      -- excluded from stall detection
    note         TEXT NOT NULL DEFAULT ''
);
```

Abandoned-session rule: a workout with `finished_at IS NULL` older than 12h
is shown as "incomplete" and its sets still count in exercise history, but
the session doesn't count toward weekly compliance.

Deleting a routine: `routine_id` uses `ON DELETE SET NULL` so a routine can
be deleted even when it has logged workouts. Those workouts survive with
`routine_id = NULL` and render as ad-hoc sessions — the same as any unplanned
workout — so no history is ever lost by deleting a routine. (The routine's
`routine_exercise` rows cascade-delete; `set_log` history hangs off
`exercise`, not the routine, so it is untouched.)

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
    weight_kg   REAL,                           -- canonical kg; NULL unless a weight-bearing type
    reps        INTEGER,                        -- NULL unless a rep-counted type
    duration_seconds REAL,                      -- NULL unless duration / duration_weight
    distance_m  REAL,                           -- canonical metres; NULL unless distance / distance_weight
    was_suggested INTEGER NOT NULL DEFAULT 0,   -- 1 = accepted via 'did as suggested'
    logged_at   TEXT NOT NULL
);
CREATE INDEX idx_setlog_exercise ON set_log(exercise_id, logged_at);
CREATE INDEX idx_setlog_workout  ON set_log(workout_id);
```

`weight_kg` and `reps` are nullable (they were `NOT NULL` before v0.5): which
metric columns a row populates is driven entirely by the exercise's
`exercise_type` (see the table above). A `none`-type set is a pure completion
record — every metric column NULL. Distances are stored canonically in metres,
converted to/from the `km`/`mi` `display_unit` the same way weights convert
between kg and the display unit.

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
    completed_weeks        INTEGER NOT NULL DEFAULT 0,  -- weeks with all prescribed sessions finished
    weeks_since_deload     INTEGER NOT NULL DEFAULT 0,
    deload_deferred_until  TEXT,                        -- NULL = not deferred
    week_anchor            TEXT NOT NULL,               -- date the current week started
    program_week           INTEGER NOT NULL DEFAULT 1,  -- current week within the active program's cycle
    objective              TEXT                         -- nullable; free text describing the program's goal (e.g. "HYROX prep, back-friendly, full-body balanced, progressive overload"). Set via Settings. Sent as context on every Haiku call so AI substitution suggestions stay aligned with intent, not just equipment/pattern matching.
);
```

Week completion job (runs on each app load): if `week_anchor` + 7 days has
passed, count finished non-deload workouts in that window. The required count
is the number of unarchived routines in the active program's current week
(`program_week`), or 3 if there is no active program. If met: increment both
counters and advance `program_week` (wrapping at `weeks_count`); an
incomplete week repeats its `program_week`. Roll `week_anchor` forward either
way. `weeks_since_deload >= 3` triggers the deload banner for the next week
(making deload every 4th completed week). Activating a different program
resets `program_week` to 1.

### ai_suggestion_cache
Per-exercise cache of AI substitution suggestions (BACKLOG item 4). Never
expires in v1 — a good suggestion from months ago is still there next time the
exercise needs a swap. One row per cached suggestion.

```sql
CREATE TABLE ai_suggestion_cache (
    id                  INTEGER PRIMARY KEY,
    planned_exercise_id INTEGER NOT NULL REFERENCES exercise(id),
    suggestion_json     TEXT NOT NULL,   -- full validated suggestion object (name, reason, movement_pattern, muscle_group, equipment, exercise_type, cue, youtube_query) as a JSON string
    created_at          TEXT NOT NULL,
    shown_at            TEXT             -- NULL until displayed to the user once, then a timestamp
);
```

`shown_at` is what lets a repeat swap attempt on the same exercise show
cached-but-unseen suggestions instantly instead of making a new API call.
Every name ever cached for an exercise (shown or not) is sent to Haiku as an
exclusion list on each fresh call, so no true duplicate is ever served across
the exercise's lifetime.

### ai_call_log
One row per ACTUAL Haiku API call — not one row per suggestion, and never
incremented on a cache hit. Backs the guardrail of at most 100 real calls per
rolling 24 hours (`can_make_ai_call()` in `db.py`).

```sql
CREATE TABLE ai_call_log (
    id         INTEGER PRIMARY KEY,
    created_at TEXT NOT NULL
);
```

### api_token
Read-only automation credentials (BACKLOG item 7) for external tools — an iPhone
Shortcut, a script — to read data without holding the browser login secret. Not a
multi-user account system: still single-user, no passwords, no signup. Token values
are long random strings (`secrets.token_urlsafe`) shown exactly once at creation and
never displayed again; revoke deletes the row.

```sql
CREATE TABLE api_token (
    id           INTEGER PRIMARY KEY,
    name         TEXT NOT NULL,       -- e.g. "iPhone Shortcuts"
    token        TEXT NOT NULL UNIQUE,-- random, shown once at creation
    scope        TEXT NOT NULL DEFAULT 'read_only'
                 CHECK (scope IN ('read_only')),
    created_at   TEXT NOT NULL,
    last_used_at TEXT                 -- NULL until first successful use
);
```

v1 scope is `read_only` only. An endpoint that opts into token auth
(`token_or_cookie_authed` in main.py) accepts EITHER the browser cookie OR a valid
`Authorization: Bearer <token>` header matching a row here, bumping `last_used_at` on
a token match. The browser cookie login flow is unchanged — this is purely additive.
Currently only `GET /api/latest-workout` (BACKLOG item 8) opts in; it returns the most
recently finished workout (`id`, `date`, `duration_seconds`, `routine_name`,
`is_deload`, `total_volume_kg` over normal `weight_reps` sets) as JSON. The program-only
export (`GET /export/program`, BACKLOG item 9) emits the active program in the exact v2
import shape (no history) and stays browser-only (cookie), not part of the token surface.

---

## Derived values (computed, never stored)

**Progress reset (`exercise.progress_reset_at`)**: a soft, non-destructive
reset. When set, the progression-suggestion and stall-detection queries only
consider sets with `set_log.logged_at > progress_reset_at` — the exercise
behaves as if it had no prior sets for suggestion purposes, so weight and rep
suggestions start fresh from the next session. No `set_log` rows are deleted.
When it is `NULL` (the default, and the case for every exercise today), the
queries scan all history unchanged. Charts, Exercise Detail history, PRs, and
volume ignore this field entirely — full history is always visible regardless
of a reset. Resetting again just moves the marker forward. Set to `now()` (UTC)
by the "Reset Progress" action on Exercise Detail.

- **Progression suggestion** per exercise: look at working sets (`set_type =
  'normal'`) from the most recent non-deload workout containing that exercise
  (respecting `progress_reset_at`, above). Behaviour depends on `exercise_type`:
  - `weight_reps`: if all sets hit `rep_max` at the same weight -> suggest
    `weight + increment_kg` (rounded to loadable increment in `display_unit`).
    Else -> same weight. When `increment_kg` is 0 (bodyweight / no-load) there is
    no weight to add: the suggestion stays put and neither progression nor the
    stall reset applies. Import accepts `increment_kg: 0`.
  - `reps_only` / `duration` / `distance` (single-axis): the routine's
    `rep_min`/`rep_max` are read as the target range for that type's own metric
    (reps, seconds, or metres). Clear the top across all sets -> bump by one step
    (+1 rep, +5 s, +100 m); otherwise nudge up toward the top. No weight axis.
  - `duration_weight` / `distance_weight`: pre-fill from the last session only —
    **no** auto-progression in this pass (no exercises of these types exist yet;
    schema-ready for future HYROX loaded carries).
  - `none`: never enters progression — a pure completion record.
- **Stall**: 3 consecutive non-deload workouts of an exercise at the same
  primary value with no total-metric improvement -> flag. For `weight_reps` this
  suggests a 10% weight reset; for the single-axis types there is no weight axis
  to reset, so the value is simply repeated with a stall flag. `duration_weight`,
  `distance_weight`, and `none` never stall. Skips and substitutions do not
  advance the stall counter. Only sessions after `progress_reset_at` (when set)
  are counted.
- **Warmup ramp** (primary exercises): from working weight W ->
  `empty bar x 10`, `0.5W x 6`, `0.75W x 3`, rounded to loadable increments.
  Logged as `set_type = 'warmup'`; never feeds progression or stall logic.
- **Volume, PRs, charts**: straight aggregation over `set_log`.

## Unit handling rule

Store kg. Render and step in `exercise.display_unit`: stepper = 2.5 kg or
5 lbs; suggestions round to nearest loadable increment in display unit; the
rounded value converts back to kg for storage. Tapping the unit chip on the
Active Workout screen updates `exercise.display_unit` persistently.

## Claude import format

### v2 (current) — program envelope

```json
{
  "version": 2,
  "program": {
    "name": "Hypertrophy Block A",
    "weeks": 2,
    "routines": [
      {
        "name": "Mon - Hinge + Horizontal",
        "week": 1,
        "exercises": [
          {
            "name": "Romanian Deadlift",
            "cue": "Hinge at hips, soft knees, neutral spine.",
            "youtube_query": "romanian deadlift form",
            "movement_pattern": "hinge",
            "muscle_group": "legs",
            "exercise_type": "weight_reps",
            "equipment": "barbell",
            "sets": 3, "rep_min": 8, "rep_max": 10,
            "rest_seconds": 120,
            "increment_kg": 2.5,
            "is_primary": true
          }
        ]
      }
    ]
  }
}
```

`week` is optional (default 1); `weeks` is optional (default: highest `week`
used). `exercise_type` is optional (default `weight_reps`, so programs exported
before v0.5 import unchanged); when present it must be one of the seven enum
values. `display_unit` is also optional per exercise — when omitted, distance
types default to `km` and everything else to `kg`; for the single-axis
`reps_only`/`duration` range types, `rep_min`/`rep_max` carry the target reps /
seconds / metres. Semantics: program matched by name -> replace (routines matched by
name within the program get their routine_exercise rows replaced; routines
absent from the import are archived); unknown program -> create. The imported
program becomes active. Re-importing the already-active program keeps
`program_week` (clamped to the new `weeks`); activating a different program
resets it to 1.

### v1 (still accepted) — bare routines

Same shape without the program envelope: `{"version": 1, "routines": [...]}`.
Routines are upserted into the active program at week 1 (an active program is
created if none exists); nothing is archived.

`equipment` is optional per exercise (nullable free text). It follows the same
update-on-name-match semantics as cue/youtube_query/tags: a matched exercise
has its equipment updated (history untouched); an unknown exercise is created
with the provided equipment, or NULL when omitted.

### Shared exercise semantics

Exercise matched by name (case-insensitive) -> update cue/query/tags/equipment,
never touch history; unknown exercise -> create. Full-database export is the
same shape plus `workouts`, `set_logs`, `substitutions`, `program_state`.

## Non-goals encoded in this schema

No users table (single user; the shared secret lives in server config, not
the database). No exercise media storage (YouTube queries only). No
supersets, no body measurements, no per-set RPE — all addable later without
breaking this schema, which is the test that scope is right.
