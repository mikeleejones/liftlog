# Workout Tracker — Design Language (Step 5)

Direction: inherited from the back-routine reference page. Dark, calm,
gym-legible. The aesthetic risk stays where it was: near-black surfaces with
per-context accent colors and monospace data, everything else quiet.

---

## Color tokens

```css
:root {
  --bg:      #0c0e13;  /* app background */
  --surface: #13161d;  /* cards, headers, sheets */
  --card:    #191d26;  /* nested/expanded surfaces */
  --border:  #242830;  /* all hairlines */
  --text:    #E4E7ED;  /* primary text */
  --muted:   #7b8492;  /* secondary text, labels */

  --cyan:    #5BC8F5;  /* Monday + informational accents */
  --gold:    #C9A96E;  /* Wednesday + warnings (deload due) */
  --green:   #4DB88A;  /* Friday + success (progression earned, set done) */
  --violet:  #9D8CFF;  /* Home routine + charts/analysis contexts */
  --red:     #E06C6C;  /* destructive only (delete, abandon session) */
}
```

Rules: day accents color-code routines everywhere they appear (Home card,
Active Workout header, history entries) so the week has a consistent visual
rhythm. Semantic uses (green = progressed) are allowed to coexist with day
coding — context disambiguates. Accents are used for chips, dots, borders,
and fills on small elements only; never large fills, never body text.

## Typography

- **UI/body:** Inter, system fallback stack. 15px base, 1.4–1.55 line height.
- **Data/labels:** JetBrains Mono (ui-monospace fallback) for anything
  numeric or structural: weights, reps, timers, targets, set counts, section
  labels, tab labels. Mono is the app's voice for facts; Inter for prose.
- Section labels: 11px, 700, letter-spacing 0.12em, uppercase, --muted.
- Gym-context floor: nothing interactive below 13px on Active Workout; the
  timer and current weight x reps render 22–28px — readable at arm's length
  on a bench.

## Spacing & shape

- Spacing scale: 4 / 8 / 12 / 16 / 24 / 32.
- Radius: 12px cards and sheets, 10px buttons and chips, 8px small controls.
- Borders: 1px --border everywhere; no shadows (flat dark UI, shadows read
  as mud on #0c0e13).
- Max content width 560px, centered — phone-first, and on the MacBook it
  becomes a comfortable column rather than a stretched desktop layout.
  Progress/chart screens may widen to 760px.

## Components

**Primary action button** ("DID AS SUGGESTED", "START"): full-width, 56px
tall, day-accent fill with --bg text, mono, letter-spaced. One per screen
maximum.

**Stepper**: 52px square tap targets, mono value between, long-press
auto-repeat. Unit chip sits against the value; tapping flips kg/lbs.

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

**Rest timer**: full-width bar pinned to the bottom of Active Workout, mono
countdown, thin progress line draining in the day accent, [skip] as a small
bordered pill button (secondary weight, but unmistakably a button — not a
bare text link). Timer end: green flash + vibration (where supported).

**Bottom tab bar** (item 10): the app's primary navigation — four
equal-width tabs (Home, Workout, Exercises, Profile), each an icon above a
mono lowercase label. Fixed to the bottom of the viewport on --surface with
a 1px --border top hairline (the same card-border treatment), inner content
capped at the 560px column and centered so it doesn't stretch on desktop.
Inactive tabs are --muted; the active tab uses --violet (the existing
home/analysis accent — reuse its visual weight, do NOT introduce a fifth
color). Respects the safe-area inset at the bottom. It is present on
Home/Workout/Exercises/Profile (and Exercise Detail, Finish Summary), and
cleanly UNMOUNTED — not CSS-hidden — during Active Workout and login so those
screens keep full-screen focus. The shell already reserves bottom padding to
clear it.

**Sheets** (jump list, substitution picker): bottom sheets on --surface,
drag handle, same card idiom inside.

**Charts** (Progress screens): single-series line on --violet, 2px stroke,
no fills/gradients, mono axis labels in --muted, dots only on data points
that were PRs. Deload weeks rendered as muted dashed segments.

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
