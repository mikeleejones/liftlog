# LiftLog

Personal workout tracker. Single user (MLJ). Self-hosted web app on ultra.cc.
This file is the design authority — read it and `docs/` before writing any code.
When a design decision here conflicts with an implementation idea, this file wins;
if a change is genuinely warranted, propose amending this file first, then code.

## Product definition

A personal workout tracker for one user, self-hosted on ultra.cc as a web app
with a Python backend and SQLite storage, accessed from iPhone (primary, at the
gym, Chrome) and MacBook (routine imports, progression charts, analysis).
Routines are designed with Claude in claude.ai and imported as JSON. It tracks
routines, sets, reps, and weight; runs a rest timer; and suggests progressive
overload using double progression with deload weeks. Exercise demos are YouTube
search links, so the exercise library is unlimited. Data is exportable as JSON
at any time.

It does NOT do: accounts/auth beyond a single shared secret, social features,
coaching content, body measurements, nutrition, offline operation, supersets,
or per-set RPE. Do not add these.

## Stack

- Backend: Python 3.11+, FastAPI, SQLite (single file), uvicorn
- Frontend: server-rendered HTML + vanilla JS + CSS (no framework, no build
  step). Mobile-first, max content width 560px (760px on chart screens).
- Auth: one shared secret. Cookie set via a single login field; every route
  checks it. Secret lives in server config/env, never in the database or repo.
- Deployment target: ultra.cc custom service behind their nginx reverse proxy.
  Develop and run locally first; deployment is its own step at the end of v0.1.

## Binding specs in docs/

- `docs/schema.md` — the complete data model: 8 tables (exercise, routine,
  routine_exercise, workout, set_log, substitution, program, program_state),
  derived-value rules (progression, stall, warmup ramp), unit handling, the
  Claude JSON import format, and import/dedupe semantics. Implement exactly;
  do not add tables or columns without amending the doc.
- `docs/design-language.md` — color tokens, typography (Inter for prose,
  JetBrains Mono for all numeric/structural text), spacing/radius scale,
  component specs (primary button, stepper, exercise card, rest timer bar,
  bottom sheets, charts), motion rules, and interface copy voice. Every screen
  derives from these tokens; no ad-hoc colors or font sizes.

## Screens (7 total)

Home -> Active Workout -> Finish Summary; plus Exercise Detail (history +
chart), Routines + Import (paste JSON with human-readable preview), Progress
(program overview), Settings (export, deload status, secret).

## Key decisions log (do not relitigate)

1. One-tap logging: "DID AS SUGGESTED" is the primary action per set; editing
   is the exception path via stepper (weight ±increment, reps ±1, long-press
   auto-repeat). Never a keyboard for set entry.
2. Weight stored canonically in kg. Display unit is a per-exercise property
   (kg or lbs) toggled by tapping the unit chip; stepper steps 2.5 kg / 5 lbs;
   suggestions round to loadable increments in the display unit.
3. Rest timer always auto-starts on set completion; [skip] control on the
   timer itself. Pinned bottom bar on Active Workout.
4. Auto-advance through exercises in routine order; a jump sheet (exercise
   list with done/pending state) allows out-of-order work when a machine is
   taken. No drag-to-reorder mid-workout.
5. Substitution: rarely used, critically important. Offer the 3 best
   alternatives (same movement_pattern first, then muscle_group, ranked by
   prior history) as full cards — never a search box as the primary path.
   When the library has fewer than 3 alternatives, remaining slots are filled
   from a built-in name catalog (exercise names + tags + YouTube queries
   only — never programming advice); picking one creates it in the library.
   Type-new-exercise is the escape hatch. Swaps/skips are recorded in the
   substitution table (re-swapping replaces the record) and never count
   toward stall detection.
6. Progression: double progression per exercise. All working sets at rep_max
   -> suggest +increment next time. Stall = 3 consecutive non-deload sessions
   at same weight, no total-rep improvement -> suggest 10% reset.
7. Deload: every 4th COMPLETED training week (a week is complete when all
   sessions prescribed by the active program week are finished; 3 if no
   active program). Pre-fills 60% weights, 2x10. Deferrable. Deload sessions
   excluded from stall detection. State stored in program_state, not derived.
8. Warmup ramps auto-suggested for is_primary exercises only:
   bar x10, 50% x6, 75% x3, logged as set_type='warmup', excluded from
   progression math.
9. Abandoned workout (finished_at NULL, >12h old): sets count in history,
   session does not count toward weekly compliance.
10. was_suggested flag recorded on every set (honesty audit surfaced on
    Progress screen later).
11. Day accent colors code routines everywhere: cyan=Mon, gold=Wed, green=Fri,
    violet=home/analysis. Green progression chip "↑ 62.5" is the signature
    element.
12. Interface copy: mono, factual, calm. No exclamation marks, no coach voice.
13. Programs group routines (added 2026-07-02): a program is a named set of
    routines spanning one or more weeks, repeated on a weekly cycle. Several
    programs may be stored; exactly one is active. The active program's
    current week drives Home and weekly compliance. Import v2 wraps routines
    in a program envelope and activates the imported program; v1 imports are
    still accepted and upsert routines into the active program's week 1.
    Routines dedupe by name within their program, not globally. Routines
    dropped by a program re-import are archived, never deleted.

## Build plan — work ONE increment at a time, wait for user testing between

- v0.1 Log: FastAPI + SQLite per schema, shared-secret auth, Home + Active
  Workout + Finish screens, ONE hardcoded routine for testing, runnable
  locally (accessible from iPhone via Mac's LAN IP).
- v0.2 Import: Routines screen, JSON import with preview + dedupe semantics,
  exercise library view. (After this, routines come from claude.ai.)
- v0.2.5 Programs: program table grouping routines, multi-week programs,
  import v2 (program envelope), program activation, weekly compliance derived
  from the active program week instead of a fixed 3.
- v0.3 Brains: progression suggestions, stall detection, warmup ramps, deload
  tracking/banner, substitution picker with 3 alternatives.
- v0.4 Polish: Progress screens with charts, Exercise Detail history, JSON
  export, timer vibration where supported, PWA manifest for Add to Home
  Screen, deployment to ultra.cc.

Do not start an increment until the previous one has been used at the gym and
signed off. Do not build ahead "while you're in there."

## Working agreements

- Keep the whole app small: this is a personal tool, not a product. Prefer
  boring code. No framework migrations, no premature abstraction.
- Schema changes require updating docs/schema.md in the same commit.
- Never commit secrets. .gitignore the SQLite database file and any .env.
- Routine design/programming questions are NOT Claude Code's job — those go
  back to the claude.ai conversation; this repo only consumes the JSON.
