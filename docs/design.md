# Workout Tracker — Design Language (v2, light)

**Version note:** v1 (dark — near-black surfaces inherited from the
back-routine reference page) is **deprecated** as of BACKLOG item 15. This
document now describes **v2 (light)**: clean and minimal, lots of white space,
restrained color, confident rather than decorative. Hevy is the structural
reference (white surfaces, card-based lists, a floating glass nav pill,
generous whitespace) but with LiftLog's own palette.

---

## Color tokens

```css
:root {
  --bg:      #FAFAFA;  /* app background — near-white, neutral not warm */
  --surface: #FFFFFF;  /* cards, headers, sheets */
  --card:    #F5F5F7;  /* nested/inset surfaces, controls */
  --border:  #E5E5EA;  /* all hairlines */
  --text:    #1C1C1E;  /* primary text — near-black */
  --muted:   #8E8E93;  /* secondary text, labels */

  --blue:    #4C7FF0;  /* Monday + informational accents */
  --teal:    #2FA89C;  /* Wednesday + warnings (deload due, stall) */
  --green:   #34C759;  /* Friday + success (progression earned, set done) */
  --indigo:  #6C63FF;  /* Home routine + charts/analysis contexts */
  --red:     #FF3B30;  /* destructive only (delete, abandon session) */
}
```

Day accents remap from v1: Monday cyan→blue, Wednesday gold→teal, Friday
green (unchanged), home/analysis violet→indigo. Warnings that were gold
(deload due, stall) now use teal — the same Wednesday-doubles-as-warning
coupling carried over. The internal accent slugs used in code and templates
are `blue` / `teal` / `green` / `indigo` to match.

Rules: day accents color-code routines everywhere they appear (Home card,
Active Workout header, history entries) so the week has a consistent visual
rhythm. Semantic uses (green = progressed) are allowed to coexist with day
coding — context disambiguates. Accents are used for chips, dots, borders,
and small fills (primary buttons carry a full accent fill with white text);
never body text. Note the Apple-system greens/teals are tuned as *fill*
colors: as text on white they read faint, so success signals prefer a fill or
a bordered chip over bare colored text (see the timer "rest done" and chart
notes below).

## Typography

- **UI/body:** Inter, system fallback stack. 15px base, 1.4–1.55 line height.
  Inter is used for **all** UI text — labels, buttons, cues, headers, section
  labels, tab labels, stepper/timer labels.
- **Data only:** JetBrains Mono (ui-monospace fallback) for numeric/tabular
  data ONLY — weights, reps, rest-timer countdown, set counts, targets
  ("3 × 8–10"), the "last time" line, chart axis numbers, the "↑ 62.5" chip.
  Deliberate v2 narrowing: the mono treatment for numbers stays (its column
  alignment is functionally useful), only non-numeric text moved to Inter.
- Section labels: 11px, 700, letter-spacing 0.08em, uppercase, --muted (Inter;
  the wide 0.12em mono spacing tightened for Inter).
- Gym-context floor: nothing interactive below 13px on Active Workout; the
  timer and current weight x reps render 22–28px — readable at arm's length
  on a bench.

## Spacing & shape

- Spacing scale: 4 / 8 / 12 / 16 / 24 / 32.
- Radius: 12px cards, sheets, and the full-width action buttons (a modest bump
  from v1); 8px chips and small controls. Restrained, not aggressively rounded.
- Borders: 1px --border everywhere; no shadows. On the light UI the #E5E5EA
  hairline carries card separation (white cards on near-white --bg), keeping
  the flat, calm look without drop shadows.
- Max content width 560px, centered — phone-first, and on the MacBook it
  becomes a comfortable column rather than a stretched desktop layout.
  Progress/chart screens may widen to 760px.

## Components

**Primary action button** ("DID AS SUGGESTED", "START"): full-width, 56px
tall, day-accent fill with white (#fff) text, Inter, 12px radius,
letter-spaced. One per screen maximum.

**Stepper**: 52px square tap targets, mono value between, long-press
auto-repeat. Unit chip sits against the value; tapping flips kg/lbs. The
item-3 tappability sizing/spacing/chrome rules are unchanged in v2 — only the
color values move to the light palette.

**Tappability rule (applies to every interactive element):** anything
tappable must carry a visible 1px --border AND a --surface or --card
background fill — never bare colored text, never fully transparent. This
covers secondary/tertiary buttons (skip, activate, cancel, delete), the
unit chip, video-link chips, and jump-list row actions. Plain --muted text
is reserved exclusively for genuinely non-interactive labels (section
headers, meta like "3×10"), so the visual language itself signals what can
be tapped. Adjacent tappable elements keep >= 8px of spacing (audited most
carefully where the stepper meets "DID AS SUGGESTED" on Active Workout).
Keep it calm — chrome for clarity, not loud colors.

**Exercise card**: the reference page's expandable row (name + mono meta +
chevron) carries over as the pattern for routine lists and history.

