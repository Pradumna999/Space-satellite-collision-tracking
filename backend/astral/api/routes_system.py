"""Health, readiness, metrics, ML laboratory, audit log."""

from __future__ import annotations

import threading
import time
from datetime import UTC, datetime, timedelta
from importlib.metadata import version as pkg_version

import psutil
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from .. import ALGORITHM_VERSIONS, __version__
from ..core.timeutil import leap_second_table_expiry
from ..db.models import AnalysisJob, AuditEvent, MLModel, ProviderFetch, SystemInfo, User
from ..db.session import SessionLocal, get_db
from ..ml.dataset import generate
from ..ml.train import train
from ..services import audit, storage
from ..settings import get_settings
from .deps import api_error, current_user, paginate, require_admin

router = APIRouter(prefix="/api/v1", tags=["system"])
_STARTED = time.time()


@router.get("/health/live")
def live():
    return {"status": "ok"}


@router.get("/health/ready")
def ready(request: Request, db: Session = Depends(get_db)):
    checks = {}
    try:
        db.execute(text("SELECT 1"))
        checks["database"] = {"ok": True}
    except Exception as exc:  # report, do not raise
        checks["database"] = {"ok": False, "error": type(exc).__name__}
    try:
        k, _ = storage.put("uploads", b"health")
        storage.delete(k)
        checks["object_store"] = {"ok": True}
    except Exception as exc:
        checks["object_store"] = {"ok": False, "error": type(exc).__name__}
    worker = getattr(request.app.state, "worker", None)
    s = get_settings()
    if s.worker_mode == "inprocess":
        beat = worker.last_beat if worker else None
        alive = bool(worker and worker.thread and worker.thread.is_alive() and beat and datetime.now(UTC) - beat < timedelta(seconds=30))
        checks["worker"] = {"ok": alive, "mode": "inprocess", "last_beat": beat.isoformat() if beat else None}
    else:
        last = db.scalar(select(func.max(AnalysisJob.heartbeat_at)).where(AnalysisJob.status == "running"))
        checks["worker"] = {"ok": True, "mode": "external", "note": "external workers report via job heartbeats", "last_job_heartbeat": last}
    exp = leap_second_table_expiry()
    checks["leap_second_table"] = {"ok": exp.datetime > datetime.utcnow(), "expires": exp.isot}  # noqa: DTZ003
    ok = all(c["ok"] for c in checks.values())
    return JSONResponse({"status": "ready" if ok else "degraded", "checks": checks}, status_code=200 if ok else 503)


@router.get("/system/info")
def info(_: User = Depends(current_user), db: Session = Depends(get_db)):
    s = get_settings()
    q = dict(db.execute(select(AnalysisJob.status, func.count()).group_by(AnalysisJob.status)).all())
    proc = psutil.Process()
    providers = db.execute(select(ProviderFetch.provider, ProviderFetch.status, func.max(ProviderFetch.fetched_at))
                           .group_by(ProviderFetch.provider, ProviderFetch.status)).all()
    bench = db.get(SystemInfo, "benchmark")
    return {
        "version": __version__, "profile": s.profile, "algorithms": ALGORITHM_VERSIONS,
        "dependencies": {p: pkg_version(p) for p in ("sgp4", "astropy", "numpy", "scipy", "scikit-learn", "fastapi", "sqlalchemy")},
        "uptime_s": round(time.time() - _STARTED), "queue": q, "worker_mode": s.worker_mode,
        "process": {"cpu_percent": proc.cpu_percent(interval=0.05), "rss_mb": round(proc.memory_info().rss / 1e6, 1),
                    "system_memory_percent": psutil.virtual_memory().percent, "cpus": psutil.cpu_count()},
        "limits": {"max_upload_mb": s.max_upload_mb, "max_objects_per_job": s.max_objects_per_job, "max_window_days": s.max_window_days,
                   "max_concurrent_jobs": s.max_concurrent_jobs, "max_jobs_per_user_per_hour": s.max_jobs_per_user_per_hour},
        "providers": [{"provider": p, "status": st, "last": t} for p, st, t in providers],
        "leap_second_table_expires": leap_second_table_expiry().isot,
        "benchmark": bench.value if bench else None,
        "readiness_statement": "Research and evaluation software. Not qualified for operational conjunction assessment.",
    }


