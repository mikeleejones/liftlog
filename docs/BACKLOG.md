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

- Trigger: "Ask for a suggestion" button inside the existing substitution
  sheet, alongside the 3 rule-based alternatives — opt-in, not a replacement.
- **Context sent, confirmed:** the program objective (new field, see below),
  the entire program — all routines and their exercises, not just today's —
  and recent history on candidate exercises. Larger payload than a minimal
  call, but still small in absolute terms for a single program; worth
  knowing this means slightly higher latency than a bare single-exercise
  prompt, acceptable for an opt-in, non-blocking action.
- **Schema addition:** `program_state` gets a new `objective` (TEXT) field —
  free text describing the program's goal (e.g. "HYROX prep, back-friendly,
  full-body balanced, progressive overload"). Set once via Settings, sent as
  context on every AI-suggestion call so swaps stay aligned with intent
  rather than just matching movement pattern.
- Model: Claude Haiku — fast, cheap, sufficient for "pick a good gym
  substitute given this context."
- API key: server-side only, new `ANTHROPIC_API_KEY` in `.env`, never sent
  to the browser. First server-side secret beyond `LIFTLOG_SECRET` — same
  care applies (gitignored, never logged).
- UI states: loading spinner while the call is in flight (this won't be
  instant like the rest of the app), graceful failure if offline or the call
  errors — rule-based alternatives remain available regardless, this is
  always additive, never a blocking dependency.

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
      ('weight_reps','reps_only','duration','weight_duration',
       'distance_duration','none'))
```

`display_unit`'s CHECK constraint broadens to also allow `'km'`/`'mi'` for
distance-type exercises (kg/lbs stays for weight-type; duration always
renders as mm:ss with no unit toggle; `none` has no unit at all).

```sql
-- set_log table: weight_kg and reps both become nullable (currently
-- weight_kg is NOT NULL). Add two new nullable columns:
duration_seconds REAL,
distance_m REAL
```

Which columns get populated depends entirely on the exercise's
`exercise_type` — the app decides what to show/save, the schema just has
room for all of it.

**Input control per type on Active Workout:**
- `weight_reps` — unchanged: weight stepper + reps stepper (today's design).
- `reps_only` — reps stepper only, no weight chip. (Cat-Cow, bodyweight
  push-ups, etc.)
- `duration` — a duration stepper (seconds, displayed mm:ss where relevant),
  same "did as suggested" one-tap pattern, pre-filled from last time.
  (Plank, dead hang, stretches you actually want tracked.)
- `weight_duration` — weight stepper + duration stepper. (Weighted plank,
  farmer's carry hold.)
- `distance_duration` — distance stepper + duration stepper. (Future: row
  erg, running intervals — not needed for the current program, schema-ready
  for later.)
- `none` — no metric input at all. Just a checkbox/tap to mark it done.
  Creates a `set_log` row with everything NULL except the type marker, for
  session-completion history only. (Plain stretches like the doorway chest
  stretch — you did it, nothing to measure.)

**Progression scope for v1** — keep this proportionate:
- `weight_reps`: existing double-progression engine, unchanged.
- `reps_only` and `duration`: simple version — suggest +1 rep or +5s when
  the top of range is hit cleanly, same stall logic (3 flat sessions ->
  flag it), just without a weight axis.
- `weight_duration` and `distance_duration`: log and chart, but **no
  auto-suggestion in v1** — you don't have exercises of these types yet
  (HYROX running work is the likely future case). Don't build the
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

