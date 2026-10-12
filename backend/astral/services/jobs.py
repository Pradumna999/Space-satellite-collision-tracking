"""Analysis jobs: submission, DB-backed queue, worker execution.

Error categories
----------------
DATA_ERROR          input data unusable for the requested analysis (no retry)
CONFIG_ERROR        invalid scientific configuration (no retry)
NUMERICAL_ERROR     numerical failure in a scientific routine (no retry)
TRANSIENT_INFRA     database/storage hiccup (retried up to MAX_ATTEMPTS with backoff)
INTERNAL            software defect (no retry; inspect logs by job id)
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import socket
import threading
import time
from datetime import UTC, datetime, timedelta
from importlib.metadata import version as pkg_version

import numpy as np
from astropy.time import Time
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from .. import ALGORITHM_VERSIONS, __version__
from ..core.covariance import rtn_to_inertial
from ..core.encounter import geometry
from ..core.frames import Frame, convert
from ..core.pc import PcStatus, foster_2d, insufficient, monte_carlo_rectilinear
from ..core.propagation import make_propagator, select_records
from ..core.records import OrbitalRecord, RecordKind
from ..core.screening import Cancelled, ScreeningConfig, ScreeningConfigError, screen
from ..core.timeutil import iso_utc, parse_epoch
from ..db.models import AnalysisJob, DatasetVersion, Encounter, ProbabilityCalculation
from ..db.session import session_scope
from ..ml import features as mlf
from ..ml.infer import load_active
from ..settings import get_settings
from . import audit
from .datasets import load_snapshot

log = logging.getLogger("astral.jobs")
MAX_ATTEMPTS = 3
HEARTBEAT_STALE_S = 600


class JobError(Exception):
    category = "INTERNAL"


class DataError(JobError):
    category = "DATA_ERROR"


class ConfigError(JobError):
    category = "CONFIG_ERROR"


class NumericalError(JobError):
    category = "NUMERICAL_ERROR"


class QuotaError(Exception):
    pass


class ScreeningJobConfig(BaseModel):
    kind: str = Field("screening", pattern="^screening$")
    start_utc: str
    duration_hours: float = Field(72.0, gt=0, le=14 * 24)
    step_s: float = Field(30.0, ge=0.5, le=600)
    threshold_km: float = Field(5.0, gt=0, le=200)
    primary_ids: list[str] | None = None
    hbr_m: float | None = Field(None, gt=0, le=1000)

    @field_validator("start_utc")
    @classmethod
    def _epoch(cls, v: str) -> str:
        parse_epoch(v.rstrip("Z"), "UTC")
        return v


class CdmJobConfig(BaseModel):
    kind: str = Field("cdm_assessment", pattern="^cdm_assessment$")
    hbr_m: float | None = Field(None, gt=0, le=1000)
    monte_carlo_samples: int = Field(0, ge=0, le=5_000_000)
    seed: int = 0


def parse_config(raw: dict) -> ScreeningJobConfig | CdmJobConfig:
    kind = raw.get("kind", "screening")
    if kind == "screening":
        return ScreeningJobConfig(**raw)
    if kind == "cdm_assessment":
        return CdmJobConfig(**raw)
    raise ValueError(f"unknown job kind {kind!r}")


def config_hash(cfg: dict, dv: DatasetVersion) -> str:
    payload = json.dumps({"config": cfg, "snapshot": dv.snapshot_sha256}, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def software_versions() -> dict:
    return {
        "astral": __version__,
        "algorithms": ALGORITHM_VERSIONS,
        "sgp4": pkg_version("sgp4"),
        "astropy": pkg_version("astropy"),
        "numpy": pkg_version("numpy"),
        "scipy": pkg_version("scipy"),
    }


def submit(db: Session, project_id: int, dv: DatasetVersion, raw_cfg: dict, user_id: int, idempotency_key: str | None = None,
           rerun_of: int | None = None) -> tuple[AnalysisJob, bool]:
    if dv.status not in ("validated", "approved"):
        raise ConfigError(f"dataset version {dv.id} is '{dv.status}'; review and approve it before analysis")
    cfg = parse_config(raw_cfg).model_dump()
    if idempotency_key:
        existing = db.scalar(select(AnalysisJob).where(AnalysisJob.project_id == project_id, AnalysisJob.idempotency_key == idempotency_key,
                                                      AnalysisJob.created_by == user_id))
        if existing:
            return existing, False
    s = get_settings()
    hour_ago = datetime.now(UTC) - timedelta(hours=1)
    n = db.scalar(select(func.count()).select_from(AnalysisJob).where(AnalysisJob.created_by == user_id, AnalysisJob.created_at >= hour_ago))
    if n >= s.max_jobs_per_user_per_hour:
        raise QuotaError(f"job quota reached ({s.max_jobs_per_user_per_hour} per hour)")
    if cfg["kind"] == "screening" and cfg["duration_hours"] > s.max_window_days * 24:
        raise ConfigError(f"window exceeds configured maximum of {s.max_window_days} days")
    job = AnalysisJob(project_id=project_id, dataset_version_id=dv.id, kind=cfg["kind"], config=cfg, config_sha256=config_hash(cfg, dv),
                      idempotency_key=idempotency_key, created_by=user_id, software=software_versions(), rerun_of=rerun_of)
    db.add(job)
    db.flush()
    audit.record(db, "analysis.submit", user_id, project_id, f"job:{job.id}", {"kind": cfg["kind"], "dataset_version": dv.id})
    db.commit()
    return job, True


# ---------------------------------------------------------------- execution

def _update(job_id: int, **fields) -> None:
    with session_scope() as db:
        db.execute(update(AnalysisJob).where(AnalysisJob.id == job_id).values(**fields))


def _cancel_requested(job_id: int) -> bool:
    with session_scope() as db:
        return bool(db.scalar(select(AnalysisJob.cancel_requested).where(AnalysisJob.id == job_id)))


def _altitude(state: list[float]) -> float:
    return float(np.linalg.norm(state[:3]) - 6378.137)


def _store_encounter(db: Session, job: AnalysisJob, e: dict, names: dict, ages: dict, props: dict, cov_avail: str, pc_res, ml) -> Encounter:
    tca = Time(e["tca_utc"].rstrip("Z"), scale="utc")
    row = Encounter(job_id=job.id, primary_id=e["primary"], secondary_id=e["secondary"], primary_name=names.get(e["primary"]),
                    secondary_name=names.get(e["secondary"]), tca=tca.to_datetime(timezone=UTC), tca_iso=e["tca_utc"],
                    miss_km=float(e["geometry"]["miss_km"]), rel_speed_km_s=float(e["geometry"]["rel_speed_km_s"]),
                    geometry=e["geometry"], frame=e["frame"], primary_state=e["primary_state"], secondary_state=e["secondary_state"],
                    refinement_status=e["refinement_status"], flags=e["flags"], data_age_days=ages, propagators=props,
                    covariance_available=cov_avail, pc_status=pc_res.status.value, pc_value=pc_res.value)
    if ml is not None:
        row.ml_priority, row.ml_model_version = ml
    db.add(row)
    db.flush()
    db.add(ProbabilityCalculation(encounter_id=row.id, method=pc_res.method or "none", algorithm_version=ALGORITHM_VERSIONS["pc_foster_2d"],
                                  status=pc_res.status.value, value=pc_res.value, hbr_km=pc_res.details.get("hbr_km"),
                                  inputs={"covariance_available": cov_avail}, result=pc_res.to_dict()))
    return row


def _ml_scores(db: Session, encs: list[dict], ages: list[float], hours: list[float]):
    model = load_active(db)
    if model is None or not encs:
        return [None] * len(encs), None
    x = mlf.matrix([mlf.from_encounter(e["geometry"], _altitude(e["primary_state"]), a, h) for e, a, h in zip(encs, ages, hours)])
    try:
        prob, ood = model.score(x)
    except Exception:  # ML failure never fails the physical analysis
        log.exception("ML scoring failed")
        return [None] * len(encs), None
    return [(float(p), model.version + (" [OOD:" + ",".join(o) + "]" if o else "")) for p, o in zip(prob, ood)], model.version


def run_screening(job: AnalysisJob, dv: DatasetVersion, db: Session) -> None:
    cfg = ScreeningJobConfig(**job.config)
    records, _doc = load_snapshot(dv)
    chosen, notes = select_records(records)
    if len(chosen) < 2:
        raise DataError("fewer than two propagatable objects (GP elements or ephemerides) in dataset")
    if len(chosen) > get_settings().max_objects_per_job:
        raise ConfigError(f"{len(chosen)} objects exceeds limit {get_settings().max_objects_per_job}")
    props = {}
    for oid, rec in chosen.items():
        try:
            props[oid] = make_propagator(rec)
        except ValueError as exc:
            notes.append(f"{oid}: not propagatable ({exc})")
    start = parse_epoch(cfg.start_utc.rstrip("Z"), "UTC")
    sc = ScreeningConfig(start=start, duration_s=cfg.duration_hours * 3600, step_s=cfg.step_s, threshold_km=cfg.threshold_km,
                         primary_ids=cfg.primary_ids, max_objects=get_settings().max_objects_per_job)

    last = [0.0]

    def progress(f: float, msg: str) -> None:
        if time.monotonic() - last[0] > 1.0 or f >= 1.0:
            last[0] = time.monotonic()
            _update(job.id, progress=round(f, 4), progress_message=msg[:200], heartbeat_at=datetime.now(UTC))

    try:
        res = screen(props, sc, progress, lambda: _cancel_requested(job.id))
    except ScreeningConfigError as exc:
        raise ConfigError(str(exc)) from exc
    except (FloatingPointError, np.linalg.LinAlgError) as exc:
        raise NumericalError(str(exc)) from exc
    names = {r.object_id: r.object_name for r in records}
    encs = [e.to_dict() for e in res.encounters]
    ages, hours, age_maps = [], [], []
    for e in encs:
        tca = Time(e["tca_utc"].rstrip("Z"), scale="utc")
        am = {oid: round(float((tca - chosen[oid].epoch).jd), 4) for oid in (e["primary"], e["secondary"])}
        age_maps.append(am)
        ages.append(max(am.values()))
        hours.append(max((tca - start).sec / 3600.0, 0.0))
    ml_scores, ml_version = _ml_scores(db, encs, ages, hours)
    for e, am, ml in zip(encs, age_maps, ml_scores):
        reasons = []
        pr = {}
        cov_flags = []
        for oid in (e["primary"], e["secondary"]):
            rec = chosen[oid]
            pr[oid] = props[oid].method
            if rec.kind is RecordKind.GP_ELEMENTS:
                reasons.append(f"{oid}: GP mean elements (TLE/OMM) carry no covariance")
                cov_flags.append(False)
            elif rec.covariance is None:
                reasons.append(f"{oid}: ephemeris has no covariance")
                cov_flags.append(False)
            else:
                reasons.append(f"{oid}: covariance exists at {iso_utc(rec.covariance.epoch)} but covariance propagation to TCA is not implemented")
                cov_flags.append(True)
        flags = list(e["flags"])
        for oid, a in am.items():
            lim = 3.0 if chosen[oid].kind is RecordKind.GP_ELEMENTS else 7.0
            if a > lim:
                flags.append(f"STALE_INPUT:{oid}")
            if chosen[oid].kind is RecordKind.GP_ELEMENTS:
                flags.append(f"TLE_ACCURACY_LIMITED:{oid}")
        e["flags"] = sorted(set(flags))
        cov_avail = "both" if all(cov_flags) else ("partial" if any(cov_flags) else "none")
        _store_encounter(db, job, e, names, am, pr, cov_avail, insufficient(reasons), ml)
    job.stats = {**res.stats, "notes": notes, "ml_model": ml_version}
    job.warnings = res.warnings[:500]


def _inertial(rec: OrbitalRecord) -> tuple[np.ndarray, np.ndarray, np.ndarray | None]:
    r, v = convert(rec.position_km[None, :], rec.velocity_km_s[None, :], rec.frame, Frame.GCRF, rec.epoch)
    cov = None
    if rec.covariance is not None:
        c = rec.covariance.matrix
        if rec.covariance.frame == "RTN":
            # RTN of the object's own state in the CDM's frame; rotate using the GCRF state
            cov = rtn_to_inertial(c, r[0], v[0])
        else:
            src = Frame(rec.covariance.frame)
            if src is not Frame.GCRF:
                raise DataError(f"{rec.object_id}: inertial covariance in {src.value} requires rotation not yet implemented; supply RTN or GCRF")
            cov = c
    return r[0], v[0], cov


def run_cdm(job: AnalysisJob, dv: DatasetVersion, db: Session) -> None:
    cfg = CdmJobConfig(**job.config)
    records, _ = load_snapshot(dv)
    by_msg: dict[str, dict[str, OrbitalRecord]] = {}
    for r in records:
        if r.source_format == "CDM_KVN":
            by_msg.setdefault(r.extra["cdm"]["message_id"], {})[r.extra["cdm_role"]] = r
    if not by_msg:
        raise DataError("dataset contains no CDM records")
    hbr_km = cfg.hbr_m / 1000.0 if cfg.hbr_m else None
    names = {r.object_id: r.object_name for r in records}
    n = 0
    for mid, objs in sorted(by_msg.items()):
        if set(objs) != {"OBJECT1", "OBJECT2"}:
            job.warnings = [*job.warnings, f"CDM {mid}: incomplete object pair; skipped"]
            continue
        o1, o2 = objs["OBJECT1"], objs["OBJECT2"]
        r1, v1, c1 = _inertial(o1)
        r2, v2, c2 = _inertial(o2)
        g = geometry(r1, v1, r2, v2)
        pc = foster_2d(r1, v1, c1, r2, v2, c2, hbr_km)
        if cfg.monte_carlo_samples and pc.status is PcStatus.COMPUTED:
            pc.details["monte_carlo_crosscheck"] = monte_carlo_rectilinear(r2 - r1, v2 - v1, (c1 + c2)[:3, :3], hbr_km, cfg.monte_carlo_samples, cfg.seed)
        cdm = o1.extra["cdm"]
        pc.details["originator"] = {"pc": cdm.get("originator_pc"), "method": cdm.get("originator_pc_method"),
                                    "miss_distance_m": cdm.get("originator_miss_distance_m"), "note": "originator values shown for comparison only"}
        flags = []
        if abs(g.range_rate_km_s) > 1e-3:
            flags.append("CDM_STATES_NOT_AT_RANGE_MINIMUM")
        if cdm.get("originator_miss_distance_m") is not None and abs(cdm["originator_miss_distance_m"] / 1000 - g.miss_km) > 0.01:
            flags.append("MISS_DIFFERS_FROM_ORIGINATOR")
        e = {"primary": o1.object_id, "secondary": o2.object_id, "tca_utc": iso_utc(o1.epoch), "geometry": g.to_dict(),
             "frame": "GCRF", "primary_state": [*r1, *v1], "secondary_state": [*r2, *v2], "refinement_status": "SUPPLIED_TCA", "flags": flags}
        cov_avail = "both" if (c1 is not None and c2 is not None) else ("partial" if (c1 is not None or c2 is not None) else "none")
        _store_encounter(db, job, e, names, {}, {o1.object_id: "CDM-supplied state at TCA", o2.object_id: "CDM-supplied state at TCA"}, cov_avail, pc, None)
        n += 1
    job.stats = {"cdm_messages": len(by_msg), "encounters": n, "hbr_m": cfg.hbr_m}


def execute(job_id: int, worker_id: str) -> None:
    with session_scope() as db:
        job = db.get(AnalysisJob, job_id)
        dv = db.get(DatasetVersion, job.dataset_version_id)
        job.status = "running"
        job.started_at = datetime.now(UTC)
        job.attempts += 1
        job.worker_id = worker_id
        job.heartbeat_at = datetime.now(UTC)
        job.warnings = []
        db.commit()
        # Clear partial results of a previous failed attempt.
        for enc in db.scalars(select(Encounter).where(Encounter.job_id == job.id)):
            db.delete(enc)
        db.commit()
        try:
            if job.kind == "screening":
                run_screening(job, dv, db)
            elif job.kind == "cdm_assessment":
                run_cdm(job, dv, db)
            else:
                raise ConfigError(f"unknown job kind {job.kind}")
            job.status = "succeeded"
            job.progress = 1.0
            job.progress_message = "complete"
            audit.record(db, "analysis.complete", None, job.project_id, f"job:{job.id}", {"encounters": job.stats.get("encounters")})
        except Cancelled:
            db.rollback()
            job.status = "cancelled"
            job.progress_message = "cancelled by user"
        except JobError as exc:
            db.rollback()
            job.status = "failed"
            job.error_category = exc.category
            job.error_message = str(exc)[:2000]
        except OperationalError as exc:
            db.rollback()
            if job.attempts < MAX_ATTEMPTS:
                job.status = "queued"
                job.error_category = "TRANSIENT_INFRA"
                job.error_message = f"retrying after transient database error (attempt {job.attempts})"
                job.started_at = datetime.now(UTC) + timedelta(seconds=10 * 2**job.attempts)  # not-before for retry
            else:
                job.status = "failed"
                job.error_category = "TRANSIENT_INFRA"
                job.error_message = str(exc)[:500]
        except Exception as exc:  # defect: record category, never leak internals to API beyond the message
            log.exception("job %s failed with internal error", job_id)
            db.rollback()
            job.status = "failed"
            job.error_category = "INTERNAL"
            job.error_message = f"{type(exc).__name__}: {str(exc)[:500]}"
        job.finished_at = datetime.now(UTC) if job.status != "queued" else None
        db.commit()


def claim_next(worker_id: str) -> int | None:
    with session_scope() as db:
        now = datetime.now(UTC)
        stale = now - timedelta(seconds=HEARTBEAT_STALE_S)
        # Recover jobs whose worker died.
        for j in db.scalars(select(AnalysisJob).where(AnalysisJob.status == "running", AnalysisJob.heartbeat_at < stale)):
            if j.attempts >= MAX_ATTEMPTS:
                j.status, j.error_category, j.error_message = "failed", "TRANSIENT_INFRA", "worker lost repeatedly"
            else:
                j.status, j.progress_message = "queued", "requeued after worker loss"
        db.flush()
        running = db.scalar(select(func.count()).select_from(AnalysisJob).where(AnalysisJob.status == "running"))
        if running >= get_settings().max_concurrent_jobs:
            return None
        q = (select(AnalysisJob).where(AnalysisJob.status == "queued", or_(AnalysisJob.started_at.is_(None), AnalysisJob.started_at <= now))
             .order_by(AnalysisJob.created_at).limit(1))
        if db.bind.dialect.name == "postgresql":
            q = q.with_for_update(skip_locked=True)
        job = db.scalar(q)
        if job is None:
            return None
        job.status = "running"
        job.worker_id = worker_id
        job.heartbeat_at = now
        return job.id


class Worker:
    def __init__(self) -> None:
        self.worker_id = f"{socket.gethostname()}:{os.getpid()}:{threading.get_ident()}"
        self._stop = threading.Event()
        self.thread: threading.Thread | None = None
        self.last_beat: datetime | None = None

    def run_forever(self, poll_s: float = 1.0) -> None:
        while not self._stop.is_set():
            self.last_beat = datetime.now(UTC)
            try:
                jid = claim_next(self.worker_id)
            except OperationalError:
                log.warning("queue poll failed; retrying")
                jid = None
            if jid is None:
                self._stop.wait(poll_s)
                continue
            log.info("job %s claimed by %s", jid, self.worker_id)
            execute(jid, self.worker_id)

    def start(self) -> None:
        self.thread = threading.Thread(target=self.run_forever, name="astral-worker", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self._stop.set()


def run_pending_sync() -> int:
    """Execute every queued job synchronously (tests and CLI)."""
    n = 0
    w = Worker()
    while True:
        jid = claim_next(w.worker_id)
        if jid is None:
            return n
        execute(jid, w.worker_id)
        n += 1


__all__ = ["submit", "Worker", "run_pending_sync", "parse_config", "DataError", "ConfigError", "QuotaError"]
