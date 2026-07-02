import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import auth, catalog, charts, exporter, importer, progression
from .config import SECRET
from .db import get_db, init_db, run_week_completion, sessions_required, utcnow

if not SECRET:
    sys.exit("LIFTLOG_SECRET is not set. Put it in the environment or a .env file, then restart.")

APP_DIR = Path(__file__).resolve().parent
app = FastAPI()
app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")


def base_path(request: Request) -> str:
    """The proxy prefix this app is mounted under (e.g. '/liftlog' when run
    with uvicorn --root-path /liftlog), or '' when served at the domain root.
    Every absolute URL sent to the browser must be prefixed with this so it
    resolves to a path the reverse proxy actually forwards."""
    return request.scope.get("root_path", "")


def redirect(request: Request, path: str, status_code: int = 303) -> RedirectResponse:
    return RedirectResponse(base_path(request) + path, status_code=status_code)


# makes {{ base }} available in every template for href/action/src prefixing
templates = Jinja2Templates(
    directory=APP_DIR / "templates",
    context_processors=[lambda request: {"base": base_path(request)}],
)

init_db()

DAY_ACCENTS = {"Mon": "cyan", "Wed": "gold", "Fri": "green"}


def accent_for(routine_name: str) -> str:
    return DAY_ACCENTS.get(routine_name[:3], "violet")


KG_PER_LB = 0.45359237


def to_display(kg: float, unit: str) -> float:
    return kg / KG_PER_LB if unit == "lbs" else kg


def fmt_weight(kg: float, unit: str) -> str:
    return f"{round(to_display(kg, unit), 2):g}"


