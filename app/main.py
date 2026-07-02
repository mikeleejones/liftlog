import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import auth
from .config import SECRET
from .db import get_db, init_db, run_week_completion, utcnow

if not SECRET:
    sys.exit("LIFTLOG_SECRET is not set. Put it in the environment or a .env file, then restart.")

APP_DIR = Path(__file__).resolve().parent
app = FastAPI()
app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")
templates = Jinja2Templates(directory=APP_DIR / "templates")

init_db()

DAY_ACCENTS = {"Mon": "cyan", "Wed": "gold", "Fri": "green"}


def accent_for(routine_name: str) -> str:
    return DAY_ACCENTS.get(routine_name[:3], "violet")


def parse_ts(ts: str) -> datetime:
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def login_redirect() -> RedirectResponse:
    return RedirectResponse("/login", status_code=303)


# ---- auth ----

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    if auth.is_authed(request):
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(request, "login.html", {"error": False})


@app.post("/login")
def login(request: Request, secret: str = Form("")):
    if not auth.secret_matches(secret):
        return templates.TemplateResponse(
            request, "login.html", {"error": True}, status_code=401
        )
    resp = RedirectResponse("/", status_code=303)
    resp.set_cookie(
        auth.COOKIE_NAME, auth.cookie_value(),
        max_age=auth.COOKIE_MAX_AGE, httponly=True, samesite="lax",
    )
    return resp


# ---- home ----

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    if not auth.is_authed(request):
        return login_redirect()
    db = get_db()
    run_week_completion(db)
    state = db.execute("SELECT * FROM program_state WHERE id = 1").fetchone()
    routines = db.execute(
        "SELECT r.*, COUNT(re.id) AS exercise_count FROM routine r "
        "LEFT JOIN routine_exercise re ON re.routine_id = r.id "
        "WHERE r.is_archived = 0 GROUP BY r.id ORDER BY r.position, r.id"
    ).fetchall()
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
    db.close()
    return templates.TemplateResponse(request, "home.html", {
        "routines": [dict(r, accent=accent_for(r["name"])) for r in routines],
        "sessions_this_week": sessions_this_week,
        "in_progress": in_progress,
        "in_progress_accent": accent_for(in_progress["routine_name"] or "") if in_progress else None,
    })


# ---- workout ----

@app.post("/workout/start")
def start_workout(request: Request, routine_id: int = Form(...)):
    if not auth.is_authed(request):
        return login_redirect()
    db = get_db()
    cur = db.execute(
        "INSERT INTO workout (routine_id, started_at) VALUES (?, ?)",
        (routine_id, utcnow()),
    )
    db.commit()
    workout_id = cur.lastrowid
    db.close()
    return RedirectResponse(f"/workout/{workout_id}", status_code=303)


def suggestion_for(db, exercise_id: int, workout_id: int, rep_min: int, rep_max: int):
    """v0.1: suggest the last working-set weight/reps from the most recent prior
    workout. Real double-progression logic lands in v0.3."""
    row = db.execute(
        "SELECT weight_kg, reps FROM set_log "
        "WHERE exercise_id = ? AND set_type = 'normal' AND workout_id != ? "
        "ORDER BY logged_at DESC, id DESC LIMIT 1",
        (exercise_id, workout_id),
    ).fetchone()
    if row is None:
        return 20.0, rep_min
    return row["weight_kg"], min(max(row["reps"], rep_min), rep_max)


