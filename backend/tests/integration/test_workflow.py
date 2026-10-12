"""End-to-end workflow through the HTTP API: upload -> validation -> job ->
background execution -> results -> visualisation data -> scenario -> reports."""

import numpy as np
from astropy.time import Time

from astral.core.frames import Frame
from astral.core.parsers import ingest
from astral.core.propagation import make_propagator, select_records
from astral.core.screening import ScreeningConfig, screen
from astral.core.synthetic import demo_catalogue, synthetic_cdm
from astral.services.jobs import run_pending_sync
from tests.conftest import login

EPOCH = Time("2026-10-10T00:00:00", scale="utc")


def test_full_screening_workflow(app, users):
    c = login(app, users["bob"])
    pid = c.post("/api/v1/projects", json={"name": "Workflow"}).json()["id"]
    tle = demo_catalogue(EPOCH, n_background=10, n_engineered=3, seed=3)
    r = c.post(f"/api/v1/projects/{pid}/datasets", files={"file": ("cat.tle", tle.encode())}, data={"name": "cat"})
    assert r.status_code == 201, r.text
    dv = r.json()
    assert dv["format"] == "TLE" and dv["stats"]["records"] == 16
    # stale-data warnings expected (epoch in the past relative to 'now'), but no errors
    det = c.get(f"/api/v1/projects/{pid}/dataset-versions/{dv['id']}").json()
    assert det["file"]["sha256"] and det["snapshot_sha256"]
    cat = c.get(f"/api/v1/projects/{pid}/catalogue", params={"vid": dv["id"], "limit": 5}).json()
    assert cat["total"] == 16 and len(cat["items"]) == 5
    cfg = {"kind": "screening", "start_utc": "2026-10-10T00:00:00Z", "duration_hours": 36, "step_s": 30, "threshold_km": 10.0}
    r = c.post(f"/api/v1/projects/{pid}/jobs", json={"dataset_version_id": dv["id"], "config": cfg}, headers={"Idempotency-Key": "k1"})
    assert r.status_code == 202, r.text
    job = r.json()
    r2 = c.post(f"/api/v1/projects/{pid}/jobs", json={"dataset_version_id": dv["id"], "config": cfg}, headers={"Idempotency-Key": "k1"})
    assert r2.json()["id"] == job["id"] and r2.json()["created"] is False
    assert run_pending_sync() >= 1
    job = c.get(f"/api/v1/projects/{pid}/jobs/{job['id']}").json()
    assert job["status"] == "succeeded", job
    assert job["stats"]["encounters"] >= 1 and job["software"]["sgp4"]
    encs = c.get(f"/api/v1/projects/{pid}/encounters", params={"job_id": job["id"]}).json()["items"]
    assert encs
    e = encs[0]
    # TLE inputs: Pc must NOT be computed
    assert e["pc_status"] == "INSUFFICIENT_DATA_FOR_PC" and e["pc_value"] is None
    assert any(f.startswith("TLE_ACCURACY_LIMITED") for f in e["flags"])
    detail = c.get(f"/api/v1/projects/{pid}/encounters/{e['id']}").json()
    assert detail["probability"][0]["status"] == "INSUFFICIENT_DATA_FOR_PC"
    assert "carry no covariance" in " ".join(detail["probability"][0]["result"]["reasons"])
    rel = c.get(f"/api/v1/projects/{pid}/encounters/{e['id']}/relative-motion", params={"span_s": 300, "points": 61}).json()
    assert abs(min(rel["range_km"]) - e["miss_km"]) < 0.05
    pos = c.get(f"/api/v1/projects/{pid}/viz/positions", params={"vid": dv["id"], "at": "2026-10-10T06:00:00Z"}).json()
    assert pos["frame"] == "GCRF" and len(pos["objects"]) == 16
    tr = c.get(f"/api/v1/projects/{pid}/viz/tracks", params={"vid": dv["id"], "start": "2026-10-10T06:00:00Z", "duration_s": 3600,
                                                             "step_s": 120, "limit": 10, "include": e["secondary_id"]}).json()
    assert tr["shown_objects"] == 10 and tr["total_objects"] == 16 and tr["samples"] == 31
    assert tr["objects"][0]["object_id"] == e["secondary_id"]  # requested objects come first
    assert len(tr["objects"][0]["r"]) == 31 * 3
    # first sample equals the single-instant position endpoint (same propagator, same frame)
    p0 = next(o for o in pos["objects"] if o["object_id"] == e["secondary_id"])
    r0 = tr["objects"][0]["r"][:3]
    assert all(abs(a - b) < 0.1 for a, b in zip(r0, p0["r_km"]))
    traj = c.get(f"/api/v1/projects/{pid}/viz/trajectory", params={"vid": dv["id"], "object_id": e["primary_id"], "start": "2026-10-10T00:00:00Z"}).json()
    assert len(traj["r_km"]) == 200
    mo = c.get(f"/api/v1/projects/{pid}/encounters/{e['id']}/maneuver-options").json()
    assert abs(mo["baseline_miss_km"] - e["miss_km"]) < 1e-3  # baseline equals the screening result
    assert len(mo["options"]) == 3 * 5 * 4 and mo["label"].startswith("SIMULATION ONLY")
    assert "recommend" not in str(mo["options"]).lower()
    sc = c.post(f"/api/v1/projects/{pid}/encounters/{e['id']}/scenarios",
                json={"name": "T+0.1", "burn_minutes_before_tca": 90, "dv_t_m_s": 0.1, "screen_other_objects": True})
    assert sc.status_code == 201, sc.text
    res = sc.json()["result"]
    assert res["label"].startswith("SIMULATION ONLY") and res["baseline"]["miss_km"] is not None
    for fmt in ("pdf", "csv", "json"):
        rr = c.post(f"/api/v1/projects/{pid}/jobs/{job['id']}/reports", params={"fmt": fmt})
        assert rr.status_code == 201, rr.text
        d = c.get(f"/api/v1/projects/{pid}/reports/{rr.json()['id']}/download")
        assert d.status_code == 200 and len(d.content) > 100
    oem = c.get(f"/api/v1/projects/{pid}/dataset-versions/{dv['id']}/export/oem",
                params={"object_id": e["primary_id"], "start": "2026-10-10T00:00:00Z", "duration_s": 3600})
    assert oem.status_code == 200 and "CCSDS_OEM_VERS" in oem.text
    # rerun is reproducible
    rr = c.post(f"/api/v1/projects/{pid}/jobs/{job['id']}/rerun").json()
    run_pending_sync()
    cmp = c.get(f"/api/v1/projects/{pid}/jobs/{job['id']}/compare/{rr['id']}").json()
    assert cmp["same_dataset_version"] and cmp["same_config"]
    assert all(abs(row.get("miss_change_km", 0)) < 1e-9 for row in cmp["rows"])


