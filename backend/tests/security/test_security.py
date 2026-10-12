"""Security tests: authentication, authorisation, project isolation, CSRF,
upload limits, unsafe paths, injection, quotas, audit."""

import pytest
from astropy.time import Time
from fastapi.testclient import TestClient

from astral.core.synthetic import demo_catalogue
from astral.services import storage
from tests.conftest import login

EPOCH = Time("2026-10-10T00:00:00", scale="utc")


@pytest.fixture(scope="module")
def setup(app, users):
    bob = login(app, users["bob"])
    pid = bob.post("/api/v1/projects", json={"name": "Bob private"}).json()["id"]
    dv = bob.post(f"/api/v1/projects/{pid}/datasets", files={"file": ("c.tle", demo_catalogue(EPOCH, 2, 1, 1).encode())}).json()
    return bob, pid, dv


def test_unauthenticated_rejected(app):
    c = TestClient(app)
    for path in ("/api/v1/projects", "/api/v1/auth/me", "/api/v1/ml/models", "/api/v1/system/info"):
        assert c.get(path).status_code == 401


def test_bad_password_and_lockout(app, users):
    c = TestClient(app)
    email = users["carol"][0]
    for _ in range(5):
        assert c.post("/api/v1/auth/login", json={"email": email, "password": "wrong-password-x"}).status_code == 401
    r = c.post("/api/v1/auth/login", json={"email": email, "password": users["carol"][1]})
    assert r.status_code == 401 and "locked" in r.json()["error"]["message"]
    from datetime import UTC, datetime, timedelta

    from astral.db.models import User
    from astral.db.session import SessionLocal

    db = SessionLocal()
    u = db.query(User).filter_by(email=email).one()
    u.locked_until = datetime.now(UTC) - timedelta(minutes=1)
    db.commit()
    db.close()


def test_cross_project_isolation(app, users, setup):
    bob, pid, dv = setup
    carol = login(app, users["carol"])
    alice = login(app, users["alice"])  # admin: still no implicit data access
    for c in (carol, alice):
        assert c.get(f"/api/v1/projects/{pid}").status_code == 404
        assert c.get(f"/api/v1/projects/{pid}/datasets").status_code == 404
        assert c.get(f"/api/v1/projects/{pid}/catalogue", params={"vid": dv["id"]}).status_code == 404
        assert c.get(f"/api/v1/projects/{pid}/dataset-versions/{dv['id']}/raw").status_code == 404
    # Carol's own project cannot reach Bob's dataset version by id
    cpid = carol.post("/api/v1/projects", json={"name": "Carol"}).json()["id"]
    assert carol.get(f"/api/v1/projects/{cpid}/dataset-versions/{dv['id']}").status_code == 404
    r = carol.post(f"/api/v1/projects/{cpid}/jobs", json={"dataset_version_id": dv["id"], "config": {"kind": "cdm_assessment"}})
    assert r.status_code == 404
    assert carol.get(f"/api/v1/projects/{cpid}/catalogue", params={"vid": dv["id"]}).status_code == 404


def test_viewer_cannot_write(app, users, setup):
    bob, pid, dv = setup
    assert bob.post(f"/api/v1/projects/{pid}/members", json={"email": users["carol"][0], "role": "viewer"}).status_code == 201
    carol = login(app, users["carol"])
    assert carol.get(f"/api/v1/projects/{pid}/datasets").status_code == 200
    r = carol.post(f"/api/v1/projects/{pid}/datasets", files={"file": ("c.tle", b"x")})
    assert r.status_code == 403
    r = carol.post(f"/api/v1/projects/{pid}/jobs", json={"dataset_version_id": dv["id"], "config": {"kind": "cdm_assessment"}})
    assert r.status_code == 403
    assert carol.post(f"/api/v1/projects/{pid}/members", json={"email": users["carol"][0], "role": "owner"}).status_code == 403


def test_csrf_required_for_cookie_sessions(app, users, setup):
    bob, pid, _ = setup
    c = TestClient(app)
    c.post("/api/v1/auth/login", json={"email": users["bob"][0], "password": users["bob"][1]})
    r = c.post("/api/v1/projects", json={"name": "no csrf"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "CSRF"
    tok = bob.post("/api/v1/auth/tokens", json={"label": "ci", "days": 1}).json()["token"]
    api = TestClient(app)
    r = api.post("/api/v1/projects", json={"name": "via token"}, headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 201


def test_non_admin_cannot_administer(app, users):
    bob = login(app, users["bob"])
    assert bob.get("/api/v1/admin/users").status_code == 403
    assert bob.get("/api/v1/admin/audit").status_code == 403
    assert bob.post("/api/v1/ml/train").status_code == 403
    assert bob.post("/api/v1/admin/users", json={"email": "x@example.test", "display_name": "x", "password": "p" * 12}).status_code == 403


def test_upload_size_limit(app, users, setup, monkeypatch):
    bob, pid, _ = setup
    from astral.settings import get_settings

    monkeypatch.setattr(get_settings(), "max_upload_mb", 1)
    r = bob.post(f"/api/v1/projects/{pid}/datasets", files={"file": ("big.tle", b"1" * (2 * 1024 * 1024))})
    assert r.status_code == 413


def test_storage_keys_cannot_escape():
    for key in ("../etc/passwd", "uploads/../../x", "uploads/abc", "snapshots/" + "0" * 32 + "/../x", "C:\\windows"):
        with pytest.raises(storage.StorageError):
            storage.get(key)


def test_filename_never_becomes_path(app, users, setup):
    bob, pid, _ = setup
    r = bob.post(f"/api/v1/projects/{pid}/datasets", files={"file": ("../../../evil.tle", demo_catalogue(EPOCH, 1, 1, 2).encode())})
    assert r.status_code == 201
    det = bob.get(f"/api/v1/projects/{pid}/dataset-versions/{r.json()['id']}").json()
    assert "/" not in det["file"]["name"] and ".." not in det["file"]["name"].replace("...", "")


def test_injection_in_query_parameters(app, users, setup):
    bob, pid, dv = setup
    r = bob.get(f"/api/v1/projects/{pid}/catalogue", params={"vid": dv["id"], "q": "' OR 1=1 --"})
    assert r.status_code == 200 and r.json()["total"] == 0
    r = bob.get(f"/api/v1/projects/{pid}/catalogue", params={"vid": dv["id"], "sort": "object_id; DROP TABLE users"})
    assert r.status_code == 200


def test_job_quota(app, users, setup, monkeypatch):
    bob, pid, dv = setup
    from astral.settings import get_settings

    monkeypatch.setattr(get_settings(), "max_jobs_per_user_per_hour", 0)
    r = bob.post(f"/api/v1/projects/{pid}/jobs", json={"dataset_version_id": dv["id"], "config": {"kind": "cdm_assessment"}})
    assert r.status_code == 429


def test_security_headers_and_error_shape(app):
    c = TestClient(app)
    r = c.get("/api/v1/projects")
    assert r.headers["X-Content-Type-Options"] == "nosniff" and "frame-ancestors 'none'" in r.headers["Content-Security-Policy"]
    assert set(r.json()["error"]) >= {"code", "message", "request_id"}


def test_audit_records_and_redacts(app, users, setup):
    alice = login(app, users["alice"])
    items = alice.get("/api/v1/admin/audit", params={"limit": 500}).json()["items"]
    actions = {a["action"] for a in items}
    assert {"auth.login", "dataset.upload", "project.create"} <= actions
    assert all("password" not in str(a["details"]).lower() or "[redacted]" in str(a["details"]) for a in items)