**Rest timer**: full-width bar pinned to the bottom of Active Workout on
--surface, mono countdown, progress line draining in the day accent, [skip]
as a small bordered pill button (secondary weight, but unmistakably a button —
not a bare text link). v2 light-theme adjustment: the line is thickened to 4px
in a light --border track (a 2px hairline that read on near-black does not
read on white), and the "rest done" countdown turns --text rather than green
(Apple green as text on white is too faint) while the green signal stays in
the fill line and the end flash. Timer end: green flash + vibration (where
supported).

**Bottom tab bar** — a **floating glassmorphic pill** (Hevy-style; this is the
settled v2 spec, it has drifted a few times — do not revert it to a docked or
dark bar). Four equal-width tabs (Home, Workout, Exercises, Profile), each an
icon above an Inter lowercase label. Exact spec:

- **Position:** `position: fixed`, floating — NOT full-width/edge-to-edge.
  Horizontal: ~16px clear of both screen edges (`left: 50%; transform:
  translateX(-50%); width: calc(100% - 32px); max-width: 460px` — so it keeps
  16px gutters on a phone and caps its width on desktop). Bottom:
  `calc(env(safe-area-inset-bottom) + 14px)` so it floats clear of the home
  indicator.
- **Shape:** fully-rounded capsule, `border-radius: 30px` (reads as a pill at
  the ~56px bar height).
- **Background / glass:** `background: rgba(255,255,255,0.75)` with BOTH
  `-webkit-backdrop-filter: blur(20px)` AND `backdrop-filter: blur(20px)`. The
  `-webkit-` prefix is REQUIRED for the blur to render on iOS Safari/PWA — never
  drop it. Content scrolls under the pill and shows through the frost.
- **Border:** subtle `1px solid rgba(255,255,255,0.4)` for a glass edge/
  definition against busy content behind the blur.
- **Shadow:** soft floating lift `0 4px 24px rgba(0,0,0,0.08)` — gentle, not a
  hard drop shadow; this also carries edge-definition against the light bg.
- **Active tab:** icon + label in --indigo (the home/analysis accent). Inactive
  tabs: --muted. Color ALONE signals active — no background fill, no pill-behind-
  the-icon highlight. Do NOT introduce a fifth color. (The tabs are global nav,
  not day-specific, so the single home/analysis accent is "the relevant day
  accent" here — not a per-tab rainbow.)
- **Stacking:** `z-index: 5` — above scrolling content but BELOW the sheet
  backdrop (10) / sheet (11), so an open bottom sheet cleanly covers the pill
  instead of the pill floating on top of it.

It is present on Home/Workout/Exercises/Profile (and Exercise Detail, Finish
Summary), and cleanly UNMOUNTED — not CSS-hidden — during Active Workout and
login so those screens keep full-screen focus. The shell reserves 120px bottom
padding so content can scroll clear of the floating pill.

**Sheets** (jump list, substitution picker): bottom sheets on --surface,
drag handle, same card idiom inside.

**Charts** (Progress screens): single-series line on --indigo, 2.5px stroke
(bumped from v1's 2px so a saturated line still reads on white),
no fills/gradients, mono axis labels in --muted, PR dots in --indigo. Deload
weeks rendered as muted dashed segments.

## Motion

Inherited restraint: 150–250ms ease transitions on expansion, sheet slide-in,
tab fade. One celebratory moment only — finishing a workout gets a brief
summary reveal animation. Respect prefers-reduced-motion by disabling all of
it. Nothing bounces.

## Writing rules (interface copy)

Mono-label voice: short, factual, lowercase-calm. "3 sessions this week",
"deload week — weights pre-set", "stalled: try 54 kg". Buttons say what they
do: START, FINISH WORKOUT, IMPORT ROUTINES. No exclamation marks, no coach
persona, no "crushing it". The app states facts; the lifting is the
motivation.

## Signature element

The progression marker: a small mono "↑ 62.5" chip in --green that appears
on any exercise that earned a weight increase — on the Home card ("2 lifts
ready to progress ↑"), the Active Workout header, and history rows. It is
the one recurring symbol of the app's whole purpose, and the only place the
UI is allowed to feel pleased.
