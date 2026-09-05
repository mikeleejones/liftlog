# LiftLog API Contract

This is the binding HTTP API contract for the React frontend and FastAPI
backend. It is introduced by v0.6's frontend/backend migration (CLAUDE.md
decision #15). Implementations must update this document in the same change
as an API addition or behavioral change.

## Conventions

- All application endpoints are rooted at `/api/*` and return JSON, except
  file downloads (`application/json` backup/program exports and
  `application/vnd.garmin.tcx+xml` TCX exports).
- Browser requests use the same-origin `liftlog_auth` HttpOnly cookie. The
  frontend sends `credentials: 'include'` for every request.
- Read-only automation endpoints may also accept `Authorization: Bearer
  <token>` where explicitly stated. They never accept an automation token for
  a browser/session-only action.
- Timestamps are UTC ISO 8601 strings. Weights are canonical kilograms;
  display-unit conversion is a frontend presentation concern unless an
  endpoint explicitly says otherwise.
- Success responses use the natural 2xx status code. Validation errors return
  `422`; missing resources return `404`; unauthenticated requests return
  `401`; forbidden token scope returns `403`.
- Error responses are JSON objects with a factual `detail` string. Never
  expose secrets, SQLite errors, or Anthropic API responses.

## Migration status

The existing server-rendered routes are the behavioral reference until their
corresponding API group is implemented and validated on
`liftlog-staging.mrradcl.com`. The groups below are placeholders for Phase 2;
each gains exact request/response schemas before implementation.

| Group | Planned endpoints | Status |
|---|---|---|
| Auth | `POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/auth/session` | Implemented and staging-verified |
| Home / progress | `GET /api/home` | Implemented and staging-verified |
| Programs / routines | list, preview, activate, archive/reactivate, delete | Implemented and staging-verified (mutations signed off) |
| Exercises | list, detail/history/chart, reset progress | Implemented and staging-verified (reset-progress signed off) |
| Workouts / sets | start, resume/state, log/edit set, substitutions, finish, discard, summary, TCX | Implemented and staging-verified (lifecycle signed off; state/summary reads verified) |
| AI substitutions | cached suggestion and selection actions | Implemented and staging-verified (documented under Workouts / Sets) |
| Profile / export | configuration, tokens, exports, deload defer | Implemented and staging-verified |
| AI program builder | draft, chat turn, preview/apply/discard | Implemented; staging verification pending |
| Automation tokens | `GET /api/latest-workout` (done); create/list/revoke token (new, see Profile / Settings) | Implemented; staging verification pending |

## Compatibility rule

The React frontend must not call an undocumented endpoint. When replacing a
server-rendered flow, preserve its current validation, auth, and mutation
semantics unless `CLAUDE.md` and this contract are amended first.

## Auth

Browser authentication remains one shared secret and one HttpOnly cookie. API
tokens are deliberately not accepted by these endpoints.

### `POST /api/auth/login`

Request body:

```json
{"secret": "the shared browser secret"}
```

Success: `200 OK`, sets the existing `liftlog_auth` HttpOnly, SameSite=Lax
cookie (one-year max age), and returns:

```json
{"authenticated": true}
```

Failure: `401 Unauthorized` with `{"detail":"Invalid secret"}`. Invalid
credentials never set or alter a cookie. Malformed/missing JSON follows
FastAPI's standard `422` validation response.

### `POST /api/auth/logout`

No body. Returns `204 No Content` and clears `liftlog_auth`. It is idempotent:
calling it with no session cookie still returns `204`.

### `GET /api/auth/session`

Returns `200 OK` for both states, avoiding an error-driven startup path in the
SPA:

```json
{"authenticated": true}
```

or:

```json
{"authenticated": false}
```

## Home / Progress

### `GET /api/home`

Requires the browser cookie; an absent or invalid cookie returns `401` with
`{"detail":"Authentication required"}`. API tokens are not accepted.

Returns the complete Home dashboard data in canonical units. The server runs
the existing week-completion rollover before querying, exactly as `GET /` does,
so `program.week`, deload state, and weekly session counts match the
server-rendered Home on the same request.

