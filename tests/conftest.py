"""Shared pytest fixtures for the JSON API regression suite (v0.6 Phase 2.5).

Design note: this suite uses ONE SQLite file for the whole test session rather
than a fresh file per test. `app/db.py` creates its SQLAlchemy engine once, at
import time, bound to whatever `LIFTLOG_DB` was set to first — so per-test
file swapping isn't possible without editing that module (out of scope here;
see CLAUDE.md's "no premature abstraction" working agreement). Tests must
therefore create their own uniquely-named rows (routines/exercises/etc.)
rather than assume a pristine database, the same way a real multi-session use
of the app would accumulate data over time.

`LIFTLOG_DB`/`LIFTLOG_SECRET` are set here, at module level, before any `app.*`
module is imported anywhere in the test run — pytest imports conftest.py
before collecting test modules, so this ordering is safe.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

_db_dir = tempfile.mkdtemp(prefix="liftlog_test_")
_db_path = str(Path(_db_dir) / "test.db")

os.environ["LIFTLOG_DB"] = _db_path
os.environ["LIFTLOG_SECRET"] = "test-only-secret-never-used-for-anything-real"
# Tests must never reach the real Anthropic API; ai.py treats a missing key as
# "AI unavailable" (existing behavior), which is what every test expects.
os.environ.pop("ANTHROPIC_API_KEY", None)

subprocess.run(
    [sys.executable, "-m", "alembic", "upgrade", "head"],
    cwd=ROOT,
    env=os.environ,
    check=True,
    capture_output=True,
)

from fastapi.testclient import TestClient  # noqa: E402  (must follow env setup above)

from app.db import get_db  # noqa: E402
from app.main import app  # noqa: E402

TEST_SECRET = os.environ["LIFTLOG_SECRET"]


@pytest.fixture()
def client() -> TestClient:
    """An unauthenticated client — use to assert the 401 boundary."""
    return TestClient(app)


@pytest.fixture()
def auth_client() -> TestClient:
    """A client authenticated through the real login endpoint, so its cookie
    has the exact same attributes (path, etc.) a browser session would — a
    manually-seeded cookie can otherwise mismatch the one `logout` clears."""
    c = TestClient(app)
    login = c.post("/api/auth/login", json={"secret": TEST_SECRET})
    assert login.status_code == 200, login.text
    return c


@pytest.fixture()
def db():
    session = get_db()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def secret() -> str:
    """The test-only browser secret set above, for tests that exercise the
    real login round trip (`POST /api/auth/login`) rather than pre-seeding
    the session cookie via the `auth_client` fixture."""
    return TEST_SECRET


@pytest.fixture()
def unique(request) -> "callable[[str], str]":
    """A per-test-unique name generator, so tests can create their own
    exercises/routines/programs without colliding across the shared session
    database or across repeated runs against a leftover db file."""
    import itertools

    counter = itertools.count()

    def make(prefix: str) -> str:
        return f"{prefix} [{request.node.name}-{next(counter)}]"

    return make
