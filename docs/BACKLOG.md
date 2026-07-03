# LiftLog — v0.5 Backlog

v0.4 shipped and is live on ultra.cc. This is the next increment. Per
CLAUDE.md's working agreements: work one item at a time, test at the gym
between items, don't build ahead.

---

## 1. Delete a routine (quick — ready to build)

Add delete to the Routines screen (confirm dialog, per design-language.md's
destructive-action red).

**Schema fix required first** (docs/schema.md amendment): `workout.routine_id`
currently has no explicit ON DELETE behavior, which means SQLite will block
deleting a routine that has any logged workouts against it. Change to:

```sql
routine_id INTEGER REFERENCES routine(id) ON DELETE SET NULL
```

This preserves all workout/set_log history when a routine is deleted — the
workout just becomes "ad-hoc" (routine_id NULL) the way an unplanned session
already works. History is never lost by deleting a routine.

---

## 2. Reset progress on a single exercise (spec settled — ready to build)

**Soft reset, confirmed:** history stays fully visible (charts, past sessions,
PRs all remain), but the progression engine and stall detection treat "now"
as a fresh start — as if the exercise had no prior sets for suggestion
purposes, without deleting anything.

**Schema addition** (docs/schema.md): add `progress_reset_at` (TEXT,
nullable) to the `exercise` table. When set, the progression-suggestion and
stall-detection queries filter `set_log.logged_at > progress_reset_at`
instead of scanning all history. Charts and Exercise Detail history queries
ignore this field entirely and keep showing everything — the reset is
invisible everywhere except the suggestion engine.

UI: "Reset Progress" action on Exercise Detail (not "delete", different verb
on purpose since nothing is destroyed). Confirm dialog explains it in plain
terms: "History stays visible. Weight suggestions start fresh from your next
session." Sets `exercise.progress_reset_at = now()`. No data deleted, so no
red/destructive styling needed — this is reversible in spirit even if there's
no literal undo (a second reset just moves the marker again).

---

## 3. Clearer, more tappable buttons (ready to build)

Two separate problems, both real: targets are too small (Apple's bare
minimum, not comfortable), AND several controls are barely visible at all —
plain muted-grey text with no fill or border (the [skip] timer control, the
video-link chip, chevron-only rows) reads as decoration, not as something
tappable, especially at a glance mid-set.

Fixes to docs/design-language.md's component spec:

- Stepper tap targets: 44px -> 52px.
- Primary button height: 52px -> 56px.
- **Secondary/tertiary buttons need real button chrome, not bare text.**
  Anything tappable (skip, video-link, jump-list row actions) gets a visible
  border (--border, 1px) AND a background fill (--surface or --card, not
  transparent) at minimum — never color-only or text-only. Reserve plain
  --muted text for genuinely non-interactive labels (section headers, meta
  info like "3x10") so the visual language itself tells you what's tappable.
- Timer [skip] control specifically: promote from quiet text link to a real
  bordered pill button, still small/secondary in visual weight (this isn't
  the primary action) but unmistakably a button.
- Minimum spacing between adjacent tappable elements: >= 8px everywhere,
  audited especially on Active Workout (stepper next to "did as suggested"
  is the highest-frequency tap sequence in the app).

Net effect: keep the calm/quiet aesthetic (no loud colors, no shouting), but
every tappable thing gets a border + fill so "is this a button" is never a
question at the gym.

---

## 4. AI-suggested substitutions (spec settled — ready to build)

This supersedes CLAUDE.md decision log item 5 (rule-based pattern/muscle-group
ranked alternatives). That approach is replaced entirely by the design below.
**Update CLAUDE.md decision log item 5 in the same commit** to read: "Swap
sheet shows Previously used (from substitution table) plus AI-suggested
alternatives (Claude Haiku, cached per exercise, see BACKLOG item 4) — no
rule-based pattern/muscle-group list."

**Flow:**
1. Swap sheet opens. "Previously used" renders instantly from the
   `substitution` table — actual past swaps for this exact routine_exercise
   slot. Zero cost, zero delay, can be empty (fine, just means never swapped
   this one before).
2. Below it, a button: "Get AI Suggestions" (not auto-fetched — this is the
   deliberate cost/latency guard from the original design pass).
3. First press: check `ai_suggestion_cache` for this exercise. If 3+ unshown
   suggestions already exist there, show them instantly — no API call. This
   is the specific fix for "pressed swap, got distracted, no change made,
   pressed swap again later" — the second attempt costs nothing.
