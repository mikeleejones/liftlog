def test_login_rejects_invalid_secret(client):
    resp = client.post("/api/auth/login", json={"secret": "definitely-wrong"})
    assert resp.status_code == 401
    assert resp.json() == {"detail": "Invalid secret"}
    assert "liftlog_auth" not in resp.cookies


def test_login_sets_cookie_and_session_reflects_it(client, secret):
    resp = client.post("/api/auth/login", json={"secret": secret})
    assert resp.status_code == 200
    assert resp.json() == {"authenticated": True}
    assert "liftlog_auth" in resp.cookies

    session_resp = client.get("/api/auth/session")
    assert session_resp.json() == {"authenticated": True}


def test_session_is_false_when_unauthenticated(client):
    resp = client.get("/api/auth/session")
    assert resp.status_code == 200
    assert resp.json() == {"authenticated": False}


def test_logout_clears_cookie_and_is_idempotent(auth_client):
    first = auth_client.post("/api/auth/logout")
    assert first.status_code == 204
    assert auth_client.get("/api/auth/session").json() == {"authenticated": False}

    # calling logout again with no session cookie is still safe
    second = auth_client.post("/api/auth/logout")
    assert second.status_code == 204