```json
{
  "program": {"id": 1, "name": "Hypertrophy Block A", "weeks_count": 2, "week": 1},
  "sessions": {"completed": 1, "required": 3},
  "deload": {"active": false, "deferred": false, "weeks_to_next": 2},
  "in_progress": null,
  "calendar": [[{"date": "2026-08-10", "day_letter": "M", "day_number": 10, "accent": "blue", "is_today": false, "is_future": false}]],
  "volume": {"points": [{"value": 4820, "is_pr": true, "is_deload": false, "label": "08-12"}], "latest_kg": 4820, "latest_is_pr": true},
  "progression": {"ready": 2, "stalled": 0, "completed_weeks": 3, "weeks_since_deload": 1, "lifts": []},
  "audit": {"suggested_pct": 82, "working_sets": 44}
}
```

`program` and `in_progress` are `null` when none exists. `volume.points` is
oldest-first and excludes completed sessions with no weight/reps volume;
`latest_kg` is `null` when it is empty. Lift rows retain Home's existing
program order and include `id`, `name`, formatted `last`/`next`/`suggest`,
and `kind` (`progress`, `stall`, or neutral behavior) for the frontend's
existing progression-chip language. `audit.suggested_pct` is `null` until at
least one normal working set exists.

## Programs / Routines

All endpoints in this group require the browser cookie. An absent or invalid
cookie returns `401`; automation tokens are not accepted. Missing IDs return
`404` with either `{"detail":"Program not found"}` or
`{"detail":"Routine not found"}`.

### `GET /api/routines?view=active|archived`

Returns the Workout tab's routines, grouped by program then week:

```json
{
  "view": "active",
  "programs": [{
    "id": 1,
    "name": "Hypertrophy Block A",
    "weeks_count": 2,
    "is_active": true,
    "current_week": 1,
    "weeks": [{"number": 1, "routines": [{"id": 4, "name": "Mon - Hinge", "exercise_count": 5, "accent": "blue"}]}]
  }],
  "standalone": [],
  "quick_start": [],
  "deload_active": false
}
```

`view` defaults to `active`; any other value returns `422`. `quick_start` and
`deload_active` appear only for `active`; each quick-start row adds
`progress_ready` to the normal routine fields. The endpoint performs the
existing weekly rollover before querying, the same as the HTML Workout tab.

### `GET /api/routines/{routine_id}/preview`

Returns a read-only routine and ordered prescription. It never creates a
workout or starts a timer:

```json
{
  "routine": {"id": 4, "program_id": 1, "name": "Mon - Hinge", "week_number": 1, "position": 0, "is_archived": false, "accent": "blue"},
  "exercises": [{"exercise_id": 8, "name": "Romanian Deadlift", "cue": "...", "exercise_type": "weight_reps", "is_primary": true, "target_sets": 3, "rep_min": 8, "rep_max": 10, "rest_seconds": 120, "target": "3 × 8–10 · rest 120s"}]
}
```

### Mutations

`POST /api/programs/{program_id}/activate` activates a stored program and
resets its `program_week` to 1 if it was inactive. It returns
`{"id":1,"is_active":true,"program_week":1}`. Repeating it for the active
program is safe and leaves the current week unchanged.

`POST /api/routines/{routine_id}/archive` and
`POST /api/routines/{routine_id}/reactivate` are reversible, returning
`{"id":4,"is_archived":true}` or `false`. They preserve the routine's
prescription and all history.

`DELETE /api/routines/{routine_id}` returns `204 No Content`. It deletes the
routine and its prescription, but logged workouts survive as ad-hoc sessions
(`workout.routine_id` becomes NULL) and no set history is deleted.

## Exercises

All endpoints require the browser cookie; unknown exercise IDs return `404`
with `{"detail":"Exercise not found"}`.

`GET /api/exercises?q=<name>` returns
`{"query":"...","exercises":[...]}`. It searches unarchived library
exercises by literal, case-insensitive name match and returns the full stored
exercise fields in name order.

`GET /api/exercises/{exercise_id}` returns `exercise`, its display `unit`,
oldest-first per-workout `history`, chart-ready `chart_points`, and `editable`.
History and chart data deliberately ignore `progress_reset_at`, preserving the
full historical record. Set metrics remain canonical kg/metres/seconds.

`POST /api/exercises/{exercise_id}/reset-progress` soft-resets suggestions and
stall detection only. It returns `{"id":1,"progress_reset_at":"..."}`;
no workout or set history is changed.

## Workouts / Sets

All JSON endpoints in this group require the browser cookie; automation tokens
are not accepted. The lifecycle and state endpoints return `401` or `404` with
the standard `{"detail":"..."}` shape. The six pre-existing set and
substitution endpoints below retain their existing `{"error":"..."}` failure
shape until the server-rendered frontend is retired; their success schemas are
frozen because that live frontend consumes them directly.