@app.get("/workout/{workout_id}", response_class=HTMLResponse)
def workout_page(request: Request, workout_id: int):
    if not auth.is_authed(request):
        return login_redirect()
    db = get_db()
    workout = db.execute("SELECT * FROM workout WHERE id = ?", (workout_id,)).fetchone()
    if workout is None:
        db.close()
        return RedirectResponse("/", status_code=303)
    if workout["finished_at"]:
        db.close()
        return RedirectResponse(f"/workout/{workout_id}/summary", status_code=303)
    routine = db.execute("SELECT * FROM routine WHERE id = ?", (workout["routine_id"],)).fetchone()
    rows = db.execute(
        "SELECT re.*, e.name, e.cue, e.youtube_query, e.display_unit, e.increment_kg "
        "FROM routine_exercise re JOIN exercise e ON e.id = re.exercise_id "
        "WHERE re.routine_id = ? ORDER BY re.position",
        (workout["routine_id"],),
    ).fetchall()
    exercises = []
    for r in rows:
        sets = db.execute(
            "SELECT set_number, weight_kg, reps FROM set_log "
            "WHERE workout_id = ? AND exercise_id = ? AND set_type = 'normal' "
            "ORDER BY set_number",
            (workout_id, r["exercise_id"]),
        ).fetchall()
        weight, reps = suggestion_for(db, r["exercise_id"], workout_id, r["rep_min"], r["rep_max"])
        exercises.append({
            "exercise_id": r["exercise_id"],
            "name": r["name"],
            "cue": r["cue"],
            "youtube_query": r["youtube_query"],
            "display_unit": r["display_unit"],
            "increment_kg": r["increment_kg"],
            "target_sets": r["target_sets"],
            "rep_min": r["rep_min"],
            "rep_max": r["rep_max"],
            "rest_seconds": r["rest_seconds"],
            "is_primary": bool(r["is_primary"]),
            "suggest_weight_kg": weight,
            "suggest_reps": reps,
            "sets": [dict(s) for s in sets],
        })
    db.close()
    routine_name = routine["name"] if routine else "ad-hoc session"
    state = {
        "workout_id": workout_id,
        "routine_name": routine_name,
        "accent": accent_for(routine_name),
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
    db.execute(
        "INSERT INTO set_log (workout_id, exercise_id, set_number, set_type, weight_kg, reps, "
        "was_suggested, logged_at) VALUES (?, ?, ?, 'normal', ?, ?, ?, ?)",
        (workout_id, int(body["exercise_id"]), int(body["set_number"]),
         float(body["weight_kg"]), int(body["reps"]),
         1 if body.get("was_suggested") else 0, utcnow()),
    )
    db.commit()
    db.close()
    return {"ok": True}


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


@app.post("/workout/{workout_id}/finish")
def finish_workout(request: Request, workout_id: int):
    if not auth.is_authed(request):
        return login_redirect()
    db = get_db()
    db.execute(
        "UPDATE workout SET finished_at = ? WHERE id = ? AND finished_at IS NULL",
        (utcnow(), workout_id),
    )
    db.commit()
    db.close()
    return RedirectResponse(f"/workout/{workout_id}/summary", status_code=303)


@app.get("/workout/{workout_id}/summary", response_class=HTMLResponse)
def summary_page(request: Request, workout_id: int):
    if not auth.is_authed(request):
        return login_redirect()
    db = get_db()
    workout = db.execute("SELECT * FROM workout WHERE id = ?", (workout_id,)).fetchone()
    if workout is None:
        db.close()
        return RedirectResponse("/", status_code=303)
    routine = db.execute("SELECT * FROM routine WHERE id = ?", (workout["routine_id"],)).fetchone()
    rows = db.execute(
        "SELECT s.exercise_id, e.name, e.display_unit, s.weight_kg, s.reps "
        "FROM set_log s JOIN exercise e ON e.id = s.exercise_id "
        "WHERE s.workout_id = ? AND s.set_type = 'normal' "
        "ORDER BY s.logged_at, s.id",
        (workout_id,),
    ).fetchall()
    db.close()

    KG_PER_LB = 0.45359237
    by_exercise = []
    index = {}
    total_volume_kg = 0.0
    for r in rows:
        total_volume_kg += r["weight_kg"] * r["reps"]
        if r["exercise_id"] not in index:
            index[r["exercise_id"]] = len(by_exercise)
            by_exercise.append({"name": r["name"], "unit": r["display_unit"], "sets": []})
        entry = by_exercise[index[r["exercise_id"]]]
        if r["display_unit"] == "lbs":
            display_weight = r["weight_kg"] / KG_PER_LB
        else:
            display_weight = r["weight_kg"]
        entry["sets"].append(f"{round(display_weight, 2):g} × {r['reps']}")

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
