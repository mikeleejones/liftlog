# LiftLog

Personal workout tracker. Single user (MLJ). Self-hosted web app on a shared
OVH VPS (see Server access — originally ultra.cc, moved since).
This file is the design authority — read it and `docs/` before writing any code.
When a design decision here conflicts with an implementation idea, this file wins;
if a change is genuinely warranted, propose amending this file first, then code.

## Product definition

A personal workout tracker for one user, self-hosted on a shared OVH VPS as a
web app with a Python backend and SQLite storage, accessed from iPhone (primary, at the
gym, Chrome) and MacBook (program design, progression charts, analysis).
Programs are designed through an in-app Claude Haiku conversation. It tracks
routines, sets, reps, and weight; runs a rest timer; and suggests progressive
overload using double progression with deload weeks. Exercise demos are YouTube
search links, so the exercise library is unlimited. Data is exportable as JSON
at any time.

It does NOT do: accounts/auth beyond a single shared secret (plus a separate,
narrower read-only automation token type for external tools like Shortcuts and
scripts — revocable credentials, distinct from the browser login secret; this
is NOT a multi-user account system: still single-user, no passwords, no signup),
social features,
coaching content, body measurements, nutrition, offline operation, supersets,
or per-set RPE. Do not add these.

## Stack

- Backend: Python 3.11+, FastAPI as a JSON API (`/api/*`), SQLAlchemy models +
  Alembic migrations over SQLite (single file), uvicorn. (Superseded the
  original Jinja2-templated FastAPI + hand-rolled sqlite3 migrations — see
  decision #15.)
- Frontend: React 19 + TypeScript + Vite + Tailwind CSS 4 + shadcn/ui + React
  Router + TanStack Query, built to `frontend/dist` and served as a static SPA
  (superseded the original server-rendered Jinja2 + vanilla JS + CSS — see
  decision #15). Design tokens (color/type/spacing/radius) still come from
  `docs/design.md` unchanged; the migration is a rendering-technology change,
  not a design-language change. Mobile-first, max content width 560px (760px
  on chart screens).
- Auth: one shared secret. A cookie set via `/api/auth/login`; every API route
  checks it (SPA fetches are same-origin, credentialed). Secret lives in
  server config/env, never in the database or repo.
- Deployment target: a shared OVH VPS (see Server access below) behind Caddy.
  Caddy serves `frontend/dist` directly and reverse-proxies `/api/*` to the
  FastAPI process — see `DEPLOY.md`. Develop and run locally first; deploy to
  `liftlog-staging` before production.

## Binding specs in docs/

- `docs/schema.md` — the complete data model, derived-value rules (progression,
  stall, warmup ramp), unit handling, the internal AI program format, and
  program replacement/deduplication semantics. Implement exactly;
  do not add tables or columns without amending the doc.
- `docs/design.md` — **v2 (light)** design language (BACKLOG item 15; v1 dark
  is deprecated): color tokens, typography (Inter for ALL UI text, JetBrains
  Mono for numeric/tabular data only), spacing/radius scale, component specs
  (primary button, stepper, exercise card, rest timer bar, bottom tab bar,
  sheets, charts), motion rules, and interface copy voice. Every screen derives
  from these tokens; no ad-hoc colors or font sizes.
- `docs/api.md` — the binding HTTP API contract introduced by v0.6. Every
  `/api/*` endpoint's request, response, auth, and error behavior must be
  documented there in the same change as its implementation.

## Screens — four-tab structure (item 10)

A persistent bottom tab bar with four destinations:

- **Home** — dashboard: today's quick-start routine card (starts the session
  directly), deload banner/defer, and the program overview folded in from the
  old standalone Progress screen (which lifts are progressing/stalled,
  completed weeks, weeks-since-deload, honesty audit). Progress is no longer a
  separate screen; `/progress` redirects to Home.
- **Workout** — the routines list (Active/Archived tabs, per-routine
  Archive/Delete) and AI program builder; where a session starts from. Backing URL `/routines`.
  Tapping a routine row opens a read-only preview of its exercises
  (`/routines/{id}/preview`, keeps the tab bar) — the preview creates no
  workout and starts no timer; only an explicit START (present on both the
  preview and the quick-start cards) begins a session.
- **Exercises** — the full exercise library, searchable by name. The front
  door to Exercise Detail, which is no longer reachable only through a routine.
- **Profile** — both exports (full backup + program-only), the API token
  manager, the program objective field, and
  shared-secret/session info. All data movement and configuration lives here.
  Backing URL `/settings`.

Full-screen (no tab bar): Active Workout and Finish Summary. The tab bar is
cleanly UNMOUNTED (not just CSS-hidden) while Active Workout is EXPANDED so it
keeps its full-screen focus, and reappears at Finish Summary. Active Workout can
also be MINIMIZED (decision #14), which remounts the tab bar and puts the
running session in a mini-bar above it. Login has no tab bar.
Exercise Detail (history + chart, Reset Progress) is reached from the
Exercises tab and keeps the bar (Exercises active).

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
5. Swap sheet shows Previously used (from substitution table) plus
   AI-suggested alternatives (Claude Haiku, cached per exercise, see BACKLOG
   item 4) — no rule-based pattern/muscle-group list. (Supersedes the original
   rule-based ranking; the swap-sheet UI and Haiku integration land in a later
   session.) Swaps/skips are recorded in the substitution table (re-swapping
   replaces the record) and never count toward stall detection.
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
11. Day accent colors code routines everywhere: blue=Mon, teal=Wed, green=Fri,
    indigo=home/analysis (v2 light palette; was cyan/gold/green/violet in v1).
    Green progression chip "↑ 62.5" is the signature element.
12. Interface copy: mono, factual, calm. No exclamation marks, no coach voice.
13. Programs group routines (added 2026-07-02): a program is a named set of
    routines spanning one or more weeks, repeated on a weekly cycle. Several
    programs may be stored; exactly one is active. The active program's
    current week drives Home and weekly compliance. Import v2 wraps routines
    in a program envelope and activates the imported program; v1 imports are
    still accepted and upsert routines into the active program's week 1.
    Routines dedupe by name within their program, not globally. Routines
    dropped by a program re-import are archived, never deleted.
14. Active Workout is minimizable (added 2026-07-21, BACKLOG item 20). This
    AMENDS the original "full-screen takeover, tab bar unmounted" rule, which
    now describes the EXPANDED state only. A chevron-down control (not a swipe
    — the app has no other gesture interactions) collapses the session: the tab
    bar remounts, the user can browse Home/Workout/Exercises/Profile, and a
    mini-bar above the tab pill shows the routine name plus the live rest
    countdown or elapsed time, tapping through to resume exactly where they
    left off. The session never pauses — it keeps running server-side, and the
    rest countdown and current exercise position survive in localStorage
    (presentation state only; every set is already persisted server-side the
    moment it's logged). The screen wake lock releases on minimize and
    re-acquires on return, via the existing pagehide/visibilitychange path.
    This does NOT add background push: leaving the app or browser entirely
    still means no rest-timer alert, exactly as before.
15. Frontend/backend migration to React + FastAPI-JSON-API (added
    2026-08-27). This AMENDS the original "server-rendered HTML + vanilla JS,
    no framework, no build step" stack decision and the "no framework
    migrations" working agreement — both superseded, see the Stack section
    above. A first migration attempt (commit `6e48cbd`, Aug 2026) was built
    and then fully discarded (`git reset` to `bd812d3`) because a mid-stream
    coding-model switch produced a UI that looked worse than the original and
    had broken functionality — not because the framework approach itself was
    wrong. This migration is a deliberate retry with explicit gates (see the
    migration/large-change discipline working agreement) rather than a
    reversal of the decision to move to React. Scope: FastAPI becomes a pure
    JSON API (`/api/*`, contract documented in `docs/api.md`); `db.py`'s
    hand-rolled sqlite3 migrations are replaced with SQLAlchemy models +
    Alembic (matching the pattern already used by the Rental Radar project on
    the same server); the frontend becomes a React 19 + Vite + TS + Tailwind +
    shadcn/ui SPA built to `frontend/dist` and served by Caddy, mirroring
    Rental Radar's already-proven Caddy block on the same VPS. `docs/design.md`
    is unchanged and remains the single source of visual truth for the new
    frontend. The old ultra.cc subpath/root-path deployment support
     (`LIFTLOG_ROOT_PATH`) is dropped as dead code now that real deployment is
     per-subdomain Caddy routing on the OVH VPS (see Server access).
16. AI program builder (added 2026-08-28): Program creation is an in-app,
    multi-turn Claude Haiku conversation in the Workout tab, not a pasted
    claude.ai JSON payload. The model emits the documented v2 program object,
    which is validated and applied through the existing importer so routine
    replacement, archival, case-insensitive exercise reuse, and history
    preservation remain unchanged. A candidate is always previewed before it
    can be applied. This supersedes the claude.ai-only import constraint.

## Build plan — work ONE increment at a time, wait for user testing between

- v0.1 Log: FastAPI + SQLite per schema, shared-secret auth, Home + Active
  Workout + Finish screens, ONE hardcoded routine for testing, runnable
  locally (accessible from iPhone via Mac's LAN IP).
- v0.2 Import: Routines screen, program creation with preview + dedupe semantics,
  exercise library view. (Superseded by decision #16's in-app AI builder.)
- v0.2.5 Programs: program table grouping routines, multi-week programs,
  import v2 (program envelope), program activation, weekly compliance derived
  from the active program week instead of a fixed 3.
- v0.3 Brains: progression suggestions, stall detection, warmup ramps, deload
  tracking/banner, substitution picker with 3 alternatives.
- v0.4 Polish: Progress screens with charts, Exercise Detail history, JSON
  export, timer vibration where supported, PWA manifest for Add to Home
  Screen, deployment to ultra.cc (later moved to the current OVH VPS — see
  Server access).
- v0.5: the 22 items in `docs/BACKLOG.md`, shipped incrementally (four-tab
  nav, AI substitutions, automation tokens, light-theme v2 redesign, TCX
  export, minimize/mini-bar, Home v2 charts, and more — see git log for the
  full list).
- v0.6 Frontend migration (decision #15, complete): FastAPI → JSON API +
  SQLAlchemy/Alembic; server-rendered Jinja2 + vanilla JS → React/Vite SPA.
  Phased and gated per screen, tested on `liftlog-staging` (and at the gym for
  Active Workout) before each next phase — same discipline as v0.1-v0.5, just
  applied to a technology change instead of a feature.

Do not start an increment until the previous one has been used at the gym and
signed off. Do not build ahead "while you're in there."

## Working agreements

- Keep the whole app small: this is a personal tool, not a product. Prefer
  boring code, no premature abstraction. The one-time exception is the
  frontend/backend migration in decision #15 — once it lands, that is not an
  invitation to churn the stack further; treat the new stack (React/Vite/
  FastAPI-API/SQLAlchemy) as the new "boring" baseline going forward, same as
  the old one was.
- Migration/large-change discipline (added with decision #15, applies to any
  future change of similar size): never switch coding models mid-phase
  without a written handoff checkpoint in this file or `CHANGES.log` — the
  first migration attempt was discarded partly because a mid-stream model
  switch produced inconsistent, regressive output. Every new screen/surface
  must be checked against `docs/design.md` for visual fidelity and against
  existing shipped behavior for functional parity before being considered
  done, not just "compiles and loads."
- Schema changes require updating docs/schema.md in the same commit.
- Never commit secrets. .gitignore the SQLite database file and any .env.
- Place new features in the tab matching their KIND, not their build order
  (item 10's whole point): a single exercise's data/history goes in Exercises;
  routine composition or session-starting goes in Workout; data movement or
  account-level config goes in Profile; a stat/summary/dashboard widget goes in
  Home. This keeps screens grouped by purpose so another reorg isn't needed.

## Server access

liftlog runs on a shared OVH VPS (alongside other personal projects), not
ultra.cc — that was the original v0.4 deployment target and has since been
replaced; this section previously described it incorrectly.

- SSH: `ssh mrradcl` (alias in `~/.ssh/config`; the deployment host is OVH,
  not ultra.cc).
- Process manager: pm2. Two processes: `liftlog` (production) and
  `liftlog-staging`, both under `/home/ubuntu/apps/<name>/`.
- Reverse proxy: Caddy (`/etc/caddy/Caddyfile`), not nginx. Production is
  `liftlog.mrradcl.com` (proxies to `localhost:8001` today; becomes
  `root * frontend/dist` + `handle /api/* { reverse_proxy }` + SPA
  `try_files` fallback after the frontend migration, matching the
  `rentalradar.mrradcl.com` block already on that box). Staging is
  `liftlog-staging.mrradcl.com` → `127.0.0.1:8011`.
- Deployment is by **rsync**, not git — the server directories are not git
  repos. See `DEPLOY.md` for the exact commands.

Always ask for explicit confirmation before running anything destructive on
the server (pm2 delete, database migrations, rm on liftlog.db) — read-only
checks (pm2 status, logs, describe) don't need to ask.
