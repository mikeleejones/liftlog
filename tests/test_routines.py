from app.db import utcnow


def _make_program_with_routine(db, unique):
    now = utcnow()
    program_name = unique("Test Program")
    program_id = db.execute(
        "INSERT INTO program (name, weeks_count, is_active, created_at, updated_at) "
        "VALUES (?, 1, 0, ?, ?)",
        (program_name, now, now),
    ).lastrowid
    exercise_name = unique("Test Squat")
    exercise_id = db.execute(
        "INSERT INTO exercise (name, movement_pattern, muscle_group, created_at) "
        "VALUES (?, 'squat', 'legs', ?)",
        (exercise_name, now),
    ).lastrowid
    routine_name = unique("Test Routine")
    routine_id = db.execute(
        "INSERT INTO routine (program_id, name, week_number, position, created_at, updated_at) "
        "VALUES (?, ?, 1, 0, ?, ?)",
        (program_id, routine_name, now, now),
    ).lastrowid
    db.execute(
        "INSERT INTO routine_exercise (routine_id, exercise_id, position, target_sets, "
        "rep_min, rep_max, rest_seconds, is_primary) VALUES (?, ?, 0, 3, 8, 10, 90, 1)",
        (routine_id, exercise_id),
    )
    db.commit()
    return program_id, routine_id, exercise_id


def test_routines_requires_auth(client):
    assert client.get("/api/routines").status_code == 401


def test_routines_list_active_view_includes_new_routine(auth_client, db, unique):
    _, routine_id, _ = _make_program_with_routine(db, unique)
    resp = auth_client.get("/api/routines?view=active")
    assert resp.status_code == 200
    data = resp.json()
    assert data["view"] == "active"
    all_routine_ids = {
        r["id"]
        for program in data["programs"]
        for week in program["weeks"]
        for r in week["routines"]
    } | {r["id"] for r in data["standalone"]}
    assert routine_id in all_routine_ids


def test_routines_invalid_view_is_422(auth_client):
    resp = auth_client.get("/api/routines?view=bogus")
    assert resp.status_code == 422


def test_routine_preview_unknown_returns_404(auth_client):
    resp = auth_client.get("/api/routines/999999/preview")
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Routine not found"}


def test_routine_preview_shape(auth_client, db, unique):
    _, routine_id, exercise_id = _make_program_with_routine(db, unique)
    resp = auth_client.get(f"/api/routines/{routine_id}/preview")
    assert resp.status_code == 200
    data = resp.json()
    assert data["routine"]["id"] == routine_id
    assert data["exercises"][0]["exercise_id"] == exercise_id
    assert data["exercises"][0]["target"] == "3 × 8–10 · rest 90s"


def test_activate_program_resets_week_only_when_not_already_active(auth_client, db, unique):
    program_id, _, _ = _make_program_with_routine(db, unique)
    # dirty the shared program_week so we can prove activation resets it
    db.execute("UPDATE program_state SET program_week = 2 WHERE id = 1")
    db.commit()

    resp = auth_client.post(f"/api/programs/{program_id}/activate")
    assert resp.status_code == 200
    assert resp.json() == {"id": program_id, "is_active": True, "program_week": 1}

    # dirty it again and re-activate the *same already-active* program: must
    # NOT reset it a second time, matching the existing HTML behavior
    db.execute("UPDATE program_state SET program_week = 2 WHERE id = 1")
    db.commit()
    resp2 = auth_client.post(f"/api/programs/{program_id}/activate")
    assert resp2.json()["program_week"] == 2


def test_delete_routine_preserves_set_log_history(auth_client, db, unique):
    _, routine_id, exercise_id = _make_program_with_routine(db, unique)
    now = utcnow()
    workout_id = db.execute(
        "INSERT INTO workout (routine_id, started_at, finished_at, is_deload) "
        "VALUES (?, ?, ?, 0)",
        (routine_id, now, now),
    ).lastrowid
    db.execute(
        "INSERT INTO set_log (workout_id, exercise_id, set_number, set_type, weight_kg, "
        "reps, was_suggested, logged_at) VALUES (?, ?, 1, 'normal', 60, 8, 1, ?)",
        (workout_id, exercise_id, now),
    )
    db.commit()

    resp = auth_client.delete(f"/api/routines/{routine_id}")
    assert resp.status_code == 204

    assert db.execute("SELECT id FROM routine WHERE id = ?", (routine_id,)).fetchone() is None
    workout = db.execute("SELECT routine_id FROM workout WHERE id = ?", (workout_id,)).fetchone()
    assert workout is not None and workout["routine_id"] is None
    set_count = db.execute(
        "SELECT COUNT(*) FROM set_log WHERE workout_id = ?", (workout_id,)
    ).fetchone()[0]
    assert set_count == 1


def test_archive_and_reactivate_routine_round_trip(auth_client, db, unique):
    _, routine_id, _ = _make_program_with_routine(db, unique)
    archived = auth_client.post(f"/api/routines/{routine_id}/archive")
    assert archived.json() == {"id": routine_id, "is_archived": True}
    reactivated = auth_client.post(f"/api/routines/{routine_id}/reactivate")
    assert reactivated.json() == {"id": routine_id, "is_archived": False}


def test_archive_unknown_routine_is_404(auth_client):
    resp = auth_client.post("/api/routines/999999/archive")
    assert resp.status_code == 404
