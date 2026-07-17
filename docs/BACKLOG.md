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

---

## 7. Read-only automation tokens (foundation for items 8 and 9)

This amends CLAUDE.md's stated non-goal of "auth beyond a single shared
secret." That non-goal is about not building a multi-user account system —
this isn't that. It's a second, narrower credential type solely for
external automations (Shortcuts, future scripts) to read data without
holding the same secret that logs you into the app itself. Still
single-user, still no accounts, no passwords, no signup flow.

**Schema addition** (docs/schema.md):

```sql
CREATE TABLE api_token (
    id           INTEGER PRIMARY KEY,
    name         TEXT NOT NULL,       -- e.g. "iPhone Shortcuts"
    token        TEXT NOT NULL UNIQUE,-- random, shown once at creation
    scope        TEXT NOT NULL DEFAULT 'read_only'
                 CHECK (scope IN ('read_only')),
    created_at   TEXT NOT NULL,
    last_used_at TEXT
);
```

v1 scope is `read_only` only — nothing external can modify LiftLog data yet,
only read it. Write access (e.g. an automation logging a workout directly)
is explicitly out of scope until there's a real use case for it.

**Settings UI:** a simple token manager — create (name it, shown once,
same UX pattern as the Anthropic console's own key creation, which you've
now used and is a good precedent) and revoke. A "last used" timestamp on
each so stale tokens are easy to spot and clean up.

**Auth on any endpoint that accepts tokens:** accept EITHER the existing
browser cookie OR a valid `Authorization: Bearer <token>` header matching
an `api_token` row. Browser login flow is completely unchanged — this is
purely additive.

---

## 8. Read-only "latest workout" endpoint

Enables the Apple Health bridge via Shortcuts (Health has no web API, so
this is the realistic path — a Shortcut pulls from LiftLog, then writes to
Health itself).

`GET /api/latest-workout` — requires a valid token (item 7). Returns the
most recently *finished* workout: `id` (the workout's database id, stable
and never reused — critical for idempotency, see below), date, duration
(finished_at - started_at), routine name, is_deload flag, total volume (sum
of weight x reps across weight_reps sets). A rough calorie estimate is
explicitly NOT included — that math is Health's job once it has duration
and workout type, not LiftLog's to guess at.

**Idempotency is the Shortcut's job, not this endpoint's.** This stays a
pure read — LiftLog never tracks whether a sync happened, keeping it
consistent with item 7's read-only scope. Instead, the response's `id`
field is what a repeatedly-triggered Shortcut uses to avoid double-writing
to Health: the Shortcut keeps a small text file (Shortcuts can read/write
files in iCloud Drive) holding the last synced workout `id`. Each run:
fetch latest workout, compare `id` to the stored value — same id, do
nothing; different id, write to Health and update the stored file. This
means triggering the Shortcut twice (or on an automatic location-based
trigger that fires more than once) is always safe, entirely without
LiftLog needing any write capability or sync-state of its own.

Small enough to keep read-only and single-purpose: this endpoint answers
exactly one question ("what was my last workout") and nothing more. A
"today's routine" variant is tempting to bundle in but should wait for a
concrete use case (e.g. a home-screen widget) rather than being built
speculatively.

---

## 9. Program-only export (distinct from the existing full backup export)

v0.4 already has a full-database JSON export on Settings — everything,
including workout history. This is different: a **program-only** export in
exactly the same shape as the import format (routines + exercises, tags,
targets — no workout/set_log history at all).

Use cases this unlocks: round-tripping a program out to tweak with Claude
and back in without a full-database file; sharing a routine with someone
else's LiftLog instance (Sarah, if she ever wants her own HYROX program in
her own instance) without exposing your training history; a clean backup of
"just the program" separate from personal data.

