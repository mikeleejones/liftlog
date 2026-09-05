def test_settings_requires_auth(client):
    assert client.get("/api/settings").status_code == 401
    assert client.post("/api/settings/tokens", json={"name": "x"}).status_code == 401
    assert client.delete("/api/settings/tokens/1").status_code == 401
    assert client.post("/api/settings/objective", json={"objective": "x"}).status_code == 401
    assert client.post("/api/settings/bodyweight", json={"bodyweight_kg": 80}).status_code == 401
    assert client.post("/api/deload/defer").status_code == 401


def test_settings_shape(auth_client):
    resp = auth_client.get("/api/settings")
    assert resp.status_code == 200
    data = resp.json()
    assert {
        "deload", "weeks_since_deload", "completed_weeks",
        "counts", "objective", "bodyweight_kg", "tokens",
    } <= data.keys()
    assert {"active", "deferred"} <= data["deload"].keys()
    assert {"exercises", "workouts", "sets"} <= data["counts"].keys()


def test_token_create_and_revoke_round_trip(auth_client):
    created = auth_client.post("/api/settings/tokens", json={"name": "Shortcuts"})
    assert created.status_code == 200
    token_data = created.json()
    assert {"id", "name", "token", "created_at"} <= token_data.keys()
    assert token_data["name"] == "Shortcuts"
    token_id = token_data["id"]

    listed = auth_client.get("/api/settings").json()["tokens"]
    assert any(t["id"] == token_id for t in listed)
    # the secret itself is never listed back
    assert not any("token" in t for t in listed)

    revoked = auth_client.delete(f"/api/settings/tokens/{token_id}")
    assert revoked.status_code == 204
    missing = auth_client.delete(f"/api/settings/tokens/{token_id}")
    assert missing.status_code == 404

    listed_after = auth_client.get("/api/settings").json()["tokens"]
    assert not any(t["id"] == token_id for t in listed_after)


def test_token_create_defaults_name_when_blank(auth_client):
    created = auth_client.post("/api/settings/tokens", json={})
    assert created.status_code == 200
    assert created.json()["name"] == "unnamed token"
    auth_client.delete(f"/api/settings/tokens/{created.json()['id']}")


def test_objective_save_and_clear(auth_client):
    saved = auth_client.post("/api/settings/objective", json={"objective": "HYROX prep"})
    assert saved.status_code == 200
    assert saved.json() == {"objective": "HYROX prep"}
    assert auth_client.get("/api/settings").json()["objective"] == "HYROX prep"

    cleared = auth_client.post("/api/settings/objective", json={"objective": "  "})
    assert cleared.json() == {"objective": ""}


def test_bodyweight_save_and_non_positive_clears(auth_client):
    saved = auth_client.post("/api/settings/bodyweight", json={"bodyweight_kg": 82.5})
    assert saved.status_code == 200
    assert saved.json() == {"bodyweight_kg": 82.5}
    assert auth_client.get("/api/settings").json()["bodyweight_kg"] == 82.5

    cleared = auth_client.post("/api/settings/bodyweight", json={"bodyweight_kg": -1})
    assert cleared.json() == {"bodyweight_kg": None}

    cleared_null = auth_client.post("/api/settings/bodyweight", json={"bodyweight_kg": None})
    assert cleared_null.json() == {"bodyweight_kg": None}


def test_deload_defer_pushes_a_week(auth_client, db):
    before = db.execute("SELECT week_anchor FROM program_state WHERE id = 1").fetchone()["week_anchor"]
    resp = auth_client.post("/api/deload/defer")
    assert resp.status_code == 200
    assert resp.json()["deload_deferred_until"] > before

    row = db.execute("SELECT deload_deferred_until FROM program_state WHERE id = 1").fetchone()
    assert row["deload_deferred_until"] == resp.json()["deload_deferred_until"]

    # leave program_state clean for later tests in other modules
    db.execute("UPDATE program_state SET deload_deferred_until = NULL WHERE id = 1")
    db.commit()
