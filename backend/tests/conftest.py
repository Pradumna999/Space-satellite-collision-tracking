import os
import tempfile
from pathlib import Path

import pytest

_tmp = Path(tempfile.mkdtemp(prefix="astral-test-"))
os.environ.update({
    "ASTRAL_PROFILE": "test",
    "ASTRAL_DATABASE_URL": f"sqlite:///{(_tmp / 'test.db').as_posix()}",
    "ASTRAL_STORAGE_DIR": str(_tmp / "objects"),
    "ASTRAL_SECRET_KEY": "test-secret-key-not-for-production",
    "ASTRAL_RATE_LIMIT_PER_MINUTE": "100000",
    "ASTRAL_AUTH_RATE_LIMIT_PER_MINUTE": "1000",
    "ASTRAL_CELESTRAK_ENABLED": "false",
})


@pytest.fixture(scope="session")
def app():
    from astral.cli import migrate
    from astral.main import create_app

    migrate()
    return create_app()


@pytest.fixture(scope="session")
def users(app):
    from astral.db.session import SessionLocal
    from astral.services.auth import create_user

    db = SessionLocal()
    out = {}
    for key, admin in (("alice", True), ("bob", False), ("carol", False)):
        u = create_user(db, f"{key}@example.test", f"{key}-password-123", key.title(), is_admin=admin)
        out[key] = (u.email, f"{key}-password-123")
    db.close()
    return out


def login(app, creds):
    from fastapi.testclient import TestClient

    c = TestClient(app)
    r = c.post("/api/v1/auth/login", json={"email": creds[0], "password": creds[1]})
    assert r.status_code == 200, r.text
    c.headers["X-CSRF-Token"] = r.json()["csrf_token"]
    return c