**UI:** a second export button on Settings, "Export Program Only," output
identical in shape to the existing import JSON schema — meaning it can be
fed right back into Import with no transformation. Uses the same
token-or-cookie auth as everything else on Settings (no new auth needed,
this one's browser-only, not part of the automation surface).

---

## 10. Navigation reorganization — four-tab structure

Nine items in, screens have accumulated features by *when they were built*
rather than *what they're for* — Settings in particular now mixes program
config, data import/export, and automation credentials with no real
grouping. This is a deliberate IA pass, not a cosmetic tweak, and it sets
the pattern every future backlog item should follow so this doesn't happen
again.

**Structure (modeled on Hevy):** a persistent bottom tab bar with four
destinations. Hidden during Active Workout (full-screen takeover, unchanged
from today); reappears at Finish Summary.

1. **Home** — dashboard. Today's suggested routine as a quick-start card,
   deload banner/defer control (unchanged from today's Home), recent
   activity, progression highlights ("2 lifts ready to progress"). This
   absorbs the old standalone Progress screen entirely — no separate
   Progress tab. Tapping the quick-start card still starts today's routine
   directly, same as today; this is a shortcut into the Workout tab's flow,
   not a separate code path.
2. **Workout** — the routines list (Active/Archived tabs, per-routine
   Archive/Delete actions — all unchanged from item 6, just relocated).
   This is where a session actually starts from, whether that's today's
   default or picking something else.
3. **Exercises** *(new destination)* — full library, searchable by name.
   Tapping an exercise opens Exercise Detail (history, chart, Reset
   Progress from item 2 — unchanged functionality, now has a proper front
   door instead of being reachable only through a routine).
4. **Profile** — settings, Import, both exports (full backup + program-only
   from item 9), the API token manager (item 7), the program objective
   field (item 4), shared secret/session info. Everything about data
   movement and configuration lives here, nothing else does.

**Migration map (what moves from where):**

| Feature | Was | Now |
|---|---|---|
| Routines list (Active/Archived) | standalone screen | Workout tab |
| Import | same screen as Routines | Profile tab |
| Full backup export | Settings | Profile tab |
| Program-only export (item 9) | Settings | Profile tab |
| API token manager (item 7) | Settings | Profile tab |
| Program objective field (item 4) | Settings | Profile tab |
| Progress screen (program overview) | standalone screen | folded into Home |
| Exercise Detail | reachable only via a routine | Exercises tab (new front door), same screen otherwise |
| Deload banner/defer | Home | Home (unchanged) |
| Active Workout / Finish Summary | full-screen, no nav | unchanged |
| AI substitution swap sheet (item 4) | inline in Active Workout | unchanged, stays inline |

**Design-language.md addition:** spec the bottom tab bar component — four
equal-width tabs, icon + label, active-tab indicator using the existing
accent tokens (reuse the day-accent system's visual weight, not a fifth new
color), 1px top border matching existing card border treatment. Hidden
state (during Active Workout) should be a clean unmount, not just
visually collapsed, so Active Workout keeps its full-screen focus exactly
as designed.

**CLAUDE.md update required in the same commit:** the "Screens (7 total)"
section needs to be rewritten to reflect this structure — it's the kind of
drift that makes CLAUDE.md stop being trustworthy as the source of truth if
left unupdated after a change this size.

**Guidance for all future backlog items (add this as a standing note in
CLAUDE.md, not just this entry):** default new features to the tab matching
their *kind*, not their build order — a single exercise's data/history goes
in Exercises; routine composition or session-starting goes in Workout; data
movement or account-level config goes in Profile; a stat/summary/dashboard
widget goes in Home. This is the whole point of doing this pass — the next
nine items shouldn't need a reorganization like this one.

---

## 11. TCX export for manual Apple Health sync

Confirmed working via manual test: a TCX file with `Sport="Other"`, no GPS
track, `DistanceMeters` 0, imports cleanly into Health via the free
"TCX to HealthKit" App Store app — correct duration, correct start/end
times, filed as workout type "Other" (TCX has no strength-training sport
value, "Other" is the correct/only choice — confirmed acceptable). This
supersedes the earlier Shortcuts/API-pull approach (item 8's
/api/latest-workout endpoint stays, unrelated, still useful for other
automation) with something simpler: no branching logic, no idempotency
concerns, since it's a manual explicit action each time rather than an
automated trigger that could double-fire.

**What to build:** a "Export to Health (.tcx)" button on Finish Summary
(and optionally also on a past workout's detail view, for logging one
after the fact). Generates a TCX file matching the structure of the tested
sample:

```xml
<Activity Sport="Other">
  <Id>{workout.started_at, ISO8601}</Id>
  <Lap StartTime="{workout.started_at, ISO8601}">
    <TotalTimeSeconds>{duration_seconds}</TotalTimeSeconds>
    <DistanceMeters>0</DistanceMeters>
    <Calories>{calorie_estimate}</Calories>
    <Intensity>Active</Intensity>
    <TriggerMethod>Manual</TriggerMethod>
  </Lap>
  <Creator xsi:type="Device_t"><Name>LiftLog</Name></Creator>
</Activity>
```

**Calorie estimate:** unlike the Shortcuts attempt, this runs server-side in
Python, not client-side in Shortcuts' action UI — no Health-permission
fetching, no multi-step action chain, just arithmetic. Use the same
METs formula abandoned earlier for being too fiddly in Shortcuts: `calories
= 6 x bodyweight_kg x (duration_seconds / 3600)` (6 METs = generic strength
training average). This needs a bodyweight value on file.

**Schema addition** (docs/schema.md): add `bodyweight_kg` (REAL, nullable)
to `program_state` — reuse the existing singleton config table rather than
creating a new one for a single field, consistent with keeping the schema
lean. Add a corresponding field on the Profile tab, next to the program
objective field, so it's set once and reused for every export. If
`bodyweight_kg` is unset, fall back to `Calories: 0` (matching the original
zero/zero decision) rather than guessing — never fabricate a number with no
input to base it on.

**UI:** the export button downloads the .tcx file directly (standard
browser download, same mechanism as the existing JSON exports). No new
auth needed — this lives on Finish Summary / workout detail, already
behind the normal session.

---

## 12. iOS safe-area / layout overflow fixes

Real bug, not a vague "improve compatibility" ask — screenshot shows the
Workout tab's header text rendering underneath the iOS status bar (time,
battery, signal icons overlapping the program name). This is the classic
PWA `viewport-fit=cover` issue: the meta tag opts into edge-to-edge
rendering (needed for a proper full-screen installed-app look) but nothing
in the CSS is padding content away from the notch/Dynamic Island/status bar
to compensate.

**Fix:** apply `env(safe-area-inset-top)` as top padding on every screen's
header/sticky-top element, and `env(safe-area-inset-bottom)` as bottom
padding on the tab bar (item 10) so it clears the home indicator too —
audit both, the screenshot only shows the top issue but the bottom is the
same class of bug and easy to miss if not checked explicitly.

**Also audit for horizontal overflow** while in there: confirm long routine
names (e.g. "Full Body Strength + Back Health") wrap cleanly within their
card rather than pushing card borders to the screen edge or overlapping
the status bar row — test specifically with the longest real routine/
program names currently in use, not just short placeholder text, since
that's exactly the kind of thing that only surfaces with real data.

**Test on the actual affected screen (Workout tab) first**, then spot-check
Home, Exercises, and Profile for the same safe-area gap — this class of bug
tends to be copy-pasted across screens if the header component isn't
shared/componentized consistently.

---

## 13. Ensure "last time" weight/reps is always visible mid-set

This was part of the original Active Workout design from day one (see the
very first wireframe: "Last: 60kg × 10,10,10 → try 62.5") — audit whether
it's actually missing, or present but not prominent enough to notice under
gym pressure. Either way, the fix is the same: make it a permanent, clearly
visible element on every exercise card during Active Workout, not
something that requires scrolling or a tap to reveal. Should sit near the
weight/rep stepper, not buried above the fold.

---

## 14. Preview a routine's exercises without starting a session

Currently tapping a routine on the Workout tab leads toward starting it.
Add a read-only preview: tapping a routine row opens its exercise list
(names, sets/reps/rest targets, order) without creating a workout or
starting any timer. A separate, explicit "Start" action begins the actual
session from either the preview or the Workout tab list directly — the
preview is purely informational, never a side-door into starting a
workout.

---

## 15. Full light-theme redesign (supersedes the original dark theme)

This reverses the visual direction set at original design time (CLAUDE.md's
"inherited from the back-routine reference page" decision) — a deliberate
reversal, not a bug fix. Update docs/design-language.md's header to note
v1 (dark) is deprecated, this is v2 (light), and CLAUDE.md's design
language reference should point to this version.

**Personality:** clean and minimal — lots of white space, restrained color
use, confident rather than decorative. Hevy is the structural reference
point (white surfaces, card-based lists, a dark neutral anchor at the
bottom, generous whitespace) but with LiftLog's own fresh palette, not a
clone of Hevy's specific colors.

**New color tokens** (full replacement of the v1 dark token set):

```css
:root {
  --bg:      #FAFAFA;  /* near-white, neutral not warm */
  --surface: #FFFFFF;
  --card:    #F5F5F7;  /* light neutral grey */
  --border:  #E5E5EA;
  --text:    #1C1C1E;  /* near-black */
  --muted:   #8E8E93;

  --blue:    #4C7FF0;  /* Monday */
  --teal:    #2FA89C;  /* Wednesday */
  --green:   #34C759;  /* Friday + success/progression (dual role, same pattern as old sage/green) */
  --indigo:  #6C63FF;  /* Home/analysis contexts */
  --red:     #FF3B30;  /* destructive only */

  --tabbar:  #1C1C1E;  /* the one dark element — bottom tab bar, near-black not navy */
}
```

**Typography:** Inter for all UI text, labels, buttons, cues, headers.
JetBrains Mono RETAINED, but only for numeric/tabular data — weights,
reps, rest timer countdown, set counts. Deliberate carryover from v1: mono
alignment is functionally useful for numbers, the complaint was about
buttons/labels feeling cold, not about the numbers themselves.

**Shape:** modest rounding, restrained — cards and buttons at 12px radius
(a small bump from v1's 10-12px, not an aggressive softening). Clean and
minimal means confident whitespace, not maximal roundness.

**Component updates required:**
- Primary button: blue or day-appropriate accent fill, white text, rounder
  per above, full-width.
- Stepper: same functional sizing from the item 3 tappability pass
  (44-52px targets), retextured for light surfaces — must remain clearly
  bordered/filled per item 3's "visible chrome, never bare text" rule,
  which still applies regardless of theme.
- Exercise card: white surface, light grey border, moderate corner radius.
- Rest timer bar: needs real contrast testing on light backgrounds — a
  thin progress line that worked on near-black won't necessarily read
  well on off-white; verify visibility explicitly rather than assuming
  the same treatment translates.
- Bottom tab bar: near-black per token above, active-tab indicator uses
  the relevant day accent.
- Charts: verify the single-series line + PR dots treatment still reads
  clearly against light backgrounds.

**Explicitly carries over unchanged from v1** (these were separate fixes,
not dark-theme-specific): the item 3 tappability rules (visible chrome on
every interactive element, 8px minimum spacing), the item 12 safe-area
fixes, the "no exclamation marks, no coach voice" copy rules.

This touches every screen — treat as its own dedicated build like item 10,
not something to combine with any other backlog item.

