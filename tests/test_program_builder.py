from app import ai_program
import app.main as main


def _program(name, routine, exercise):
    return {
        "name": name,
        "weeks": 1,
        "routines": [{"name": routine, "week": 1, "exercises": [{
            "name": exercise, "movement_pattern": "hinge", "muscle_group": "legs",
            "sets": 3, "rep_min": 8, "rep_max": 10, "rest_seconds": 120,
            "increment_kg": 2.5, "exercise_type": "weight_reps", "display_unit": "kg",
            "equipment": "barbell", "is_primary": True, "cue": "brace", "youtube_query": "deadlift form",
        }]}],
    }


def test_program_builder_requires_auth(client):
    assert client.get("/api/programs/builder").status_code == 401
    assert client.post("/api/programs/builder/message", json={"content": "three days"}).status_code == 401
    assert client.post("/api/programs/builder/apply").status_code == 401
    assert client.post("/api/programs/builder/discard").status_code == 401


def test_program_builder_message_preview_apply_and_discard(auth_client, db, unique, monkeypatch):
    program_name = unique("Builder Program")
    routine_name = unique("Builder Day")
    exercise_name = unique("Builder Deadlift")
    program = _program(program_name, routine_name, exercise_name)
    monkeypatch.setattr(ai_program, "generate_turn", lambda *_: {"message": "Here is a complete first draft.", "ready": True, "program": program})

    assert auth_client.get("/api/programs/builder").json() == {"messages": [], "plan": None}
    sent = auth_client.post("/api/programs/builder/message", json={"content": "Build me a two-day strength plan"})
    assert sent.status_code == 200
    assert sent.json()["state"] == "ok"
    assert sent.json()["plan"]["program"]["name"] == program_name
    assert db.execute("SELECT id FROM routine WHERE name = ?", (routine_name,)).fetchone() is None

    applied = auth_client.post("/api/programs/builder/apply")
    assert applied.status_code == 200
    assert applied.json()["result"]["routines"][0]["name"] == routine_name
    assert db.execute("SELECT id FROM routine WHERE name = ?", (routine_name,)).fetchone() is not None
    assert db.execute("SELECT id FROM program_draft WHERE id = 1").fetchone() is None
    assert auth_client.post("/api/programs/builder/discard").json() == {"ok": True}


def test_program_builder_preserves_multi_turn_draft(auth_client, unique, monkeypatch):
    program = _program(unique("Follow-up Program"), unique("Follow-up Day"), unique("Follow-up Exercise"))
    turns = iter([
        {"message": "How many days can you train?", "ready": False, "program": None},
        {"message": "Here is your program.", "ready": True, "program": program},
    ])
    monkeypatch.setattr(ai_program, "generate_turn", lambda *_: next(turns))

    first = auth_client.post("/api/programs/builder/message", json={"content": "I want to get stronger"})
    assert first.json()["plan"] is None
    second = auth_client.post("/api/programs/builder/message", json={"content": "Three days each week"})
    assert second.json()["plan"]["program"]["name"] == program["name"]
    draft = auth_client.get("/api/programs/builder").json()
    assert [message["role"] for message in draft["messages"]] == ["user", "assistant", "user", "assistant"]


def test_program_builder_limit_does_not_call_model(auth_client, monkeypatch):
    monkeypatch.setattr(main, "can_make_ai_call", lambda _db: False)
    monkeypatch.setattr(ai_program, "generate_turn", lambda *_: (_ for _ in ()).throw(AssertionError("must not call AI")))
    response = auth_client.post("/api/programs/builder/message", json={"content": "Build a plan"})
    assert response.json()["state"] == "limit"