@router.get("/admin/audit")
def audit_log(action: str | None = None, limit: int = 100, offset: int = 0, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    limit, offset = paginate(limit, offset)
    q = select(AuditEvent)
    if action:
        q = q.where(AuditEvent.action.like(f"{action[:50]}%"))
    total = db.scalar(select(func.count()).select_from(q.subquery()))
    rows = db.scalars(q.order_by(AuditEvent.id.desc()).limit(limit).offset(offset))
    return {"total": total, "items": [{"id": a.id, "at": a.occurred_at, "user_id": a.user_id, "action": a.action, "project_id": a.project_id,
                                       "target": a.target, "details": a.details, "outcome": a.outcome, "request_id": a.request_id, "ip": a.ip}
                                      for a in rows]}


# ------------------------------------------------------------------- ML lab

def _model(m: MLModel) -> dict:
    return {"id": m.id, "name": m.name, "version": m.version, "status": m.status, "training_data_origin": m.training_data_origin,
            "training_data_sha256": m.training_data_sha256, "artefact_sha256": m.artefact_sha256, "params": m.params, "metrics": m.metrics,
            "feature_schema": m.feature_schema, "seed": m.seed, "code_version": m.code_version, "created_at": m.created_at,
            "label": "EXPERIMENTAL — priority score for analyst review, not a probability of collision"}


@router.get("/ml/models")
def list_models(_: User = Depends(current_user), db: Session = Depends(get_db)):
    st = db.get(SystemInfo, "ml_training")
    return {"items": [_model(m) for m in db.scalars(select(MLModel).order_by(MLModel.id.desc()))], "training": st.value if st else None}


_train_lock = threading.Lock()


def train_and_register(user_id: int | None, n_groups: int = 3000, seed: int = 0) -> int:
    """Generate synthetic data, train, store artefact, register as experimental."""
    data = generate(n_groups, seed=20261011 + seed)
    out = train(data, seed=seed)
    key, sha = storage.put("models", out["model_bytes"], ".joblib")
    meta = out["meta"]
    db = SessionLocal()
    try:
        n = db.scalar(select(func.count()).select_from(MLModel).where(MLModel.name == meta["name"])) or 0
        m = MLModel(name=meta["name"], version=f"{n + 1}", status="experimental", artefact_key=key, artefact_sha256=sha,
                    training_data_sha256=meta["training_data_sha256"], training_data_origin=meta["training_data_origin"],
                    params={"algorithm": meta["algorithm"], **meta["params"], "selection": meta["selection"], "label_definition": meta["label_definition"],
                            "sklearn": meta["sklearn_version"], "data_seed": meta["data_seed"], "n_groups": n_groups},
                    metrics=meta["metrics"], feature_schema=meta["feature_schema"], seed=seed, code_version=meta["code_version"])
        db.add(m)
        db.flush()
        audit.record(db, "ml.train", user_id, target=f"model:{m.id}", details={"data_sha256": meta["training_data_sha256"]})
        db.commit()
        return m.id
    finally:
        db.close()


def _set_training(value: dict) -> None:
    db = SessionLocal()
    try:
        row = db.get(SystemInfo, "ml_training") or SystemInfo(key="ml_training", value={})
        row.value = value
        row.updated_at = datetime.now(UTC)
        db.merge(row)
        db.commit()
    finally:
        db.close()


@router.post("/ml/train", status_code=202)
def start_training(n_groups: int = 3000, seed: int = 0, admin: User = Depends(require_admin)):
    n_groups = int(min(max(n_groups, 200), 20000))
    if not _train_lock.acquire(blocking=False):
        raise api_error(409, "BUSY", "a training run is already in progress")

    def run():
        try:
            _set_training({"status": "running", "started": datetime.now(UTC).isoformat(), "n_groups": n_groups, "seed": seed})
            mid = train_and_register(admin.id, n_groups, seed)
            _set_training({"status": "succeeded", "model_id": mid, "finished": datetime.now(UTC).isoformat()})
        except Exception as exc:
            _set_training({"status": "failed", "error": f"{type(exc).__name__}: {exc}"[:500]})
        finally:
            _train_lock.release()

    threading.Thread(target=run, daemon=True, name="ml-train").start()
    return {"status": "started", "n_groups": n_groups, "seed": seed}


@router.post("/ml/models/{mid}/activate")
def activate(mid: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    m = db.get(MLModel, mid)
    if m is None:
        raise api_error(404, "NOT_FOUND", "model not found")
    for other in db.scalars(select(MLModel).where(MLModel.status == "active_experimental")):
        other.status = "experimental"
    m.status = "active_experimental"
    audit.record(db, "ml.activate", admin.id, target=f"model:{mid}")
    db.commit()
    return _model(m)


@router.post("/ml/models/{mid}/deactivate")
def deactivate(mid: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    m = db.get(MLModel, mid)
    if m is None:
        raise api_error(404, "NOT_FOUND", "model not found")
    m.status = "experimental"
    audit.record(db, "ml.deactivate", admin.id, target=f"model:{mid}")
    db.commit()
    return _model(m)