4. If fewer than 3 unshown cached suggestions exist, call Haiku for the
   shortfall (see prompt contract below), save all results to the cache,
   show 3.
5. Once results are showing, the button becomes "Refresh." Same logic:
   pull the next 3 unshown cached suggestions if they exist; only call
   Haiku again if genuinely exhausted.
6. Shown suggestions are marked `shown_at` in the cache so they're never
   re-served as "new" — and any suggestion ever cached for this exercise
   (shown or not) is sent to Haiku as an exclusion list on every fresh call,
   so no true duplicate appears across the exercise's whole lifetime.
7. **Cache never expires in v1.** It's per-exercise, permanent — a good
   suggestion from months ago is still sitting there next time this
   exercise needs a swap. This is a deliberate simplicity choice, not an
   oversight.

**Prompt contract sent to Haiku:** the exercise being replaced (name, cue,
movement_pattern, muscle_group, equipment, exercise_type), explicit framing
that its equipment is specifically unavailable right now, the program
objective, the full program's routines/exercises for context, and the full
exclusion list of every name ever cached for this exercise slot.

**Response contract:** strict JSON, array of suggestion objects, each with
`name`, `reason` (one short sentence), `movement_pattern`, `muscle_group`,
`equipment`, `exercise_type`, `cue`, `youtube_query`. Server validates every
field against the real enums before it's ever shown — malformed response
fails closed with a friendly retry, never a raw error or broken card.

**On picking a suggestion (AI or historic):** creates a full library
exercise immediately if it doesn't already exist (AI suggestions already
carry every tag item 5's schema needs). Then asks: one-time or permanent?
- One-time: a `substitution` row only. Today's workout uses the new
  exercise; the routine is untouched going forward.
- Permanent: same `substitution` row, plus update that `routine_exercise`
  row's `exercise_id` to the new exercise (same sets/reps/rest/is_primary —
  only the exercise filling the slot changes).

**Schema additions** (docs/schema.md):

```sql
-- program_state table
objective TEXT   -- free text describing the program's goal, e.g. "HYROX
                 -- prep, back-friendly, full-body balanced, progressive
                 -- overload." Set once via Settings. Sent as context on
                 -- every Haiku call so suggestions stay aligned with
                 -- intent, not just equipment/pattern matching.

-- exercise table
equipment TEXT   -- nullable. AI-created exercises always populate this.
                 -- Existing exercises pick it up on next JSON re-import
                 -- (import already updates tags on name-match).

-- new table: per-exercise AI suggestion cache, never expires in v1
CREATE TABLE ai_suggestion_cache (
    id                  INTEGER PRIMARY KEY,
    planned_exercise_id INTEGER NOT NULL REFERENCES exercise(id),
    suggestion_json     TEXT NOT NULL,   -- full validated suggestion object
    created_at          TEXT NOT NULL,
    shown_at            TEXT             -- NULL until displayed once
);

-- new table: log of ACTUAL Haiku calls only (not cached re-shows),
-- backs the 100/day guardrail
CREATE TABLE ai_call_log (
    id         INTEGER PRIMARY KEY,
    created_at TEXT NOT NULL
);
```

**Settings addition:** a plain text field for the program objective, saved
to `program_state.objective`. Small, one-time setup — you'll fill this in
once (e.g. the HYROX-prep, back-friendly, progressive-overload framing from
the original program design) and it feeds every future Haiku call.

**Import JSON format:** add optional `equipment` per exercise, following the
same update-on-name-match semantics as cue/youtube_query/tags today.

- Model: Claude Haiku — fast, cheap, sufficient for "pick a good gym
  substitute given this context."
- API key: server-side only, new `ANTHROPIC_API_KEY` in `.env`, never sent
  to the browser. First server-side secret beyond `LIFTLOG_SECRET` — same
  care applies (gitignored, never logged).
- UI states: loading spinner only during an actual Haiku call (cache hits
  are instant, no spinner needed); graceful failure if offline or the call
  errors — Previously Used remains available regardless, this is always
  additive, never a blocking dependency.
