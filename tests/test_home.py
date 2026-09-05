def test_home_requires_auth(client):
    assert client.get("/api/home").status_code == 401


def test_home_returns_expected_shape(auth_client):
    resp = auth_client.get("/api/home")
    assert resp.status_code == 200
    data = resp.json()
    assert {
        "program", "sessions", "deload", "in_progress",
        "calendar", "volume", "progression", "audit",
    } <= data.keys()
    assert {"completed", "required"} <= data["sessions"].keys()
    assert {"active", "deferred", "weeks_to_next"} <= data["deload"].keys()
    assert {"points", "latest_kg", "latest_is_pr"} <= data["volume"].keys()
    assert {"ready", "stalled", "completed_weeks", "weeks_since_deload", "lifts"} <= data["progression"].keys()
    # the seed program ("starter") is active by default in a fresh database
    assert data["program"] is not None
    assert data["program"]["name"] == "starter"
