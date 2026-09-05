from app.db import utcnow


def _make_routine(db, unique, exercise_type="weight_reps", increment_kg=2.5):
    now = utcnow()
    program_id = db.execute(
        "INSERT INTO program (name, weeks_count, is_active, created_at, updated_at) "
        "VALUES (?, 1, 0, ?, ?)",
        (unique("Workout Test Program"), now, now),
    ).lastrowid
    exercise_id = db.execute(
        "INSERT INTO exercise (name, movement_pattern, muscle_group, exercise_type, "
        "increment_kg, created_at) VALUES (?, 'squat', 'legs', ?, ?, ?)",
        (unique("Workout Test Squat"), exercise_type, increment_kg, now),
    ).lastrowid
    routine_id = db.execute(
        "INSERT INTO routine (program_id, name, week_number, position, created_at, updated_at) "
        "VALUES (?, ?, 1, 0, ?, ?)",
        (program_id, unique("Workout Test Routine"), now, now),
    ).lastrowid
    db.execute(
        "INSERT INTO routine_exercise (routine_id, exercise_id, position, target_sets, "
        "rep_min, rep_max, rest_seconds, is_primary) VALUES (?, ?, 0, 3, 8, 10, 90, 1)",
        (routine_id, exercise_id),
    )
    db.commit()
    return routine_id, exercise_id


def test_workouts_require_auth(client):
    assert client.post("/api/workouts", json={"routine_id": 1}).status_code == 401
    assert client.get("/api/workouts/1").status_code == 401


def test_start_unknown_routine_is_404(auth_client):
    resp = auth_client.post("/api/workouts", json={"routine_id": 999999})
    assert resp.status_code == 404


def test_start_state_finish_summary_lifecycle(auth_client, db, unique):
    routine_id, exercise_id = _make_routine(db, unique)

    started = auth_client.post("/api/workouts", json={"routine_id": routine_id})
    assert started.status_code == 200
    workout_id = started.json()["id"]
    assert started.json()["is_deload"] is False

    state = auth_client.get(f"/api/workouts/{workout_id}")
    assert state.status_code == 200
    state_data = state.json()
    assert state_data["workout"]["id"] == workout_id
    assert state_data["workout"]["finished_at"] is None
    assert state_data["exercises"][0]["exercise_id"] == exercise_id
    assert state_data["exercises"][0]["sets"] == []

    finished = auth_client.post(f"/api/workouts/{workout_id}/finish")
    assert finished.status_code == 200
    assert finished.json()["finished_at"]

    # finishing twice is a conflict
    assert auth_client.post(f"/api/workouts/{workout_id}/finish").status_code == 409

    # state remains readable (no redirect) after finishing
    finished_state = auth_client.get(f"/api/workouts/{workout_id}")
    assert finished_state.json()["workout"]["finished_at"]

    summary = auth_client.get(f"/api/workouts/{workout_id}/summary")
    assert summary.status_code == 200
    assert summary.json()["totals"] == {"sets": 0, "volume_kg": 0}


def test_discard_only_works_on_open_workout(auth_client, db, unique):
    routine_id, _ = _make_routine(db, unique)
    workout_id = auth_client.post("/api/workouts", json={"routine_id": routine_id}).json()["id"]

    assert auth_client.post(f"/api/workouts/{workout_id}/discard").status_code == 204
    assert auth_client.get(f"/api/workouts/{workout_id}").status_code == 404

    workout_id2 = auth_client.post("/api/workouts", json={"routine_id": routine_id}).json()["id"]
    auth_client.post(f"/api/workouts/{workout_id2}/finish")
    assert auth_client.post(f"/api/workouts/{workout_id2}/discard").status_code == 409


def test_log_set_and_edit_clears_was_suggested(auth_client, db, unique):
    routine_id, exercise_id = _make_routine(db, unique)
    workout_id = auth_client.post("/api/workouts", json={"routine_id": routine_id}).json()["id"]

    logged = auth_client.post(
        f"/api/workout/{workout_id}/set",
        json={
            "exercise_id": exercise_id, "set_number": 1, "set_type": "normal",
            "was_suggested": 1, "weight_kg": 60, "reps": 8,
            "duration_seconds": None, "distance_m": None,
        },
    )
    assert logged.status_code == 200
    set_id = logged.json()["id"]
    row = db.execute("SELECT was_suggested FROM set_log WHERE id = ?", (set_id,)).fetchone()
    assert row["was_suggested"] == 1

    edited = auth_client.post(
        f"/api/set/{set_id}",
        json={"weight_kg": 62.5, "reps": 9, "duration_seconds": None, "distance_m": None},
    )
    assert edited.status_code == 200
    assert edited.json()["weight_kg"] == 62.5
    row2 = db.execute("SELECT was_suggested FROM set_log WHERE id = ?", (set_id,)).fetchone()
    assert row2["was_suggested"] == 0


def test_substitute_skip_and_swap(auth_client, db, unique):
    routine_id, exercise_id = _make_routine(db, unique)
    now = utcnow()
    other_exercise_id = db.execute(
        "INSERT INTO exercise (name, movement_pattern, muscle_group, created_at) "
        "VALUES (?, 'hinge', 'legs', ?)",
        (unique("Alternate Exercise"), now),
    ).lastrowid
    db.commit()
    workout_id = auth_client.post("/api/workouts", json={"routine_id": routine_id}).json()["id"]

    skip = auth_client.post(
        f"/api/workout/{workout_id}/substitute",
        json={"planned_exercise_id": exercise_id, "skip": True},
    )
    assert skip.status_code == 200
    assert skip.json() == {"skipped": True}
    state_after_skip = auth_client.get(f"/api/workouts/{workout_id}").json()
    assert state_after_skip["exercises"][0]["skipped"] is True

    swap = auth_client.post(
        f"/api/workout/{workout_id}/substitute",
        json={
            "planned_exercise_id": exercise_id,
            "actual_exercise_id": other_exercise_id,
            "permanent": False,
        },
    )
    assert swap.status_code == 200
    assert swap.json()["exercise"]["exercise_id"] == other_exercise_id
    assert swap.json()["exercise"]["skipped"] is False
    state_after_swap = auth_client.get(f"/api/workouts/{workout_id}").json()
    assert state_after_swap["exercises"][0]["exercise_id"] == other_exercise_id
    assert state_after_swap["exercises"][0]["skipped"] is False


def test_deload_workout_prefills_60_percent_2x10(auth_client, db, unique):
    routine_id, exercise_id = _make_routine(db, unique)
    # force deload_active(): 4th week, no deferral
    db.execute(
        "UPDATE program_state SET weeks_since_deload = 3, deload_deferred_until = NULL WHERE id = 1"
    )
    db.commit()

    started = auth_client.post("/api/workouts", json={"routine_id": routine_id})
    assert started.json()["is_deload"] is True
    workout_id = started.json()["id"]

    state = auth_client.get(f"/api/workouts/{workout_id}").json()
    exercise = state["exercises"][0]
    # classic 60% x 2x10 override, no warmups on a deload session
    assert exercise["target_sets"] == 2
    assert exercise["rep_min"] == 10
    assert exercise["rep_max"] == 10
    assert exercise["warmups"] == []
    assert exercise["suggest_kind"] == "deload"
    assert exercise["suggest_reps"] == 10
    # first-ever session for this exercise: 60% of the 20kg bar, floored at 2.5kg
    assert exercise["suggest_weight_kg"] == 12.5

    # restore program_state so later tests in this module aren't affected
    db.execute(
        "UPDATE program_state SET weeks_since_deload = 0, deload_deferred_until = NULL WHERE id = 1"
    )
    db.commit()