- **Guardrail:** cap at 100 actual Haiku calls per rolling 24 hours, backed
  by `ai_call_log` (cached re-shows don't count, only real API calls do).
  Button disables with a plain message if hit — extremely unlikely at real
  usage, cheap insurance against a stuck retry loop.

---

## 5. Exercise type (weight/reps, reps-only, duration, distance, none)

Right now every exercise is assumed to be weight + reps. That's wrong for
stretches, planks, and anything bodyweight-timed — and will be wrong for
future distance work (HYROX running intervals). This needs a real type field
that changes both what gets logged and what input control Active Workout
shows.

**Schema additions** (docs/schema.md):

```sql
-- exercise table
exercise_type TEXT NOT NULL DEFAULT 'weight_reps'
    CHECK (exercise_type IN
      ('weight_reps','reps_only','duration','duration_weight',
       'distance','distance_weight','none'))
```

`display_unit`'s CHECK constraint broadens to also allow `'km'`/`'mi'` for
distance-type exercises (kg/lbs stays for weight-bearing types; duration
always renders as mm:ss with no unit toggle; `none` and `reps_only` have no
unit at all).

```sql
-- set_log table: weight_kg and reps both become nullable (currently
-- weight_kg is NOT NULL). Add two new nullable columns:
duration_seconds REAL,
distance_m REAL
```

Which columns get populated depends entirely on the exercise's
`exercise_type`:
- `weight_reps` -> reps + weight_kg
- `reps_only` -> reps
- `duration` -> duration_seconds
- `duration_weight` -> duration_seconds + weight_kg
- `distance` -> distance_m
- `distance_weight` -> distance_m + weight_kg
- `none` -> nothing (completion record only)

**Input control per type on Active Workout:**
- `weight_reps` — unchanged: weight stepper + reps stepper (today's design).
- `reps_only` — reps stepper only, no weight chip. (Cat-Cow, bodyweight
  push-ups, etc.)
- `duration` — a duration stepper (seconds, displayed mm:ss where relevant),
  same "did as suggested" one-tap pattern, pre-filled from last time.
  (Plank, dead hang, stretches you actually want tracked.)
- `duration_weight` — duration stepper + weight stepper. (Weighted plank,
  farmer's carry hold in place.)
- `distance` — distance stepper (km/mi display toggle, same pattern as
  kg/lbs). (Future: running intervals, row erg by distance.)
- `distance_weight` — distance stepper + weight stepper. (Loaded carry for
  distance — relevant for HYROX-style farmer's carry work.)
- `none` — no metric input at all. Just a checkbox/tap to mark it done.
  Creates a `set_log` row with everything NULL except the type marker, for
  session-completion history only. (Plain stretches like the doorway chest
  stretch — you did it, nothing to measure.)

**Progression scope for v1** — keep this proportionate:
- `weight_reps`: existing double-progression engine, unchanged.
- `reps_only`, `duration`, `distance`: simple version — suggest +1 rep, +5s,
  or a small distance bump when the top of range is hit cleanly, same stall
  logic (3 flat sessions -> flag it), just without a weight axis.
- `duration_weight` and `distance_weight`: log and chart, but **no
  auto-suggestion in v1** — you don't have exercises of these types yet
  (HYROX loaded-carry work is the likely future case). Don't build the
  suggestion logic ahead of having a real exercise to test it against.
- `none`: never enters progression or stall logic at all. It's a completion
  record, nothing more.

**Import JSON:** add `exercise_type` per exercise, default `weight_reps` if
omitted — so the program you already imported keeps working without
modification, and only new imports need to specify it.

---

## 6. Archive and reactivate programs (schema already supports this — UI only)

Good news: `routine.is_archived` already exists in the schema from the
original design — this was built in deliberately but never got a screen.
This is a UI-only addition, not a schema change.

**Distinct from Item 1 (delete):** archive is soft and reversible — the
routine and its routine_exercise rows stay fully intact, it's just hidden
from the default Routines view. Delete (item 1) is hard and permanent. Both
should be offered as separate actions (e.g. two options on a routine's
menu/swipe: "Archive" vs "Delete"), so it's never ambiguous which one you're
choosing.

**UI:**
- Routines screen gets two views — Active (default) and Archived (a tab or
  toggle at the top, per design-language.md's existing tab pattern from
  Active Workout's day tabs).
- Active routines get an "Archive" action → sets `is_archived = 1`, routine
  moves to the Archived view, disappears from Home's "today's routine"
  logic.
- Archived routines get a "Reactivate" action → sets `is_archived = 0`,
  routine moves back to Active.
- Re-importing JSON with a name matching an archived routine should also
  reactivate it automatically (update its exercises AND flip
  `is_archived = 0`) — so pasting a program back in "just works" without
  requiring the manual toggle too, though the manual toggle should exist
  for quick reactivation without needing the JSON on hand.

