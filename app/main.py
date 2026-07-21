import json
import secrets
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import ai, auth, charts, exporter, importer, progression
from .config import SECRET
from .db import can_make_ai_call, get_db, init_db, run_week_completion, sessions_required, utcnow

if not SECRET:
    sys.exit("LIFTLOG_SECRET is not set. Put it in the environment or a .env file, then restart.")

APP_DIR = Path(__file__).resolve().parent
app = FastAPI()
app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")


def _asset_version() -> str:
    """A cache-busting stamp appended to static asset URLs (?v=...). Derived from
    the newest mtime across static/, computed once at startup — a redeploy touches
    the files and restarts the server, so browsers fetch fresh CSS/JS instead of a
    heuristically-cached stale copy (StaticFiles sends no Cache-Control)."""
    try:
        newest = max(p.stat().st_mtime for p in (APP_DIR / "static").glob("*") if p.is_file())
        return str(int(newest))
    except (OSError, ValueError):
        return "1"


ASSET_VERSION = _asset_version()


def base_path(request: Request) -> str:
    """The proxy prefix this app is mounted under (e.g. '/liftlog' when run
    with uvicorn --root-path /liftlog), or '' when served at the domain root.
    Every absolute URL sent to the browser must be prefixed with this so it
    resolves to a path the reverse proxy actually forwards."""
    return request.scope.get("root_path", "")


def redirect(request: Request, path: str, status_code: int = 303) -> RedirectResponse:
    return RedirectResponse(base_path(request) + path, status_code=status_code)


def _mini_workout(request):
    """The open session's mini-bar payload, available to EVERY template so a
    minimized workout stays visible across all four tabs (BACKLOG item 20).

    A context processor rather than something each route passes: the mini-bar is
    global chrome like the tab bar, and threading it through six handlers is how
    it ends up missing from the seventh. base.html only renders it on tabbed
    screens, so Active Workout (which is the full view) and login never show it.
    Same 12h cutoff as Home's resume card — an abandoned session stops being
    'in progress' (decision #9)."""
    if not auth.is_authed(request):
        return {"mini_workout": None}
    db = get_db()
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=12)).strftime("%Y-%m-%dT%H:%M:%SZ")
    row = db.execute(
        "SELECT w.id, w.started_at, r.name AS routine_name FROM workout w "
        "LEFT JOIN routine r ON r.id = w.routine_id "
        "WHERE w.finished_at IS NULL AND w.started_at >= ? ORDER BY w.started_at DESC LIMIT 1",
        (cutoff,),
    ).fetchone()
    db.close()
    if row is None:
        return {"mini_workout": None}
    name = row["routine_name"] or "ad-hoc session"
    return {"mini_workout": {
        "id": row["id"],
        "started_at": row["started_at"],
        "routine_name": name,
        "accent": accent_for(name),
    }}


# makes {{ base }}, {{ asset_v }} and {{ mini_workout }} available in every
# template for URL prefixing, static-asset cache-busting and the minimized-
# session bar
templates = Jinja2Templates(
    directory=APP_DIR / "templates",
    context_processors=[
        lambda request: {"base": base_path(request), "asset_v": ASSET_VERSION},
        _mini_workout,
    ],
)

init_db()

DAY_ACCENTS = {"Mon": "blue", "Wed": "teal", "Fri": "green"}


def accent_for(routine_name: str) -> str:
    return DAY_ACCENTS.get(routine_name[:3], "indigo")


KG_PER_LB = 0.45359237


def to_display(kg: float, unit: str) -> float:
    return kg / KG_PER_LB if unit == "lbs" else kg


def fmt_weight(kg: float, unit: str) -> str:
    return f"{round(to_display(kg, unit), 2):g}"


M_PER_KM = 1000.0
M_PER_MI = 1609.344


def distance_display(m: float, unit: str) -> float:
    if unit == "mi":
        return m / M_PER_MI
    if unit == "km":
        return m / M_PER_KM
    return m


def fmt_distance(m: float, unit: str) -> str:
    return f"{round(distance_display(m, unit), 2):g}"