def parse_ts(ts: str) -> datetime:
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def login_redirect(request: Request) -> RedirectResponse:
    return redirect(request, "/login")


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

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    if not auth.is_authed(request):
        return login_redirect(request)
    db = get_db()
    run_week_completion(db)
    state = db.execute("SELECT * FROM program_state WHERE id = 1").fetchone()
    active = db.execute("SELECT * FROM program WHERE is_active = 1").fetchone()
    if active:
        routines = db.execute(
            "SELECT r.*, COUNT(re.id) AS exercise_count FROM routine r "
            "LEFT JOIN routine_exercise re ON re.routine_id = r.id "
            "WHERE r.is_archived = 0 AND r.program_id = ? AND r.week_number = ? "
            "GROUP BY r.id ORDER BY r.position, r.id",
            (active["id"], state["program_week"]),
        ).fetchall()
    else:
        routines = db.execute(
            "SELECT r.*, COUNT(re.id) AS exercise_count FROM routine r "
            "LEFT JOIN routine_exercise re ON re.routine_id = r.id "
            "WHERE r.is_archived = 0 GROUP BY r.id ORDER BY r.position, r.id"
        ).fetchall()
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

    routine_cards = []
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
        routine_cards.append(dict(r, accent=accent_for(r["name"]), progress_ready=ready))

    db.close()
    return templates.TemplateResponse(request, "home.html", {
        "routines": routine_cards,
        "sessions_this_week": sessions_this_week,
        "sessions_required": required,
        "program": active,
        "program_week": state["program_week"],
        "deload": deload,
        "deload_deferred": deload_deferred,
        "in_progress": in_progress,
        "in_progress_accent": accent_for(in_progress["routine_name"] or "") if in_progress else None,
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

def _program_groups(db):
    """Programs (active first) with their unarchived routines grouped by week,
    plus any standalone routines."""
    groups = []
    programs = db.execute(
        "SELECT * FROM program ORDER BY is_active DESC, name"
    ).fetchall()
    state = db.execute("SELECT program_week FROM program_state WHERE id = 1").fetchone()
    for p in programs:
        routines = db.execute(
            "SELECT r.*, COUNT(re.id) AS exercise_count FROM routine r "
            "LEFT JOIN routine_exercise re ON re.routine_id = r.id "
            "WHERE r.program_id = ? AND r.is_archived = 0 "
            "GROUP BY r.id ORDER BY r.week_number, r.position, r.id",
            (p["id"],),
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
        "WHERE r.program_id IS NULL AND r.is_archived = 0 "
        "GROUP BY r.id ORDER BY r.position, r.id"
    ).fetchall()
    return groups, [dict(r, accent=accent_for(r["name"])) for r in standalone]


def _routines_context(db, imported=0, errors=None, raw=""):
    groups, standalone = _program_groups(db)
    return {
        "groups": groups,
        "standalone": standalone,
        "imported": imported,
        "errors": errors or [],
        "raw": raw,
    }


@app.get("/routines", response_class=HTMLResponse)
def routines_page(request: Request, imported: int = 0):
    if not auth.is_authed(request):
        return login_redirect(request)
    db = get_db()
    context = _routines_context(db, imported=imported)
    db.close()
    return templates.TemplateResponse(request, "routines.html", context)


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
        db = get_db()
        context = _routines_context(db, errors=errors, raw=raw)
        db.close()
        return templates.TemplateResponse(request, "routines.html", context, status_code=422)
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
        return redirect(request, "/routines")
    db = get_db()
    importer.apply_import(db, importer.normalize(payload), utcnow())
    db.commit()
    db.close()
    return redirect(request, "/routines?imported=1")


@app.get("/exercises", response_class=HTMLResponse)
def exercises_page(request: Request):
    if not auth.is_authed(request):
        return login_redirect(request)
    db = get_db()
    exercises = db.execute(
        "SELECT * FROM exercise WHERE is_archived = 0 ORDER BY name COLLATE NOCASE"
    ).fetchall()
    db.close()
    return templates.TemplateResponse(request, "exercises.html", {"exercises": exercises})


# ---- progress + exercise detail + settings ----

def _exercise_history(db, exercise_id, unit):
    """Per-workout summary for one exercise (working sets only), oldest first,
    with top-set weight, volume, date, deload flag, and PR marks. A PR is a
    top-set weight strictly above every earlier session's top set."""
    rows = db.execute(
        "SELECT w.id AS wid, w.started_at, w.is_deload, s.weight_kg, s.reps "
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
                "is_deload": bool(r["is_deload"]), "sets": [], "top_kg": 0.0,
                "volume_kg": 0.0,
            })
        s = sessions[-1]
        s["sets"].append((r["weight_kg"], r["reps"]))
        s["top_kg"] = max(s["top_kg"], r["weight_kg"])
        s["volume_kg"] += r["weight_kg"] * r["reps"]
    best = 0.0
    history = []
    for s in sessions:
        is_pr = (not s["is_deload"]) and s["top_kg"] > best
        if is_pr:
            best = s["top_kg"]
        history.append({
            "date": s["started_at"][:10],
            "is_deload": s["is_deload"],
            "is_pr": is_pr,
            "top": fmt_weight(s["top_kg"], unit),
            "top_kg": s["top_kg"],
            "sets_text": " · ".join(f"{fmt_weight(w, unit)}×{r}" for w, r in s["sets"]),
            "volume": f"{round(to_display(s['volume_kg'], unit)):g}",
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
    history = _exercise_history(db, exercise_id, unit)
    db.close()
    chart = charts.line_chart([
        {"value": to_display(h["top_kg"], unit), "is_pr": h["is_pr"],
         "is_deload": h["is_deload"], "label": h["date"][5:]}
        for h in history
    ])
    return templates.TemplateResponse(request, "exercise_detail.html", {
        "exercise": exercise,
        "unit": unit,
        "history": list(reversed(history)),
        "chart": chart,
        "youtube_query": exercise["youtube_query"],
    })


@app.get("/progress", response_class=HTMLResponse)
def progress_page(request: Request):
    if not auth.is_authed(request):
        return login_redirect(request)
    db = get_db()
    run_week_completion(db)
    state = db.execute("SELECT * FROM program_state WHERE id = 1").fetchone()
    active = db.execute("SELECT * FROM program WHERE is_active = 1").fetchone()
    now = utcnow()
    deload = progression.deload_active(db, now)

    lifts = []
    if active:
        rows = db.execute(
            "SELECT re.target_sets, re.rep_min, re.rep_max, e.* FROM routine_exercise re "
            "JOIN exercise e ON e.id = re.exercise_id "
            "JOIN routine r ON r.id = re.routine_id "
            "WHERE r.program_id = ? AND r.week_number = ? AND r.is_archived = 0 "
            "ORDER BY r.position, re.position",
            (active["id"], state["program_week"]),
        ).fetchall()
        seen = set()
        for re in rows:
            if re["id"] in seen:
                continue
            seen.add(re["id"])
            s = progression.suggest(db, re, re["target_sets"], re["rep_min"], re["rep_max"])
            last = db.execute(
                "SELECT s.weight_kg FROM set_log s JOIN workout w ON w.id = s.workout_id "
                "WHERE s.exercise_id = ? AND s.set_type = 'normal' AND w.is_deload = 0 "
                "ORDER BY w.started_at DESC, s.id DESC LIMIT 1",
                (re["id"],),
            ).fetchone()
            lifts.append({
                "id": re["id"],
                "name": re["name"],
                "unit": re["display_unit"],
                "last": fmt_weight(last["weight_kg"], re["display_unit"]) if last else "—",
                "suggest": fmt_weight(s["weight_kg"], re["display_unit"]),
                "kind": s["kind"],
            })

    # honesty audit (decision 10): share of working sets logged as-suggested
    audit = db.execute(
        "SELECT COUNT(*) AS total, COALESCE(SUM(was_suggested), 0) AS suggested "
        "FROM set_log WHERE set_type = 'normal'"
    ).fetchone()
    suggested_pct = round(100 * audit["suggested"] / audit["total"]) if audit["total"] else None

    ready = sum(1 for l in lifts if l["kind"] == "progress")
    db.close()
    return templates.TemplateResponse(request, "progress.html", {
        "program": active,
        "program_week": state["program_week"],
        "completed_weeks": state["completed_weeks"],
        "weeks_since_deload": state["weeks_since_deload"],
        "deload": deload,
        "lifts": lifts,
        "ready": ready,
        "suggested_pct": suggested_pct,
        "audit_total": audit["total"],
    })


@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request):
    if not auth.is_authed(request):
        return login_redirect(request)
    db = get_db()
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
    db.close()
    return templates.TemplateResponse(request, "settings.html", {
        "deload": deload,
        "weeks_since_deload": state["weeks_since_deload"],
        "completed_weeks": state["completed_weeks"],
        "deload_deferred": bool(state["deload_deferred_until"] and state["deload_deferred_until"] > now),
        "counts": counts,
    })


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
    if workout["is_deload"]:
        s = progression.deload_prefill(db, exercise, exclude_workout_id=workout_id)
        target_sets, rep_min, rep_max = 2, 10, 10
        warmups = []
    else:
        s = progression.suggest(db, exercise, target_sets, rep_min, rep_max,
                                exclude_workout_id=workout_id)
        warmups = progression.warmup_ramp(s["weight_kg"], exercise["display_unit"]) \
            if is_primary else []
    sets = db.execute(
        "SELECT set_number, weight_kg, reps FROM set_log "
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
        "display_unit": exercise["display_unit"],
        "increment_kg": exercise["increment_kg"],
        "target_sets": target_sets,
        "rep_min": rep_min,
        "rep_max": rep_max,
        "rest_seconds": rest_seconds,
        "is_primary": is_primary,
        "suggest_weight_kg": s["weight_kg"],
        "suggest_reps": s["reps"],
        "suggest_kind": s["kind"],
        "warmups": warmups,
        "warmups_logged": warmups_logged,
        "skipped": False,
        "sets": [dict(row) for row in sets],
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
    db.execute(
        "INSERT INTO set_log (workout_id, exercise_id, set_number, set_type, weight_kg, reps, "
        "was_suggested, logged_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (workout_id, int(body["exercise_id"]), int(body["set_number"]), set_type,
         float(body["weight_kg"]), int(body["reps"]),
         1 if body.get("was_suggested") else 0, utcnow()),
    )
    db.commit()
    db.close()
    return {"ok": True}


@app.get("/api/workout/{workout_id}/substitutes/{planned_exercise_id}")
def substitutes(request: Request, workout_id: int, planned_exercise_id: int,
                current: int = 0):
    if not auth.is_authed(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    db = get_db()
    workout = db.execute("SELECT * FROM workout WHERE id = ?", (workout_id,)).fetchone()
    if workout is None:
        db.close()
        return JSONResponse({"error": "no such workout"}, status_code=404)
    # never suggest what's already in play this workout: the exercise being
    # swapped, earlier swap targets, or anything with sets logged today
    exclude = {current} if current else set()
    for r in db.execute(
        "SELECT actual_exercise_id AS id FROM substitution "
        "WHERE workout_id = ? AND actual_exercise_id IS NOT NULL "
        "UNION SELECT DISTINCT exercise_id FROM set_log WHERE workout_id = ?",
        (workout_id, workout_id),
    ):
        exclude.add(r["id"])
    candidates = progression.substitution_candidates(
        db, planned_exercise_id, workout["routine_id"], exclude_ids=exclude
    )
    result = [
        {
            "id": c["id"],
            "name": c["name"],
            "movement_pattern": c["movement_pattern"],
            "muscle_group": c["muscle_group"],
            "last_used": c["last_used"],
            "from_catalog": False,
        }
        for c in candidates
    ]
    if len(result) < 3:
        planned = db.execute(
            "SELECT * FROM exercise WHERE id = ?", (planned_exercise_id,)
        ).fetchone()
        exclude_names = {c["name"] for c in result}
        for entry in catalog.suggestions(db, planned, exclude_names, 3 - len(result)):
            result.append({
                "id": None,
                "name": entry["name"],
                "movement_pattern": entry["movement_pattern"],
                "muscle_group": entry["muscle_group"],
                "last_used": None,
                "from_catalog": True,
            })
    db.close()
    return {"candidates": result}


@app.post("/api/workout/{workout_id}/substitute")
async def substitute(request: Request, workout_id: int):
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
    if body.get("new_name"):
        name = body["new_name"].strip()
        if not name:
            db.close()
            return JSONResponse({"error": "empty name"}, status_code=400)
        actual = db.execute(
            "SELECT * FROM exercise WHERE name = ? COLLATE NOCASE", (name,)
        ).fetchone()
        if actual is None:
            # catalog names bring their own tags; typed names inherit the
            # planned exercise's
            planned = db.execute(
                "SELECT * FROM exercise WHERE id = ?", (planned_id,)
            ).fetchone()
            known = catalog.lookup(name)
            if known:
                pattern, group, yt = known
            else:
                pattern, group, yt = (planned["movement_pattern"],
                                      planned["muscle_group"], f"{name.lower()} form")
            actual_id = db.execute(
                "INSERT INTO exercise (name, cue, youtube_query, movement_pattern, "
                "muscle_group, display_unit, increment_kg, created_at) "
                "VALUES (?, '', ?, ?, ?, ?, ?, ?)",
                (name, yt, pattern, group, planned["display_unit"],
                 planned["increment_kg"], now),
            ).lastrowid
            actual = db.execute("SELECT * FROM exercise WHERE id = ?", (actual_id,)).fetchone()
    else:
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
    if unit not in ("kg", "lbs"):
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
        "SELECT s.exercise_id, e.name, e.display_unit, s.weight_kg, s.reps "
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
        total_volume_kg += r["weight_kg"] * r["reps"]
        if r["exercise_id"] not in index:
            index[r["exercise_id"]] = len(by_exercise)
            by_exercise.append({"name": r["name"], "unit": r["display_unit"],
                                "exercise_id": r["exercise_id"], "sets": []})
        entry = by_exercise[index[r["exercise_id"]]]
        entry["sets"].append(f"{fmt_weight(r['weight_kg'], r['display_unit'])} × {r['reps']}")

    duration = None
    if workout["finished_at"]:
        seconds = (parse_ts(workout["finished_at"]) - parse_ts(workout["started_at"])).total_seconds()
        duration = f"{int(seconds // 60)} min"

    routine_name = routine["name"] if routine else "ad-hoc session"
    return templates.TemplateResponse(request, "summary.html", {
        "routine_name": routine_name,
        "accent": accent_for(routine_name),
        "finished": bool(workout["finished_at"]),
        "duration": duration,
        "total_sets": len(rows),
        "total_volume": f"{total_volume_kg:,.0f} kg",
        "exercises": by_exercise,
    })
