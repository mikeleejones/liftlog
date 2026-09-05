from app.db import utcnow


def _make_exercise(db, unique, **overrides):
    now = utcnow()
    name = unique("Test Bench Press")
    fields = {
        "movement_pattern": "horizontal_push",
        "muscle_group": "chest",
        **overrides,
    }
    exercise_id = db.execute(
        "INSERT INTO exercise (name, movement_pattern, muscle_group, created_at) "
        "VALUES (?, ?, ?, ?)",
        (name, fields["movement_pattern"], fields["muscle_group"], now),
    ).lastrowid
    db.commit()
    return exercise_id, name


def test_exercises_requires_auth(client):
    assert client.get("/api/exercises").status_code == 401


def test_exercise_search_finds_by_substring(auth_client, db, unique):
    _, name = _make_exercise(db, unique)
    needle = name.split(" [")[0][:12]
    resp = auth_client.get(f"/api/exercises?q={needle}")
    assert resp.status_code == 200
    data = resp.json()
    assert any(e["name"] == name for e in data["exercises"])


def test_exercise_detail_unknown_is_404(auth_client):
    resp = auth_client.get("/api/exercises/999999")
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Exercise not found"}


def test_exercise_detail_shape(auth_client, db, unique):
    exercise_id, _ = _make_exercise(db, unique)
    resp = auth_client.get(f"/api/exercises/{exercise_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["exercise"]["id"] == exercise_id
    assert data["history"] == []
    assert data["chart_points"] == []
    assert data["editable"] is True


def test_exercise_detail_page_renders(auth_client, db, unique):
    exercise_id, name = _make_exercise(db, unique)
    resp = auth_client.get(f"/exercise/{exercise_id}")
    assert resp.status_code == 200
    assert name in resp.text


def test_reset_progress_sets_timestamp_and_is_idempotent(auth_client, db, unique):
    exercise_id, _ = _make_exercise(db, unique)
    resp = auth_client.post(f"/api/exercises/{exercise_id}/reset-progress")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == exercise_id
    assert body["progress_reset_at"]

    row = db.execute(
        "SELECT progress_reset_at FROM exercise WHERE id = ?", (exercise_id,)
    ).fetchone()
    assert row["progress_reset_at"] == body["progress_reset_at"]


def test_reset_progress_unknown_is_404(auth_client):
    resp = auth_client.post("/api/exercises/999999/reset-progress")
    assert resp.status_code == 404