### Lifecycle and state

`POST /api/workouts` accepts `{"routine_id":4}` and creates an open session,
including the existing deload determination:

```json
{"id":12,"started_at":"2026-08-27T15:00:00Z","is_deload":false}
```

`POST /api/workouts/{workout_id}/finish` returns
`{"id":12,"finished_at":"2026-08-27T16:03:00Z"}`. It returns `409` if the
session is already finished. `POST /api/workouts/{workout_id}/discard` returns
`204 No Content` and deletes only an open session (including its sets); it also
returns `409` for a finished session.

`GET /api/workouts/{workout_id}` returns the full current session state for
both open and finished workouts. The frontend selects the Active Workout or
Finish Summary view from `workout.finished_at`; this endpoint never redirects.
Set metrics remain canonical kg/metres/seconds.

```json
{
  "workout": {"id":12,"started_at":"2026-08-27T15:00:00Z","finished_at":null,"is_deload":false,"routine_name":"Mon - Hinge","accent":"blue"},
  "exercises": [{"exercise_id":8,"planned_exercise_id":8,"name":"Romanian Deadlift","cue":"...","youtube_query":"...","exercise_type":"weight_reps","display_unit":"kg","increment_kg":2.5,"target_sets":3,"rep_min":8,"rep_max":10,"rest_seconds":120,"is_primary":true,"suggest_weight_kg":80,"suggest_reps":8,"suggest_duration_seconds":null,"suggest_distance_m":null,"suggest_kind":"same","warmups":[],"warmups_logged":0,"skipped":false,"sets":[],"last":null}]
}
```

`GET /api/workouts/{workout_id}/summary` returns the Finish Summary aggregate
for either an open or finished session. `totals.volume_kg` is the sum of every
normal set with both weight and reps. Each set retains raw metrics plus the
existing display text and its exercise's display-unit suffix.

```json
{
  "workout": {"id":12,"started_at":"2026-08-27T15:00:00Z","finished_at":"2026-08-27T16:03:00Z","routine_name":"Mon - Hinge","accent":"blue","duration_seconds":3780},
  "totals": {"sets":3,"volume_kg":2400},
  "exercises": [{"exercise_id":8,"name":"Romanian Deadlift","unit":"kg","sets":[{"weight_kg":80,"reps":10,"duration_seconds":null,"distance_m":null,"text":"80 × 10"}]}]
}
```

### Logged sets and display units

The following pre-existing endpoints are stable compatibility contracts for the
server-rendered Active Workout page and are also available to the React
frontend.

`POST /api/workout/{workout_id}/set` logs one set for an open workout. Its body
includes `exercise_id`, `set_number`, `set_type` (`normal` or `warmup`),
`was_suggested`, and all four metric keys (`weight_kg`, `reps`,
`duration_seconds`, `distance_m`), using `null` for axes the exercise type does
not use. It returns `{"ok":true,"id":34}`. An unavailable or finished workout
returns `409`; an invalid `set_type` returns `400`.

`POST /api/set/{set_id}` corrects a logged set, including one in a finished
workout. Its body contains all four metric keys. The server clears axes not
used by the logged exercise and changes `was_suggested` to false. It returns
the corrected metrics, for example:

```json
{"ok":true,"weight_kg":80,"reps":10,"duration_seconds":null,"distance_m":null}
```

`POST /api/exercise/{exercise_id}/unit` persists
`{"unit":"kg"|"lbs"|"km"|"mi"}` and returns `{"ok":true}`. Invalid units
return `400`.

### Substitutions

`GET /api/workout/{workout_id}/swap/{planned_exercise_id}?current=<exercise_id>`
returns previous actual exercises for that routine slot, excluding `current`:

```json
{"previously_used":[{"id":17,"name":"Dumbbell RDL","last_used":"2026-08-20T15:00:00Z"}]}
```

`POST /api/workout/{workout_id}/ai-suggestions/{planned_exercise_id}` accepts
an empty JSON object. A successful response is
`{"state":"ok","suggestions":[...]}` where each suggestion has `cache_id`,
`name`, `reason`, `movement_pattern`, `muscle_group`, `equipment`,
`exercise_type`, and `youtube_query`. The existing daily guardrail responds
with `{"state":"limit","message":"..."}`; an unavailable suggestion call
responds with `{"state":"error","message":"..."}`.