def test_cdm_assessment_computes_pc_with_covariance(app, users):
    c = login(app, users["bob"])
    pid = c.post("/api/v1/projects", json={"name": "CDM"}).json()["id"]
    res = ingest(demo_catalogue(EPOCH, n_background=0, n_engineered=2, seed=3), reference_time=EPOCH)
    chosen, _ = select_records(res.records)
    sr = screen({k: make_propagator(v) for k, v in chosen.items()}, ScreeningConfig(start=EPOCH, duration_s=72 * 3600, threshold_km=10))
    e = sr.encounters[0]
    cdm = synthetic_cdm(e.primary_state[:3], e.primary_state[3:], e.secondary_state[:3], e.secondary_state[3:], e.tca, Frame(e.frame),
                        ids=(e.primary, e.secondary))
    dv = c.post(f"/api/v1/projects/{pid}/datasets", files={"file": ("a.cdm", cdm.encode())}).json()
    # without HBR -> insufficient
    j1 = c.post(f"/api/v1/projects/{pid}/jobs", json={"dataset_version_id": dv["id"], "config": {"kind": "cdm_assessment"}}).json()
    j2 = c.post(f"/api/v1/projects/{pid}/jobs", json={"dataset_version_id": dv["id"],
                                                      "config": {"kind": "cdm_assessment", "hbr_m": 20, "monte_carlo_samples": 400000}}).json()
    run_pending_sync()
    e1 = c.get(f"/api/v1/projects/{pid}/encounters", params={"job_id": j1["id"]}).json()["items"][0]
    e2 = c.get(f"/api/v1/projects/{pid}/encounters", params={"job_id": j2["id"]}).json()["items"][0]
    assert e1["pc_status"] == "INSUFFICIENT_DATA_FOR_PC" and e1["pc_value"] is None
    assert e2["pc_status"] == "COMPUTED" and 0 <= e2["pc_value"] <= 1
    assert abs(e2["miss_km"] - e.geometry["miss_km"]) < 1e-3
    det = c.get(f"/api/v1/projects/{pid}/encounters/{e2['id']}").json()
    mc = det["probability"][0]["result"]["details"]["monte_carlo_crosscheck"]
    lo, hi = mc["ci95"]
    width = hi - lo
    assert lo - width <= e2["pc_value"] <= hi + width
    rel = c.get(f"/api/v1/projects/{pid}/encounters/{e2['id']}/relative-motion", params={"span_s": 600, "points": 241}).json()
    assert max(abs(t) for t in rel["t_s"]) <= 120.0  # rectilinear CDM view is limited to ±120 s
    assert abs(min(rel["range_km"]) - e2["miss_km"]) < 1e-3
    exp = c.get(f"/api/v1/projects/{pid}/encounters/{e2['id']}/export/cdm")
    assert exp.status_code == 200 and "COLLISION_PROBABILITY" in exp.text
    # exported CDM re-parses with covariances intact
    from astral.core.parsers.cdm import parse_cdm_kvn

    recs, f = parse_cdm_kvn(exp.text)
    assert len(recs) == 2 and all(r.covariance is not None for r in recs)
    assert np.allclose(recs[0].covariance.matrix, recs[0].covariance.matrix.T)