def fmt_duration(seconds: float) -> str:
    seconds = int(round(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


# the metric that drives an exercise's chart/history "top" and PR line
PRIMARY_METRIC = {
    "weight_reps": "weight_kg",
    "reps_only": "reps",
    "duration": "duration_seconds",
    "duration_weight": "weight_kg",
    "distance": "distance_m",
    "distance_weight": "distance_m",
    "none": None,
}


# which set_log metric columns each exercise_type populates — the server-side
# mirror of workout.js's TYPE_AXES. Anything outside a type's axes is stored
# NULL, so an edit can never populate a column the type doesn't use.
SET_AXES = {
    "weight_reps": ("weight_kg", "reps"),
    "reps_only": ("reps",),
    "duration": ("duration_seconds",),
    "duration_weight": ("weight_kg", "duration_seconds"),
    "distance": ("distance_m",),
    "distance_weight": ("distance_m", "weight_kg"),
    "none": (),
}


def metric_label(exercise_type: str, unit: str) -> str:
    """Axis/suffix label for an exercise's primary metric."""
    if exercise_type in ("weight_reps", "duration_weight"):
        return unit
    if exercise_type == "reps_only":
        return "reps"
    if exercise_type == "duration":
        return ""  # mm:ss is self-describing
    if exercise_type in ("distance", "distance_weight"):
        return unit
    return ""


def fmt_primary(exercise_type: str, value, unit: str) -> str:
    """Bare human string for an exercise's primary metric value (weight, reps,
    duration, or distance) in its display unit — no unit suffix; pair with
    metric_label(). Duration self-describes as mm:ss."""
    if value is None:
        return "—"
    if exercise_type in ("weight_reps", "duration_weight"):
        return fmt_weight(value, unit)
    if exercise_type == "reps_only":
        return str(int(value))
    if exercise_type == "duration":
        return fmt_duration(value)
    if exercise_type in ("distance", "distance_weight"):
        return fmt_distance(value, unit)
    return ""


def primary_chart_value(exercise_type: str, value, unit: str) -> float:
    """Numeric value plotted on the Exercise Detail chart, in display terms."""
    if value is None:
        return 0.0
    if exercise_type in ("weight_reps", "duration_weight"):
        return to_display(value, unit)
    if exercise_type in ("distance", "distance_weight"):
        return distance_display(value, unit)
    return float(value)


def set_cell(exercise_type: str, row, unit: str):
    """(cell_text, unit_suffix) for one logged set. weight_reps keeps its
    'W × R' cell plus a shared unit suffix (unchanged look); other types embed
    their own units inline and carry no suffix."""
    if exercise_type == "weight_reps":
        return f"{fmt_weight(row['weight_kg'], unit)} × {row['reps']}", unit
    if exercise_type == "reps_only":
        return f"{row['reps']}", "reps"
    if exercise_type == "duration":
        return fmt_duration(row["duration_seconds"]), ""
    if exercise_type == "distance":
        return f"{fmt_distance(row['distance_m'], unit)} {unit}", ""
    if exercise_type == "duration_weight":
        return f"{fmt_weight(row['weight_kg'], unit)}{unit} · {fmt_duration(row['duration_seconds'])}", ""
    if exercise_type == "distance_weight":
        return f"{fmt_distance(row['distance_m'], unit)}{unit} · {fmt_weight(row['weight_kg'], 'kg')}kg", ""
    return "done", ""  # none


def _last_text(exercise_type: str, sets, unit: str) -> str:
    """Compact one-line summary of a past session's working sets, in display
    units, for the Active Workout 'last time' line (BACKLOG item 13). weight_reps
    states the weight once when it was uniform (e.g. '60 kg × 10,10,10'), matching
    the original wireframe; other types join per-set cells."""
    if exercise_type == "weight_reps":
        reps = ",".join(str(int(s["reps"])) for s in sets)
        weights = {s["weight_kg"] for s in sets}
        if len(weights) == 1:
            return f"{fmt_weight(sets[0]['weight_kg'], unit)} {unit} × {reps}"
        return ", ".join(f"{fmt_weight(s['weight_kg'], unit)}×{int(s['reps'])}" for s in sets)
    if exercise_type == "reps_only":
        return ",".join(str(int(s["reps"])) for s in sets) + " reps"
    if exercise_type == "duration":
        return ", ".join(fmt_duration(s["duration_seconds"]) for s in sets)
    if exercise_type == "distance":
        return ", ".join(f"{fmt_distance(s['distance_m'], unit)} {unit}" for s in sets)
    if exercise_type == "duration_weight":
        return ", ".join(f"{fmt_weight(s['weight_kg'], unit)}{unit}·{fmt_duration(s['duration_seconds'])}" for s in sets)
    if exercise_type == "distance_weight":
        return ", ".join(f"{fmt_distance(s['distance_m'], unit)}{unit}·{fmt_weight(s['weight_kg'], 'kg')}kg" for s in sets)
    return ""


def last_session_summary(db, exercise, exclude_workout_id):
    """The most recent non-deload session's working sets for this exercise as
    {'text', 'date'}, or None if never done (BACKLOG item 13). This is factual
    history shown mid-set, so — like charts and Exercise Detail — it ignores
    progress_reset_at; it is not a suggestion. 'none'-type exercises have nothing
    to show."""
    if exercise["exercise_type"] == "none":
        return None
    row = db.execute(
        "SELECT w.id AS wid, w.started_at FROM set_log s "
        "JOIN workout w ON w.id = s.workout_id "
        "WHERE s.exercise_id = ? AND s.set_type = 'normal' AND w.is_deload = 0 "
        "AND w.id != ? ORDER BY w.started_at DESC, w.id DESC LIMIT 1",
        (exercise["id"], exclude_workout_id or 0),
    ).fetchone()
    if row is None:
        return None
    sets = db.execute(
        "SELECT weight_kg, reps, duration_seconds, distance_m FROM set_log "
        "WHERE workout_id = ? AND exercise_id = ? AND set_type = 'normal' "
        "ORDER BY set_number",
        (row["wid"], exercise["id"]),
    ).fetchall()
    if not sets:
        return None
    # 'sets' carries the raw canonical metrics alongside the pre-formatted text:
    # Active Workout re-derives the line client-side so it follows the unit chip
    # (BACKLOG item 17), while server-rendered screens use 'text' directly.
    return {"text": _last_text(exercise["exercise_type"], sets, exercise["display_unit"]),
            "sets": [{k: r[k] for k in ("weight_kg", "reps", "duration_seconds", "distance_m")}
                     for r in sets],
            "date": row["started_at"][:10]}


def _suggest_text(exercise_type: str, s, unit: str) -> str:
    """The computed suggestion as one line in display units, mirroring
    _last_text's shape so Home's 'last … · next …' pair reads on the same axes.
    Double progression advances the REP target on most sessions and the load only
    when the top of the range was cleared, so weight_reps must state both axes —
    a weight-only 'next' looks identical to 'last' whenever reps are what moved,
    which is what made the engine look stuck (BACKLOG item 16)."""
    w, reps = s["weight_kg"], s["reps"]
    secs, dist = s["duration_seconds"], s["distance_m"]
    if exercise_type == "weight_reps":
        if w is None or reps is None:
            return "—"
        return f"{fmt_weight(w, unit)} {unit} × {int(reps)}"
    if exercise_type == "reps_only":
        return f"{int(reps)} reps" if reps is not None else "—"
    if exercise_type == "duration":
        return fmt_duration(secs) if secs is not None else "—"
    if exercise_type == "distance":
        return f"{fmt_distance(dist, unit)} {unit}" if dist is not None else "—"
    if exercise_type == "duration_weight":
        if w is None or secs is None:
            return "—"
        return f"{fmt_weight(w, unit)}{unit}·{fmt_duration(secs)}"
    if exercise_type == "distance_weight":
        if w is None or dist is None:
            return "—"
        return f"{fmt_distance(dist, unit)}{unit}·{fmt_weight(w, 'kg')}kg"
    return "—"  # none: a completion record has nothing to suggest


def parse_ts(ts: str) -> datetime:
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def _like_escape(term: str) -> str:
    """Escape LIKE wildcards so a search term is matched literally (paired with
    ESCAPE '\\' in the query)."""
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def login_redirect(request: Request) -> RedirectResponse:
    return redirect(request, "/login")


def token_or_cookie_authed(request: Request, db) -> bool:
    """True for a valid browser cookie OR a valid 'Authorization: Bearer <token>'
    header matching an api_token row. On a successful token match, last_used_at is
    bumped. The browser cookie flow is unchanged; this is purely additive for
    endpoints that opt in (BACKLOG item 7). Callers pass an open db."""
    if auth.is_authed(request):
        return True
    token = auth.bearer_token(request)
    if not token:
        return False
    row = db.execute("SELECT id FROM api_token WHERE token = ?", (token,)).fetchone()
    if row is None:
        return False
    db.execute("UPDATE api_token SET last_used_at = ? WHERE id = ?", (utcnow(), row["id"]))
    db.commit()
    return True


# ---- auth ----

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    if auth.is_authed(request):
        return redirect(request, "/")
    return templates.TemplateResponse(request, "login.html", {"error": False})


@app.post("/login")
def login(request: Request, secret: str = Form("")):
    if not auth.secret_matches(secret):
        return templates.TemplateResponse(
            request, "login.html", {"error": True}, status_code=401
        )
    resp = redirect(request, "/")
    resp.set_cookie(
        auth.COOKIE_NAME, auth.cookie_value(),
        max_age=auth.COOKIE_MAX_AGE, httponly=True, samesite="lax",
        path=base_path(request) or "/",
    )
    return resp


# ---- home ----

def _program_overview(db, active, program_week):
    """Program-level lift overview folded into Home from the old standalone
    Progress screen (BACKLOG item 10): each current-week lift's last vs suggested
    value and progress/stall kind, plus the honesty audit. Read-only."""
    lifts = []
    if active:
        rows = db.execute(
            "SELECT re.target_sets, re.rep_min, re.rep_max, e.* FROM routine_exercise re "
            "JOIN exercise e ON e.id = re.exercise_id "
            "JOIN routine r ON r.id = re.routine_id "
            "WHERE r.program_id = ? AND r.week_number = ? AND r.is_archived = 0 "
            "ORDER BY r.position, re.position",
            (active["id"], program_week),
        ).fetchall()
        seen = set()
        for re in rows:
            if re["id"] in seen:
                continue
            seen.add(re["id"])
            etype = re["exercise_type"]
            unit = re["display_unit"]
            primary = PRIMARY_METRIC[etype]
            s = progression.suggest(db, re, re["target_sets"], re["rep_min"], re["rep_max"])
            # the whole last session, not its final set: a weight-only "last" hid
            # both the rep count and mixed-weight sessions, which is what made
            # "last 115 · next 115" look like a broken engine (BACKLOG item 16).
            last = last_session_summary(db, re, None)
            lifts.append({
                "id": re["id"],
                "name": re["name"],
                "last": last["text"] if last else "—",
                "next": _suggest_text(etype, s, unit),
                # compact primary-metric value for the progress/stall chip only
                "suggest": fmt_primary(etype, s[primary], unit) if primary else "—",
                "kind": s["kind"],
            })
    # Actionable lifts first — progress-ready, then stalled — each group keeping
    # its program order (sort is stable). The list runs to every lift in the
    # week, mobility work included, so without this the two or three rows worth
    # acting on sit wherever the routine happens to put them (item 21). Nothing
    # is hidden; only the order changes.
    lifts.sort(key=lambda l: {"progress": 0, "stall": 1}.get(l["kind"], 2))
    # honesty audit (decision 10): share of working sets logged as-suggested
    audit = db.execute(
        "SELECT COUNT(*) AS total, COALESCE(SUM(was_suggested), 0) AS suggested "
        "FROM set_log WHERE set_type = 'normal'"
    ).fetchone()
    suggested_pct = round(100 * audit["suggested"] / audit["total"]) if audit["total"] else None
    return {
        "lifts": lifts,
        "ready": sum(1 for l in lifts if l["kind"] == "progress"),
        "suggested_pct": suggested_pct,
        "audit_total": audit["total"],
    }


def _volume_history(db, limit=12):
    """Total tonnage per completed session, oldest first, for Home's volume
    chart (BACKLOG item 21).

    Volume is defined exactly as the TCX and latest-workout endpoints define it
    — weight x reps over working sets of weight_reps exercises — so the number
    on Home always agrees with the one those export. Sessions with no
    weight_reps work at all (a mobility-only day) are left out rather than
    plotted as a zero: they weren't zero-effort sessions, they just have no
    tonnage to compare, and a 0 would flatten the whole series.

    A 'PR' here is a volume record: strictly above every earlier session's, with
    deload weeks unable to earn one — the same rule Exercise Detail's chart uses
    for its top-set PRs."""
    rows = db.execute(
        "SELECT w.id, w.started_at, w.is_deload, r.name AS routine_name, "
        "  (SELECT COALESCE(SUM(s.weight_kg * s.reps), 0) FROM set_log s "
        "   JOIN exercise e ON e.id = s.exercise_id "
        "   WHERE s.workout_id = w.id AND s.set_type = 'normal' "
        "     AND e.exercise_type = 'weight_reps' "
        "     AND s.weight_kg IS NOT NULL AND s.reps IS NOT NULL) AS volume "
        "FROM workout w LEFT JOIN routine r ON r.id = w.routine_id "
        "WHERE w.finished_at IS NOT NULL "
        "ORDER BY w.started_at DESC, w.id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    sessions = [r for r in reversed(rows) if r["volume"] > 0]
    best = None
    points = []
    for r in sessions:
        volume = round(r["volume"])
        is_pr = (not r["is_deload"]) and (best is None or volume > best)
        if is_pr:
            best = volume
        points.append({
            "value": volume,
            "is_pr": is_pr,
            "is_deload": bool(r["is_deload"]),
            "label": r["started_at"][5:10],
        })
    return points


DAY_LETTERS = ("M", "T", "W", "T", "F", "S", "S")


def _completion_calendar(db, weeks=3):
    """Day-cell grid of completed sessions for the last `weeks` weeks, ending
    with the current (Mon-Sun) week (BACKLOG item 21). A filled cell carries the
    routine's own day accent, so the grid reads as the same colour language as
    the routine cards; an ad-hoc session with no routine falls back to the
    indigo home/analysis accent.

    Dates come from started_at[:10] — UTC, matching every other date the app
    shows (Exercise Detail history, the chart labels) rather than introducing a
    second, inconsistent notion of what day a session happened on."""
    today = datetime.now(timezone.utc).date()
    week_start = today - timedelta(days=today.weekday())
    first = week_start - timedelta(weeks=weeks - 1)
    rows = db.execute(
        "SELECT w.started_at, r.name AS routine_name FROM workout w "
        "LEFT JOIN routine r ON r.id = w.routine_id "
        "WHERE w.finished_at IS NOT NULL AND w.started_at >= ? "
        "ORDER BY w.started_at",
        (first.strftime("%Y-%m-%dT00:00:00Z"),),
    ).fetchall()
    done = {}
    for r in rows:
        # first session of a day owns the cell's colour; a second same-day
        # session doesn't get its own cell (the grid is one cell per day)
        done.setdefault(r["started_at"][:10], accent_for(r["routine_name"] or ""))
    grid = []
    for w in range(weeks):
        cells = []
        for d in range(7):
            day = first + timedelta(weeks=w, days=d)
            iso = day.isoformat()
            cells.append({
                "date": iso,
                "day_letter": DAY_LETTERS[d],
                "day_number": day.day,
                "accent": done.get(iso),
                "is_today": day == today,
                "is_future": day > today,
            })
        grid.append(cells)
    return grid


def _quick_start_cards(db, active, program_week):
    """The current program week's routines as day-accented START cards (with a
    'N lifts ready ↑' chip). This is the session-start shortcut — it lives on the
    Workout tab (BACKLOG item 10 puts session-starting there). With no active
    program, every unarchived routine is offered."""
    if active:
        routines = db.execute(
            "SELECT r.*, COUNT(re.id) AS exercise_count FROM routine r "
            "LEFT JOIN routine_exercise re ON re.routine_id = r.id "
            "WHERE r.is_archived = 0 AND r.program_id = ? AND r.week_number = ? "
            "GROUP BY r.id ORDER BY r.position, r.id",
            (active["id"], program_week),
        ).fetchall()
    else:
        routines = db.execute(
            "SELECT r.*, COUNT(re.id) AS exercise_count FROM routine r "
            "LEFT JOIN routine_exercise re ON re.routine_id = r.id "
            "WHERE r.is_archived = 0 GROUP BY r.id ORDER BY r.position, r.id"
        ).fetchall()
    cards = []
    for r in routines:
        ready = 0
        for re in db.execute(
            "SELECT re.target_sets, re.rep_min, re.rep_max, e.* FROM routine_exercise re "
            "JOIN exercise e ON e.id = re.exercise_id WHERE re.routine_id = ?",
            (r["id"],),
        ).fetchall():
            s = progression.suggest(db, re, re["target_sets"], re["rep_min"], re["rep_max"])
            if s["kind"] == "progress":
                ready += 1
        cards.append(dict(r, accent=accent_for(r["name"]), progress_ready=ready))
    return cards


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    if not auth.is_authed(request):
        return login_redirect(request)
    db = get_db()
    run_week_completion(db)
    state = db.execute("SELECT * FROM program_state WHERE id = 1").fetchone()
    active = db.execute("SELECT * FROM program WHERE is_active = 1").fetchone()
    required, _ = sessions_required(db, state["program_week"])
    sessions_this_week = db.execute(
        "SELECT COUNT(*) FROM workout WHERE finished_at IS NOT NULL AND started_at >= ?",
        (state["week_anchor"],),
    ).fetchone()[0]
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=12)).strftime("%Y-%m-%dT%H:%M:%SZ")
    in_progress = db.execute(
        "SELECT w.id, w.started_at, r.name AS routine_name FROM workout w "
        "LEFT JOIN routine r ON r.id = w.routine_id "
        "WHERE w.finished_at IS NULL AND w.started_at >= ? ORDER BY w.started_at DESC LIMIT 1",
        (cutoff,),
    ).fetchone()

    now = utcnow()
    deload = progression.deload_active(db, now)
    deload_deferred = bool(
        state["weeks_since_deload"] >= 3
        and state["deload_deferred_until"]
        and state["deload_deferred_until"] > now
    )

    overview = _program_overview(db, active, state["program_week"])
    volume_points = _volume_history(db)
    calendar = _completion_calendar(db)
    db.close()
    latest_volume = volume_points[-1]["value"] if volume_points else None
    return templates.TemplateResponse(request, "home.html", {
        "active_tab": "home",
        "sessions_this_week": sessions_this_week,
        "sessions_required": required,
        "volume_chart": charts.line_chart(volume_points),
        "latest_volume": f"{latest_volume:,}" if latest_volume is not None else None,
        "volume_is_pr": bool(volume_points and volume_points[-1]["is_pr"]),
        "calendar": calendar,
        "weeks_to_deload": max(0, 3 - state["weeks_since_deload"]),
        "stalled": sum(1 for l in overview["lifts"] if l["kind"] == "stall"),
        "program": active,
        "program_week": state["program_week"],
        "completed_weeks": state["completed_weeks"],
        "weeks_since_deload": state["weeks_since_deload"],
        "deload": deload,
        "deload_deferred": deload_deferred,
        "in_progress": in_progress,
        "in_progress_accent": accent_for(in_progress["routine_name"] or "") if in_progress else None,
        **overview,
    })


@app.post("/deload/defer")
def defer_deload(request: Request):
    if not auth.is_authed(request):
        return login_redirect(request)
    db = get_db()
    state = db.execute("SELECT week_anchor FROM program_state WHERE id = 1").fetchone()
    until = (parse_ts(state["week_anchor"]) + timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
    db.execute("UPDATE program_state SET deload_deferred_until = ? WHERE id = 1", (until,))
    db.commit()
    db.close()
    return redirect(request, "/")


# ---- routines + import ----

def _program_groups(db, archived=False):
    """Programs (active first) with their routines grouped by week, plus any
    standalone routines. `archived` selects the archived view (is_archived = 1)
    instead of the default active view."""
    flag = 1 if archived else 0
    groups = []
    programs = db.execute(
        "SELECT * FROM program ORDER BY is_active DESC, name"
    ).fetchall()
    state = db.execute("SELECT program_week FROM program_state WHERE id = 1").fetchone()
    for p in programs:
        routines = db.execute(
            "SELECT r.*, COUNT(re.id) AS exercise_count FROM routine r "
            "LEFT JOIN routine_exercise re ON re.routine_id = r.id "
            "WHERE r.program_id = ? AND r.is_archived = ? "
            "GROUP BY r.id ORDER BY r.week_number, r.position, r.id",
            (p["id"], flag),
        ).fetchall()
        if not routines:
            continue
        weeks = []
        for r in routines:
            if not weeks or weeks[-1]["number"] != r["week_number"]:
                weeks.append({"number": r["week_number"], "routines": []})
            weeks[-1]["routines"].append(dict(r, accent=accent_for(r["name"])))
        groups.append({
            "program": p,
            "weeks": weeks,
            "current_week": state["program_week"] if p["is_active"] else None,
        })
    standalone = db.execute(
        "SELECT r.*, COUNT(re.id) AS exercise_count FROM routine r "
        "LEFT JOIN routine_exercise re ON re.routine_id = r.id "
        "WHERE r.program_id IS NULL AND r.is_archived = ? "
        "GROUP BY r.id ORDER BY r.position, r.id",
        (flag,),
    ).fetchall()
    return groups, [dict(r, accent=accent_for(r["name"])) for r in standalone]


def _routines_context(db, imported=0, view="active"):
    archived = view == "archived"
    groups, standalone = _program_groups(db, archived=archived)
    return {
        "active_tab": "workout",
        "view": "archived" if archived else "active",
        "archived": archived,
        "groups": groups,
        "standalone": standalone,
        "imported": imported,
    }


@app.get("/routines", response_class=HTMLResponse)
def routines_page(request: Request, imported: int = 0, view: str = "active"):
    if not auth.is_authed(request):
        return login_redirect(request)
    db = get_db()
    run_week_completion(db)
    context = _routines_context(db, imported=imported, view=view)
    if not context["archived"]:
        # session-start shortcut cards live here now (moved off Home)
        state = db.execute("SELECT * FROM program_state WHERE id = 1").fetchone()
        active = db.execute("SELECT * FROM program WHERE is_active = 1").fetchone()
        context.update({
            "quick_start": _quick_start_cards(db, active, state["program_week"]),
            "program": active,
            "program_week": state["program_week"],
            "deload": progression.deload_active(db, utcnow()),
        })
    db.close()
    return templates.TemplateResponse(request, "routines.html", context)


def _target_text(exercise_type: str, target_sets, rep_min, rep_max, rest_seconds) -> str:
    """The prescription line for a routine_exercise ('3 × 8–10 · rest 90s'),
    mirroring Active Workout's own target line."""
    if exercise_type == "none":
        return f"mark done · rest {rest_seconds}s"
    reps = str(rep_min) if rep_min == rep_max else f"{rep_min}–{rep_max}"
    return f"{target_sets} × {reps} · rest {rest_seconds}s"


@app.get("/routines/{routine_id}/preview", response_class=HTMLResponse)
def routine_preview(request: Request, routine_id: int):
    """Read-only look at a routine's exercises before committing to a session
    (BACKLOG item 14). Creates no workout and starts no timer — the only way to
    begin a session is the explicit START form (POST /workout/start)."""
    if not auth.is_authed(request):
        return login_redirect(request)
    db = get_db()
    routine = db.execute("SELECT * FROM routine WHERE id = ?", (routine_id,)).fetchone()
    if routine is None:
        db.close()
        return redirect(request, "/routines")
    rows = db.execute(
        "SELECT re.target_sets, re.rep_min, re.rep_max, re.rest_seconds, re.is_primary, "
        "e.name, e.cue, e.exercise_type FROM routine_exercise re "
        "JOIN exercise e ON e.id = re.exercise_id "
        "WHERE re.routine_id = ? ORDER BY re.position",
        (routine_id,),
    ).fetchall()
    db.close()
    exercises = [{
        "name": r["name"],
        "cue": r["cue"],
        "is_primary": bool(r["is_primary"]),
        "target": _target_text(r["exercise_type"], r["target_sets"],
                               r["rep_min"], r["rep_max"], r["rest_seconds"]),
    } for r in rows]
    return templates.TemplateResponse(request, "routine_preview.html", {
        "active_tab": "workout",
        "routine": routine,
        "accent": accent_for(routine["name"]),
        "exercises": exercises,
    })


@app.post("/programs/{program_id}/activate")
def activate_program(request: Request, program_id: int):
    if not auth.is_authed(request):
        return login_redirect(request)
    db = get_db()
    program = db.execute("SELECT * FROM program WHERE id = ?", (program_id,)).fetchone()
    if program and not program["is_active"]:
        db.execute("UPDATE program SET is_active = 0 WHERE id != ?", (program_id,))
        db.execute("UPDATE program SET is_active = 1 WHERE id = ?", (program_id,))
        db.execute("UPDATE program_state SET program_week = 1 WHERE id = 1")
        db.commit()
    db.close()
    return redirect(request, "/routines")


@app.post("/routines/{routine_id}/delete")
def delete_routine(request: Request, routine_id: int):
    if not auth.is_authed(request):
        return login_redirect(request)
    db = get_db()
    # routine_exercise cascades; workout.routine_id is SET NULL, so logged
    # sessions survive as ad-hoc and no set_log history is lost.
    db.execute("DELETE FROM routine WHERE id = ?", (routine_id,))
    db.commit()
    db.close()
    return redirect(request, "/routines")


@app.post("/routines/{routine_id}/archive")
def archive_routine(request: Request, routine_id: int):
    if not auth.is_authed(request):
        return login_redirect(request)
    db = get_db()
    # Soft, reversible: routine_exercise rows and all workout history untouched.
    # Home's "today's routine" logic filters is_archived = 0, so it drops out.
    db.execute(
        "UPDATE routine SET is_archived = 1, updated_at = ? WHERE id = ?",
        (utcnow(), routine_id),
    )
    db.commit()
    db.close()
    return redirect(request, "/routines")


@app.post("/routines/{routine_id}/reactivate")
def reactivate_routine(request: Request, routine_id: int):
    if not auth.is_authed(request):
        return login_redirect(request)
    db = get_db()
    db.execute(
        "UPDATE routine SET is_archived = 0, updated_at = ? WHERE id = ?",
        (utcnow(), routine_id),
    )
    db.commit()
    db.close()
    return redirect(request, "/routines?view=archived")


def _parse_import(raw: str):
    """Returns (payload, errors). payload is None when unusable."""
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as e:
        return None, [f"not valid JSON: {e.msg} (line {e.lineno})"]
    errors = importer.validate(payload)
    return (None, errors) if errors else (payload, [])


@app.post("/routines/import/preview", response_class=HTMLResponse)
def import_preview(request: Request, raw: str = Form("")):
    if not auth.is_authed(request):
        return login_redirect(request)
    payload, errors = _parse_import(raw)
    if errors:
        # import lives on the Profile tab now — re-render it with the errors + raw
        db = get_db()
        context = _settings_context(db, import_errors=errors, import_raw=raw)
        db.close()
        return templates.TemplateResponse(request, "settings.html", context, status_code=422)
    db = get_db()
    plan = importer.plan(db, importer.normalize(payload))
    db.close()
    return templates.TemplateResponse(request, "import_preview.html", {
        "plan": plan,
        "raw": raw,
    })


@app.post("/routines/import/apply")
def import_apply(request: Request, raw: str = Form("")):
    if not auth.is_authed(request):
        return login_redirect(request)
    payload, errors = _parse_import(raw)
    if errors:
        return redirect(request, "/settings")
    db = get_db()
    importer.apply_import(db, importer.normalize(payload), utcnow())
    db.commit()
    db.close()
    return redirect(request, "/routines?imported=1")


@app.get("/exercises", response_class=HTMLResponse)
def exercises_page(request: Request, q: str = ""):
    if not auth.is_authed(request):
        return login_redirect(request)
    db = get_db()
    query = q.strip()
    if query:
        exercises = db.execute(
            "SELECT * FROM exercise WHERE is_archived = 0 AND name LIKE ? ESCAPE '\\' "
            "ORDER BY name COLLATE NOCASE",
            (f"%{_like_escape(query)}%",),
        ).fetchall()
    else:
        exercises = db.execute(
            "SELECT * FROM exercise WHERE is_archived = 0 ORDER BY name COLLATE NOCASE"
        ).fetchall()
    db.close()
    return templates.TemplateResponse(request, "exercises.html", {
        "active_tab": "exercises",
        "exercises": exercises,
        "q": query,
    })


# ---- progress + exercise detail + settings ----

def _exercise_history(db, exercise):
    """Per-workout summary for one exercise (working sets only), oldest first,
    with the type's primary-metric top, date, deload flag, and PR marks. A PR is
    a top value strictly above every earlier session's top. Charts and history
    ignore progress_reset_at — full history is always shown."""
    exercise_id = exercise["id"]
    etype = exercise["exercise_type"]
    unit = exercise["display_unit"]
    primary = PRIMARY_METRIC[etype]
    rows = db.execute(
        "SELECT w.id AS wid, w.started_at, w.is_deload, s.id AS sid, "
        "s.weight_kg, s.reps, s.duration_seconds, s.distance_m "
        "FROM set_log s JOIN workout w ON w.id = s.workout_id "
        "WHERE s.exercise_id = ? AND s.set_type = 'normal' "
        "ORDER BY w.started_at, w.id, s.set_number",
        (exercise_id,),
    ).fetchall()
    sessions = []
    for r in rows:
        if not sessions or sessions[-1]["wid"] != r["wid"]:
            sessions.append({
                "wid": r["wid"], "started_at": r["started_at"],
                "is_deload": bool(r["is_deload"]), "sets": [], "top": None,
            })
        s = sessions[-1]
        s["sets"].append(r)
        if primary is not None and r[primary] is not None:
            s["top"] = r[primary] if s["top"] is None else max(s["top"], r[primary])
    best = None
    history = []
    for s in sessions:
        top = s["top"]
        is_pr = (not s["is_deload"]) and top is not None and (best is None or top > best)
        if is_pr:
            best = top
        history.append({
            "date": s["started_at"][:10],
            "is_deload": s["is_deload"],
            "is_pr": is_pr,
            "top": fmt_primary(etype, top, unit),
            "top_value": primary_chart_value(etype, top, unit) if top is not None else None,
            # one entry per set rather than a joined string: each is individually
            # tappable to correct it after the fact (BACKLOG item 18)
            "sets": [{
                "id": row["sid"],
                "text": set_cell(etype, row, unit)[0],
                "weight_kg": row["weight_kg"],
                "reps": row["reps"],
                "duration_seconds": row["duration_seconds"],
                "distance_m": row["distance_m"],
            } for row in s["sets"]],
        })
    return history


@app.get("/exercise/{exercise_id}", response_class=HTMLResponse)
def exercise_detail(request: Request, exercise_id: int):
    if not auth.is_authed(request):
        return login_redirect(request)
    db = get_db()
    exercise = db.execute("SELECT * FROM exercise WHERE id = ?", (exercise_id,)).fetchone()
    if exercise is None:
        db.close()
        return redirect(request, "/exercises")
    unit = exercise["display_unit"]
    history = _exercise_history(db, exercise)
    db.close()
    # 'none'-type exercises have no metric to chart; skip sessions with no top
    chart = charts.line_chart([
        {"value": h["top_value"], "is_pr": h["is_pr"],
         "is_deload": h["is_deload"], "label": h["date"][5:]}
        for h in history if h["top_value"] is not None
    ])
    etype = exercise["exercise_type"]
    return templates.TemplateResponse(request, "exercise_detail.html", {
        "active_tab": "exercises",
        "exercise": exercise,
        "unit": metric_label(etype, unit),
        "history": list(reversed(history)),
        "chart": chart,
        "youtube_query": exercise["youtube_query"],
        # a 'none'-type set records completion only — nothing to correct
        "editable": bool(SET_AXES[etype]),
        "edit_context": json.dumps({
            "base": base_path(request),
            "exercise_type": etype,
            "display_unit": unit,
            "accent": "indigo",  # Exercise Detail is an analysis context
        }),
    })


@app.post("/exercise/{exercise_id}/reset-progress")
def reset_exercise_progress(request: Request, exercise_id: int):
    if not auth.is_authed(request):
        return login_redirect(request)
    db = get_db()
    # Soft reset: no set_log rows are touched. Only the marker moves, so the
    # progression/stall queries start fresh from the next session while charts
    # and history keep showing everything. Resetting again just moves it forward.
    db.execute(
        "UPDATE exercise SET progress_reset_at = ? WHERE id = ?",
        (utcnow(), exercise_id),
    )
    db.commit()
    db.close()
    return redirect(request, f"/exercise/{exercise_id}")


@app.get("/progress")
def progress_page(request: Request):
    # Progress is no longer a separate screen (BACKLOG item 10) — its content is
    # folded into Home. Redirect keeps old bookmarks / PWA shortcuts working.
    return redirect(request, "/")


def _settings_context(db, new_token=None, import_errors=None, import_raw=""):
    state = db.execute("SELECT * FROM program_state WHERE id = 1").fetchone()
    now = utcnow()
    deload = progression.deload_active(db, now)
    counts = {
        "exercises": db.execute("SELECT COUNT(*) FROM exercise").fetchone()[0],
        "workouts": db.execute(
            "SELECT COUNT(*) FROM workout WHERE finished_at IS NOT NULL"
        ).fetchone()[0],
        "sets": db.execute("SELECT COUNT(*) FROM set_log").fetchone()[0],
    }
    tokens = db.execute(
        "SELECT id, name, created_at, last_used_at FROM api_token ORDER BY created_at DESC, id DESC"
    ).fetchall()
    return {
        "active_tab": "profile",
        "deload": deload,
        "weeks_since_deload": state["weeks_since_deload"],
        "completed_weeks": state["completed_weeks"],
        "deload_deferred": bool(state["deload_deferred_until"] and state["deload_deferred_until"] > now),
        "counts": counts,
        "objective": state["objective"] or "",
        # cleaned for the input's value: '80' not '80.0', '' when unset
        "bodyweight_kg": ("%g" % state["bodyweight_kg"]) if state["bodyweight_kg"] else "",
        "tokens": tokens,
        "new_token": new_token,
        "import_errors": import_errors or [],
        "import_raw": import_raw,
    }


@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request):
    if not auth.is_authed(request):
        return login_redirect(request)
    db = get_db()
    context = _settings_context(db)
    db.close()
    return templates.TemplateResponse(request, "settings.html", context)


@app.post("/settings/tokens", response_class=HTMLResponse)
def create_token(request: Request, name: str = Form("")):
    if not auth.is_authed(request):
        return login_redirect(request)
    db = get_db()
    name = name.strip() or "unnamed token"
    # long random URL-safe string; shown exactly once here and never again
    token = secrets.token_urlsafe(32)
    db.execute(
        "INSERT INTO api_token (name, token, scope, created_at) VALUES (?, ?, 'read_only', ?)",
        (name, token, utcnow()),
    )
    db.commit()
    context = _settings_context(db, new_token={"name": name, "token": token})
    db.close()
    return templates.TemplateResponse(request, "settings.html", context)


@app.post("/settings/tokens/{token_id}/revoke")
def revoke_token(request: Request, token_id: int):
    if not auth.is_authed(request):
        return login_redirect(request)
    db = get_db()
    db.execute("DELETE FROM api_token WHERE id = ?", (token_id,))
    db.commit()
    db.close()
    return redirect(request, "/settings")


@app.post("/settings/objective")
def save_objective(request: Request, objective: str = Form("")):
    if not auth.is_authed(request):
        return login_redirect(request)
    db = get_db()
    db.execute(
        "UPDATE program_state SET objective = ? WHERE id = 1",
        (objective.strip() or None,),
    )
    db.commit()
    db.close()
    return redirect(request, "/settings")


@app.post("/settings/bodyweight")
def save_bodyweight(request: Request, bodyweight_kg: str = Form("")):
    """Save bodyweight (kg) to program_state for the TCX/Health calorie estimate
    (BACKLOG item 11). Blank or non-positive/invalid input clears it to NULL, so
    the export falls back to Calories 0 rather than a fabricated number."""
    if not auth.is_authed(request):
        return login_redirect(request)
    value = bodyweight_kg.strip()
    parsed = None
    if value:
        try:
            parsed = float(value)
        except ValueError:
            parsed = None
        if parsed is not None and parsed <= 0:
            parsed = None
    db = get_db()
    db.execute("UPDATE program_state SET bodyweight_kg = ? WHERE id = 1", (parsed,))
    db.commit()
    db.close()
    return redirect(request, "/settings")


@app.get("/export")
def export_json(request: Request):
    if not auth.is_authed(request):
        return login_redirect(request)
    db = get_db()
    data = exporter.export_all(db, utcnow())
    db.close()
    stamp = utcnow()[:10]
    return JSONResponse(
        data,
        headers={"Content-Disposition": f'attachment; filename="liftlog-export-{stamp}.json"'},
    )


@app.get("/export/program")
def export_program_json(request: Request):
    """Program-only export (BACKLOG item 9): the active program in the exact v2
    import shape, no history. Browser-only (cookie), not part of the token
    surface. Re-importable through the Import screen as-is."""
    if not auth.is_authed(request):
        return login_redirect(request)
    db = get_db()
    data = exporter.export_program(db)
    db.close()
    if data is None:
        return redirect(request, "/settings")
    stamp = utcnow()[:10]
    return JSONResponse(
        data,
        headers={"Content-Disposition": f'attachment; filename="liftlog-program-{stamp}.json"'},
    )


@app.get("/workout/{workout_id}/export.tcx")
def export_workout_tcx(request: Request, workout_id: int):
    """Download a finished workout as a Garmin TCX file (BACKLOG item 11) for
    manual Apple Health import via the free 'TCX to HealthKit' app. Standard
    browser download, behind the normal session — same as the JSON exports."""
    if not auth.is_authed(request):
        return login_redirect(request)
    db = get_db()
    workout = db.execute("SELECT * FROM workout WHERE id = ?", (workout_id,)).fetchone()
    if workout is None or workout["finished_at"] is None:
        db.close()
        return redirect(request, "/")
    duration_seconds = (
        parse_ts(workout["finished_at"]) - parse_ts(workout["started_at"])
    ).total_seconds()
    state = db.execute("SELECT bodyweight_kg FROM program_state WHERE id = 1").fetchone()
    bodyweight_kg = state["bodyweight_kg"] if state else None
    db.close()
    xml = exporter.workout_tcx(workout["started_at"], duration_seconds, bodyweight_kg)
    stamp = workout["started_at"][:10]
    return Response(
        content=xml,
        media_type="application/vnd.garmin.tcx+xml",
        headers={
            "Content-Disposition": f'attachment; filename="liftlog-workout-{workout_id}-{stamp}.tcx"'
        },
    )


@app.get("/api/latest-workout")
def latest_workout(request: Request):
    """Read-only latest finished workout for the Health-bridge Shortcut (BACKLOG
    item 8). Accepts a browser cookie OR a Bearer token (item 7). The `id` is the
    stable workout row id the Shortcut uses for client-side idempotency."""
    db = get_db()
    if not token_or_cookie_authed(request, db):
        db.close()
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    workout = db.execute(
        "SELECT * FROM workout WHERE finished_at IS NOT NULL "
        "ORDER BY finished_at DESC, id DESC LIMIT 1"
    ).fetchone()
    if workout is None:
        db.close()
        return JSONResponse({"error": "no finished workouts"}, status_code=404)
    routine_name = "Ad-hoc Session"
    if workout["routine_id"]:
        row = db.execute(
            "SELECT name FROM routine WHERE id = ?", (workout["routine_id"],)
        ).fetchone()
        if row:
            routine_name = row["name"]
    duration = (parse_ts(workout["finished_at"]) - parse_ts(workout["started_at"])).total_seconds()
    # volume = weight x reps over normal sets of weight_reps exercises only
    volume = db.execute(
        "SELECT COALESCE(SUM(s.weight_kg * s.reps), 0) AS v FROM set_log s "
        "JOIN exercise e ON e.id = s.exercise_id "
        "WHERE s.workout_id = ? AND s.set_type = 'normal' "
        "AND e.exercise_type = 'weight_reps' "
        "AND s.weight_kg IS NOT NULL AND s.reps IS NOT NULL",
        (workout["id"],),
    ).fetchone()["v"]
    db.close()
    return {
        "id": workout["id"],
        "date": workout["finished_at"],
        "duration_seconds": int(duration),
        "routine_name": routine_name,
        "is_deload": bool(workout["is_deload"]),
        "total_volume_kg": round(volume, 2),
    }


# ---- workout ----

@app.post("/workout/start")
def start_workout(request: Request, routine_id: int = Form(...)):
    if not auth.is_authed(request):
        return login_redirect(request)
    db = get_db()
    now = utcnow()
    is_deload = 1 if progression.deload_active(db, now) else 0
    cur = db.execute(
        "INSERT INTO workout (routine_id, started_at, is_deload) VALUES (?, ?, ?)",
        (routine_id, now, is_deload),
    )
    db.commit()
    workout_id = cur.lastrowid
    db.close()
    return redirect(request, f"/workout/{workout_id}")


def _exercise_payload(db, workout, exercise, target_sets, rep_min, rep_max,
                      rest_seconds, is_primary):
    """The per-exercise object the Active Workout JS consumes. Deload workouts
    override the prescription with 60% x 2x10 and skip warmup ramps."""
    workout_id = workout["id"]
    etype = exercise["exercise_type"]
    if workout["is_deload"]:
        s = progression.deload_prefill(db, exercise, exclude_workout_id=workout_id)
        # the classic 60% x 2x10 override is rep-based; other types just do 2 sets
        target_sets, rep_min, rep_max = (2, 10, 10) if etype == "weight_reps" else (2, rep_min, rep_max)
        warmups = []
    else:
        s = progression.suggest(db, exercise, target_sets, rep_min, rep_max,
                                exclude_workout_id=workout_id)
        # warmup ramps are barbell-weight ramps: only weight_reps primaries get them
        warmups = progression.warmup_ramp(s["weight_kg"], exercise["display_unit"]) \
            if is_primary and etype == "weight_reps" and s["weight_kg"] else []
    # id travels with each set so a logged set can be tapped and corrected in
    # place from the completed-sets list (BACKLOG item 18)
    sets = db.execute(
        "SELECT id, set_number, weight_kg, reps, duration_seconds, distance_m FROM set_log "
        "WHERE workout_id = ? AND exercise_id = ? AND set_type = 'normal' "
        "ORDER BY set_number",
        (workout_id, exercise["id"]),
    ).fetchall()
    warmups_logged = db.execute(
        "SELECT COUNT(*) FROM set_log WHERE workout_id = ? AND exercise_id = ? "
        "AND set_type = 'warmup'",
        (workout_id, exercise["id"]),
    ).fetchone()[0]
    return {
        "exercise_id": exercise["id"],
        "name": exercise["name"],
        "cue": exercise["cue"],
        "youtube_query": exercise["youtube_query"],
        "exercise_type": etype,
        "display_unit": exercise["display_unit"],
        "increment_kg": exercise["increment_kg"],
        "target_sets": target_sets,
        "rep_min": rep_min,
        "rep_max": rep_max,
        "rest_seconds": rest_seconds,
        "is_primary": is_primary,
        "suggest_weight_kg": s["weight_kg"],
        "suggest_reps": s["reps"],
        "suggest_duration_seconds": s["duration_seconds"],
        "suggest_distance_m": s["distance_m"],
        "suggest_kind": s["kind"],
        "warmups": warmups,
        "warmups_logged": warmups_logged,
        "skipped": False,
        "sets": [dict(row) for row in sets],
        "last": last_session_summary(db, exercise, workout_id),
    }


@app.get("/workout/{workout_id}", response_class=HTMLResponse)
def workout_page(request: Request, workout_id: int):
    if not auth.is_authed(request):
        return login_redirect(request)
    db = get_db()
    workout = db.execute("SELECT * FROM workout WHERE id = ?", (workout_id,)).fetchone()
    if workout is None:
        db.close()
        return redirect(request, "/")
    if workout["finished_at"]:
        db.close()
        return redirect(request, f"/workout/{workout_id}/summary")
    routine = db.execute("SELECT * FROM routine WHERE id = ?", (workout["routine_id"],)).fetchone()
    rows = db.execute(
        "SELECT re.* FROM routine_exercise re WHERE re.routine_id = ? ORDER BY re.position",
        (workout["routine_id"],),
    ).fetchall()
    # substitutions recorded earlier in this workout (resume case)
    subs = {
        r["planned_exercise_id"]: r["actual_exercise_id"]
        for r in db.execute(
            "SELECT planned_exercise_id, actual_exercise_id FROM substitution "
            "WHERE workout_id = ?", (workout_id,),
        )
    }
    exercises = []
    for r in rows:
        exercise_id = r["exercise_id"]
        skipped = False
        if exercise_id in subs:
            if subs[exercise_id] is None:
                skipped = True
            else:
                exercise_id = subs[exercise_id]
        exercise = db.execute("SELECT * FROM exercise WHERE id = ?", (exercise_id,)).fetchone()
        payload = _exercise_payload(
            db, workout, exercise, r["target_sets"], r["rep_min"], r["rep_max"],
            r["rest_seconds"], bool(r["is_primary"]),
        )
        payload["planned_exercise_id"] = r["exercise_id"]
        payload["skipped"] = skipped
        exercises.append(payload)
    db.close()
    routine_name = routine["name"] if routine else "ad-hoc session"
    state = {
        "workout_id": workout_id,
        "base": base_path(request),
        "routine_name": routine_name,
        "accent": accent_for(routine_name),
        "is_deload": bool(workout["is_deload"]),
        "exercises": exercises,
    }
    return templates.TemplateResponse(request, "workout.html", {
        "routine_name": routine_name,
        "accent": state["accent"],
        "state_json": json.dumps(state),
    })


@app.post("/api/workout/{workout_id}/set")
async def log_set(request: Request, workout_id: int):
    if not auth.is_authed(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    body = await request.json()
    db = get_db()
    workout = db.execute("SELECT * FROM workout WHERE id = ?", (workout_id,)).fetchone()
    if workout is None or workout["finished_at"]:
        db.close()
        return JSONResponse({"error": "workout not open"}, status_code=409)
    set_type = body.get("set_type", "normal")
    if set_type not in ("normal", "warmup"):
        db.close()
        return JSONResponse({"error": "bad set_type"}, status_code=400)

    def _num(key, cast):
        v = body.get(key)
        return None if v is None else cast(v)

    # which metric columns are populated is the client's call (driven by
    # exercise_type); any omitted metric is stored NULL — a 'none' set is all-NULL
    cur = db.execute(
        "INSERT INTO set_log (workout_id, exercise_id, set_number, set_type, weight_kg, reps, "
        "duration_seconds, distance_m, was_suggested, logged_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (workout_id, int(body["exercise_id"]), int(body["set_number"]), set_type,
         _num("weight_kg", float), _num("reps", int),
         _num("duration_seconds", float), _num("distance_m", float),
         1 if body.get("was_suggested") else 0, utcnow()),
    )
    db.commit()
    set_id = cur.lastrowid
    db.close()
    # the new row's id goes back so the client can make the set immediately
    # editable, without waiting for a page reload to learn it (item 18)
    return {"ok": True, "id": set_id}


@app.post("/api/set/{set_id}")
async def edit_set(request: Request, set_id: int):
    """Correct an already-logged set in place (BACKLOG item 18). Only the metric
    columns move: workout_id, exercise_id, set_number and set_type are never
    touched, so an edit can't fork into a duplicate row or renumber the slot.

    Deliberately works on FINISHED workouts too — correcting something noticed
    later is half the point — which is why there's no 'workout not open' guard
    here, unlike log_set. logged_at also keeps its original value: it's the
    historical timestamp progress_reset_at filters on, not an edit stamp."""
    if not auth.is_authed(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    body = await request.json()
    db = get_db()
    row = db.execute(
        "SELECT s.set_type, e.exercise_type FROM set_log s "
        "JOIN exercise e ON e.id = s.exercise_id WHERE s.id = ?",
        (set_id,),
    ).fetchone()
    if row is None:
        db.close()
        return JSONResponse({"error": "no such set"}, status_code=404)
    # warmups are always weight+reps whatever the exercise's own type, mirroring
    # how log_set writes them
    axes = ("weight_kg", "reps") if row["set_type"] == "warmup" \
        else SET_AXES[row["exercise_type"]]
    values = {}
    for key in ("weight_kg", "reps", "duration_seconds", "distance_m"):
        v = body.get(key)
        if key not in axes or v is None:
            values[key] = None
        elif key == "reps":
            values[key] = max(1, int(v))
        else:
            values[key] = max(0.0, float(v))
    # was_suggested always drops to 0: a correction made after the fact is no
    # longer an unmodified acceptance of the suggestion, so the honesty audit
    # (decision #10) must stop counting it as one.
    db.execute(
        "UPDATE set_log SET weight_kg = ?, reps = ?, duration_seconds = ?, "
        "distance_m = ?, was_suggested = 0 WHERE id = ?",
        (values["weight_kg"], values["reps"], values["duration_seconds"],
         values["distance_m"], set_id),
    )
    db.commit()
    db.close()
    return {"ok": True, **values}


def _swap_program_context(db, workout):
    """The active-context program's routines + their exercise names, for the
    Haiku prompt. Uses the workout's routine's program, falling back to the
    active program (ad-hoc workout)."""
    program_id = None
    if workout["routine_id"]:
        row = db.execute(
            "SELECT program_id FROM routine WHERE id = ?", (workout["routine_id"],)
        ).fetchone()
        program_id = row["program_id"] if row else None
    if program_id is None:
        active = db.execute("SELECT id FROM program WHERE is_active = 1").fetchone()
        program_id = active["id"] if active else None
    if program_id is None:
        return None, []
    routines = []
    for r in db.execute(
        "SELECT id, name FROM routine WHERE program_id = ? AND is_archived = 0 "
        "ORDER BY week_number, position, id",
        (program_id,),
    ):
        names = [
            row["name"] for row in db.execute(
                "SELECT e.name FROM routine_exercise re JOIN exercise e ON e.id = re.exercise_id "
                "WHERE re.routine_id = ? ORDER BY re.position",
                (r["id"],),
            )
        ]
        routines.append({"name": r["name"], "exercises": names})
    return program_id, routines


@app.get("/api/workout/{workout_id}/swap/{planned_exercise_id}")
def swap_previously_used(request: Request, workout_id: int, planned_exercise_id: int,
                         current: int = 0):
    """The 'previously used' section: actual past swaps recorded for this slot.
    Renders instantly, zero cost, can be empty."""
    if not auth.is_authed(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    db = get_db()
    rows = db.execute(
        "SELECT e.id, e.name, MAX(w.started_at) AS last_used "
        "FROM substitution s JOIN workout w ON w.id = s.workout_id "
        "JOIN exercise e ON e.id = s.actual_exercise_id "
        "WHERE s.planned_exercise_id = ? AND s.actual_exercise_id IS NOT NULL "
        "AND e.is_archived = 0 AND e.id != ? "
        "GROUP BY e.id ORDER BY last_used DESC",
        (planned_exercise_id, current or 0),
    ).fetchall()
    db.close()
    return {"previously_used": [
        {"id": r["id"], "name": r["name"], "last_used": r["last_used"]} for r in rows
    ]}


@app.post("/api/workout/{workout_id}/ai-suggestions/{planned_exercise_id}")
def ai_suggestions(request: Request, workout_id: int, planned_exercise_id: int):
    """'Get AI Suggestions' / 'Refresh': serve 3 unshown cached suggestions
    instantly, or call Haiku for the shortfall (guarded by the 100/day cap)."""
    if not auth.is_authed(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    db = get_db()
    workout = db.execute("SELECT * FROM workout WHERE id = ?", (workout_id,)).fetchone()
    planned = db.execute(
        "SELECT * FROM exercise WHERE id = ?", (planned_exercise_id,)
    ).fetchone()
    if workout is None or planned is None:
        db.close()
        return JSONResponse({"error": "not found"}, status_code=404)

    unshown = db.execute(
        "SELECT id, suggestion_json FROM ai_suggestion_cache "
        "WHERE planned_exercise_id = ? AND shown_at IS NULL ORDER BY created_at LIMIT 3",
        (planned_exercise_id,),
    ).fetchall()

    if len(unshown) < 3:
        # need a real Haiku call for the shortfall — guardrail check first
        if not can_make_ai_call(db):
            db.close()
            return {"state": "limit",
                    "message": "daily suggestion limit reached — try again later"}
        need = 3 - len(unshown)
        # exclusion list: every name ever cached for this slot (shown or not)
        exclusions = set()
        for row in db.execute(
            "SELECT suggestion_json FROM ai_suggestion_cache WHERE planned_exercise_id = ?",
            (planned_exercise_id,),
        ):
            try:
                exclusions.add(json.loads(row["suggestion_json"])["name"])
            except (ValueError, KeyError, TypeError):
                pass
        _, program_routines = _swap_program_context(db, workout)
        objective_row = db.execute(
            "SELECT objective FROM program_state WHERE id = 1"
        ).fetchone()
        objective = objective_row["objective"] if objective_row else None
        now = utcnow()
        # record the actual call BEFORE making it — one row per real attempt, so a
        # stuck retry loop still counts against the 100/day guardrail
        db.execute("INSERT INTO ai_call_log (created_at) VALUES (?)", (now,))
        db.commit()
        try:
            fresh = ai.fetch_suggestions(
                dict(planned), objective, program_routines, exclusions, need
            )
        except (ai.AICallError, ai.AIValidationError):
            db.close()
            return {"state": "error", "message": "couldn't get suggestions, try again"}
        for s in fresh:
            db.execute(
                "INSERT INTO ai_suggestion_cache (planned_exercise_id, suggestion_json, "
                "created_at, shown_at) VALUES (?, ?, ?, NULL)",
                (planned_exercise_id, json.dumps(s), now),
            )
        db.commit()
        unshown = db.execute(
            "SELECT id, suggestion_json FROM ai_suggestion_cache "
            "WHERE planned_exercise_id = ? AND shown_at IS NULL ORDER BY created_at LIMIT 3",
            (planned_exercise_id,),
        ).fetchall()

    # mark the ones we're about to show, so they're never re-served as "new"
    now = utcnow()
    result = []
    for row in unshown:
        db.execute(
            "UPDATE ai_suggestion_cache SET shown_at = ? WHERE id = ?", (now, row["id"])
        )
        s = json.loads(row["suggestion_json"])
        result.append({
            "cache_id": row["id"],
            "name": s["name"],
            "reason": s["reason"],
            "movement_pattern": s["movement_pattern"],
            "muscle_group": s["muscle_group"],
            "equipment": s["equipment"],
            "exercise_type": s["exercise_type"],
            "youtube_query": s["youtube_query"],
        })
    db.commit()
    db.close()
    if not result:
        return {"state": "error", "message": "couldn't get suggestions, try again"}
    return {"state": "ok", "suggestions": result}


def _ai_exercise(db, suggestion, now):
    """Find-or-create a library exercise from a validated AI suggestion. AI
    suggestions carry every tag the library needs. Returns the exercise row."""
    existing = db.execute(
        "SELECT * FROM exercise WHERE name = ? COLLATE NOCASE", (suggestion["name"],)
    ).fetchone()
    if existing:
        return existing
    etype = suggestion["exercise_type"]
    unit = "km" if etype in ("distance", "distance_weight") else "kg"
    new_id = db.execute(
        "INSERT INTO exercise (name, cue, youtube_query, movement_pattern, muscle_group, "
        "exercise_type, equipment, display_unit, increment_kg, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 2.5, ?)",
        (suggestion["name"], suggestion["cue"], suggestion["youtube_query"],
         suggestion["movement_pattern"], suggestion["muscle_group"], etype,
         suggestion["equipment"], unit, now),
    ).lastrowid
    return db.execute("SELECT * FROM exercise WHERE id = ?", (new_id,)).fetchone()


@app.post("/api/workout/{workout_id}/substitute")
async def substitute(request: Request, workout_id: int):
    """Apply a swap. Input is one of: {skip}, {cache_id, permanent} (AI pick), or
    {actual_exercise_id, permanent} (previously-used pick). One-time records only a
    substitution; permanent also repoints the routine_exercise slot."""
    if not auth.is_authed(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    body = await request.json()
    planned_id = int(body["planned_exercise_id"])
    db = get_db()
    workout = db.execute("SELECT * FROM workout WHERE id = ?", (workout_id,)).fetchone()
    if workout is None or workout["finished_at"]:
        db.close()
        return JSONResponse({"error": "workout not open"}, status_code=409)

    # re-swapping (or skipping after a swap) replaces the record, not stacks it
    db.execute(
        "DELETE FROM substitution WHERE workout_id = ? AND planned_exercise_id = ?",
        (workout_id, planned_id),
    )

    if body.get("skip"):
        db.execute(
            "INSERT INTO substitution (workout_id, planned_exercise_id, actual_exercise_id) "
            "VALUES (?, ?, NULL)",
            (workout_id, planned_id),
        )
        db.commit()
        db.close()
        return {"skipped": True}

    now = utcnow()
    if body.get("cache_id") is not None:
        # AI pick: create the library exercise from the cached suggestion if new
        cached = db.execute(
            "SELECT suggestion_json FROM ai_suggestion_cache WHERE id = ? "
            "AND planned_exercise_id = ?",
            (int(body["cache_id"]), planned_id),
        ).fetchone()
        if cached is None:
            db.close()
            return JSONResponse({"error": "no such suggestion"}, status_code=404)
        actual = _ai_exercise(db, json.loads(cached["suggestion_json"]), now)
    else:
        # previously-used pick: an existing library exercise
        actual = db.execute(
            "SELECT * FROM exercise WHERE id = ?", (int(body["actual_exercise_id"]),)
        ).fetchone()
        if actual is None:
            db.close()
            return JSONResponse({"error": "no such exercise"}, status_code=404)

    db.execute(
        "INSERT INTO substitution (workout_id, planned_exercise_id, actual_exercise_id) "
        "VALUES (?, ?, ?)",
        (workout_id, planned_id, actual["id"]),
    )
    re = db.execute(
        "SELECT * FROM routine_exercise WHERE routine_id = ? AND exercise_id = ?",
        (workout["routine_id"], planned_id),
    ).fetchone()
    # permanent swap: repoint the routine_exercise slot to the new exercise,
    # leaving sets/reps/rest/is_primary untouched
    if body.get("permanent") and re:
        db.execute(
            "UPDATE routine_exercise SET exercise_id = ? WHERE id = ?",
            (actual["id"], re["id"]),
        )
    target_sets = re["target_sets"] if re else 3
    rep_min = re["rep_min"] if re else 8
    rep_max = re["rep_max"] if re else 12
    rest_seconds = re["rest_seconds"] if re else 90
    is_primary = bool(re["is_primary"]) if re else False
    payload = _exercise_payload(
        db, workout, actual, target_sets, rep_min, rep_max, rest_seconds, is_primary
    )
    payload["planned_exercise_id"] = planned_id
    db.commit()
    db.close()
    return {"exercise": payload}


@app.post("/api/exercise/{exercise_id}/unit")
async def set_unit(request: Request, exercise_id: int):
    if not auth.is_authed(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    body = await request.json()
    unit = body.get("unit")
    if unit not in ("kg", "lbs", "km", "mi"):
        return JSONResponse({"error": "bad unit"}, status_code=400)
    db = get_db()
    db.execute("UPDATE exercise SET display_unit = ? WHERE id = ?", (unit, exercise_id))
    db.commit()
    db.close()
    return {"ok": True}


@app.post("/workout/{workout_id}/discard")
def discard_workout(request: Request, workout_id: int):
    if not auth.is_authed(request):
        return login_redirect(request)
    db = get_db()
    # only an open workout can be discarded; set_log rows go with it (CASCADE)
    db.execute("DELETE FROM workout WHERE id = ? AND finished_at IS NULL", (workout_id,))
    db.commit()
    db.close()
    return redirect(request, "/")


@app.post("/workout/{workout_id}/finish")
def finish_workout(request: Request, workout_id: int):
    if not auth.is_authed(request):
        return login_redirect(request)
    db = get_db()
    db.execute(
        "UPDATE workout SET finished_at = ? WHERE id = ? AND finished_at IS NULL",
        (utcnow(), workout_id),
    )
    db.commit()
    db.close()
    return redirect(request, f"/workout/{workout_id}/summary")


@app.get("/workout/{workout_id}/summary", response_class=HTMLResponse)
def summary_page(request: Request, workout_id: int):
    if not auth.is_authed(request):
        return login_redirect(request)
    db = get_db()
    workout = db.execute("SELECT * FROM workout WHERE id = ?", (workout_id,)).fetchone()
    if workout is None:
        db.close()
        return redirect(request, "/")
    routine = db.execute("SELECT * FROM routine WHERE id = ?", (workout["routine_id"],)).fetchone()
    rows = db.execute(
        "SELECT s.exercise_id, e.name, e.exercise_type, e.display_unit, "
        "s.weight_kg, s.reps, s.duration_seconds, s.distance_m "
        "FROM set_log s JOIN exercise e ON e.id = s.exercise_id "
        "WHERE s.workout_id = ? AND s.set_type = 'normal' "
        "ORDER BY s.logged_at, s.id",
        (workout_id,),
    ).fetchall()
    db.close()

    by_exercise = []
    index = {}
    total_volume_kg = 0.0
    for r in rows:
        if r["weight_kg"] is not None and r["reps"] is not None:
            total_volume_kg += r["weight_kg"] * r["reps"]
        if r["exercise_id"] not in index:
            index[r["exercise_id"]] = len(by_exercise)
            by_exercise.append({"name": r["name"], "unit": "",
                                "exercise_id": r["exercise_id"], "sets": []})
        entry = by_exercise[index[r["exercise_id"]]]
        cell, suffix = set_cell(r["exercise_type"], r, r["display_unit"])
        entry["sets"].append(cell)
        entry["unit"] = suffix

    duration = None
    if workout["finished_at"]:
        seconds = (parse_ts(workout["finished_at"]) - parse_ts(workout["started_at"])).total_seconds()
        duration = f"{int(seconds // 60)} min"

    routine_name = routine["name"] if routine else "ad-hoc session"
    return templates.TemplateResponse(request, "summary.html", {
        # tab bar remounts at Finish Summary (item 10); no tab is highlighted
        # since the summary isn't itself one of the four destinations.
        "active_tab": "summary",
        "workout_id": workout_id,
        "routine_name": routine_name,
        "accent": accent_for(routine_name),
        "finished": bool(workout["finished_at"]),
        "duration": duration,
        "total_sets": len(rows),
        "total_volume": f"{total_volume_kg:,.0f} kg",
        "exercises": by_exercise,
    })