`POST /api/workout/{workout_id}/substitute` requires `planned_exercise_id` and
one of: `{"skip":true}`, `{"actual_exercise_id":17,"permanent":false}`, or
`{"cache_id":9,"permanent":true}`. A skip returns `{"skipped":true}`.
Otherwise it returns `{"exercise":{...}}`, with the full per-exercise shape
from `GET /api/workouts/{workout_id}` so the client can replace that one slot
without reloading the entire session. A permanent replacement also repoints
the corresponding routine prescription.

### TCX export

`GET /workout/{workout_id}/export.tcx` remains a cookie-authenticated file
download outside `/api/*`. It exports finished workouts only as
`application/vnd.garmin.tcx+xml`; the browser receives an attachment named
`liftlog-workout-{id}-{date}.tcx`. The existing server-rendered redirect
behavior for an unknown or unfinished workout is retained.

## Profile / Settings

All endpoints in this group require the browser cookie; automation tokens are
not accepted (token management is itself one of these endpoints).

### Settings data

`GET /api/settings` returns the Profile tab's dashboard data. `bodyweight_kg`
is canonical kilograms or `null` when unset; token rows never include the
token secret itself (that's shown exactly once, at creation).

```json
{
  "deload": {"active": false, "deferred": false},
  "weeks_since_deload": 1,
  "completed_weeks": 3,
  "counts": {"exercises": 42, "workouts": 30, "sets": 640},
  "objective": "HYROX prep",
  "bodyweight_kg": 82.5,
  "tokens": [{"id": 1, "name": "Shortcuts", "created_at": "2026-08-01T00:00:00Z", "last_used_at": "2026-08-27T12:00:00Z"}]
}
```

### Automation tokens

`POST /api/settings/tokens` accepts `{"name":"..."}` (defaults to "unnamed
token" when blank) and returns the new token's secret exactly once:

```json
{"id": 2, "name": "Shortcuts", "token": "<opaque url-safe secret>", "created_at": "2026-08-27T15:00:00Z"}
```

`DELETE /api/settings/tokens/{token_id}` returns `204 No Content`, or `404`
with `{"detail":"Token not found"}`. Revoking a token immediately invalidates
it for `token_or_cookie_authed` consumers such as `GET /api/latest-workout`.

### Objective and bodyweight

`POST /api/settings/objective` accepts `{"objective":"..."}` (blank clears it)
and returns `{"objective":"..."}`. `POST /api/settings/bodyweight` accepts
`{"bodyweight_kg": 82.5}` or `{"bodyweight_kg": null}`; non-positive values are
also treated as clearing it (matching the existing bodyweight-driven TCX
calorie estimate, which falls back to 0 rather than a fabricated number). It
returns `{"bodyweight_kg": 82.5}` or `{"bodyweight_kg": null}`.

### AI program builder

The Workout tab owns program creation. `GET /api/programs/builder` returns the
persisted single-user draft as `{"messages":[{"role":"user"|"assistant",
"content":"..."}],"plan":<plan|null>}`. The plan is recomputed from the
validated internal v2 program object.

`POST /api/programs/builder/message` accepts `{"content":"..."}`. It appends
one user message, calls Claude Haiku with the saved transcript, exercise
library, and active-program context, then returns `{"state":"ok","message":
"...","plan":<plan|null>}`. A candidate is never persisted as a real program
until applied. The shared daily AI guardrail returns `{"state":"limit",
"message":"..."}`; unavailable or malformed AI responses return
`{"state":"error","message":"..."}`.

`POST /api/programs/builder/apply` validates the stored candidate again, then
uses `importer.apply_import` to create or replace/activate its program,
replace same-name routines, archive dropped routines, and case-insensitively
reuse or create exercises. It returns `{"result":<plan>}` and clears the
draft. `POST /api/programs/builder/discard` clears the draft and returns
`{"ok":true}`.

### Deload defer

`POST /api/deload/defer` takes no body and returns
`{"deload_deferred_until": "2026-09-03T00:00:00Z"}`, pushing the deload one
week out exactly like the existing HTML control.

### Exports (unchanged, outside `/api/*`)

`GET /export` (full backup) and `GET /export/program` (active program only,
the internal v2 builder shape) remain cookie-authenticated JSON file downloads
outside `/api/*`, per this document's file-download exception — consistent
with the TCX export above. They are not part of the automation-token surface.