def test_invalid_upload_and_review_flow(app, users):
    c = login(app, users["bob"])
    pid = c.post("/api/v1/projects", json={"name": "Review"}).json()["id"]
    r = c.post(f"/api/v1/projects/{pid}/datasets", files={"file": ("x.txt", b"not orbital data")})
    assert r.status_code == 422 and r.json()["error"]["code"] == "UPLOAD_REJECTED"
    r = c.post(f"/api/v1/projects/{pid}/datasets", files={"file": ("x.bin", b"\x00\x01\x02" * 100)})
    assert r.status_code == 422
    tle = demo_catalogue(EPOCH, n_background=2, n_engineered=1, seed=1)
    lines = tle.splitlines()
    bad = "\n".join(lines + [lines[0], lines[1], lines[2][:-1] + str((int(lines[2][-1]) + 1) % 10)]) + "\n"
    dv = c.post(f"/api/v1/projects/{pid}/datasets", files={"file": ("bad.tle", bad.encode())}).json()
    assert dv["status"] == "needs_review"
    cfg = {"kind": "screening", "start_utc": "2026-10-10T00:00:00Z", "duration_hours": 1}
    r = c.post(f"/api/v1/projects/{pid}/jobs", json={"dataset_version_id": dv["id"], "config": cfg})
    assert r.status_code == 422 and "approve" in r.json()["error"]["message"]
    f = c.get(f"/api/v1/projects/{pid}/dataset-versions/{dv['id']}/findings", params={"severity": "error"}).json()
    assert f["total"] >= 1 and f["items"][0]["code"] == "TLE_CHECKSUM"
    assert c.post(f"/api/v1/projects/{pid}/dataset-versions/{dv['id']}/approve").json()["status"] == "approved"
    r = c.post(f"/api/v1/projects/{pid}/jobs", json={"dataset_version_id": dv["id"], "config": cfg})
    assert r.status_code == 202
    bad_cfg = {"kind": "screening", "start_utc": "2026-10-10T00:00:00Z", "duration_hours": 1, "step_s": 5000}
    r = c.post(f"/api/v1/projects/{pid}/jobs", json={"dataset_version_id": dv["id"], "config": bad_cfg})
    assert r.status_code == 422
    csv = c.get(f"/api/v1/projects/{pid}/dataset-versions/{dv['id']}/validation-report.csv")
    assert csv.status_code == 200 and "TLE_CHECKSUM" in csv.text


def test_health_and_openapi(app):
    from fastapi.testclient import TestClient

    c = TestClient(app)
    assert c.get("/api/v1/health/live").json()["status"] == "ok"
    r = c.get("/api/v1/health/ready")
    assert r.json()["checks"]["database"]["ok"] is True
    spec = c.get("/api/v1/openapi.json").json()
    assert "/api/v1/projects/{pid}/jobs" in spec["paths"]
