"""Jobs, encounters, visualisation data, scenarios, reports."""

from __future__ import annotations

import numpy as np
from astropy.time import Time, TimeDelta
from fastapi import APIRouter, Depends, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import ALGORITHM_VERSIONS
from ..core.frames import Frame, convert, earth_rotation_angle_deg, eop_table_end, rtn_basis, teme_to_gcrf_matrices
from ..core.maneuver import ManeuverSpec, maneuver_options, simulate
from ..core.propagation import make_propagator, select_records
from ..core.timeutil import TimeParseError, iso_utc, parse_epoch
from ..db.models import AnalysisJob, Dataset, DatasetVersion, Encounter, ProbabilityCalculation, Report, Scenario, User
from ..db.session import get_db
from ..services import audit, reports, storage
from ..services.datasets import load_snapshot
from ..services.jobs import ConfigError, QuotaError, submit
from .deps import analyst, api_error, current_user, paginate, viewer

router = APIRouter(prefix="/api/v1/projects/{pid}", tags=["analysis"])


def _job(j: AnalysisJob) -> dict:
    return {"id": j.id, "kind": j.kind, "status": j.status, "dataset_version_id": j.dataset_version_id, "config": j.config,
            "config_sha256": j.config_sha256, "progress": j.progress, "progress_message": j.progress_message, "attempts": j.attempts,
            "error_category": j.error_category, "error_message": j.error_message, "stats": j.stats, "warnings": j.warnings,
            "software": j.software, "rerun_of": j.rerun_of, "created_at": j.created_at, "started_at": j.started_at, "finished_at": j.finished_at,
            "cancel_requested": j.cancel_requested}


def _get_job(db: Session, pid: int, jid: int) -> AnalysisJob:
    j = db.get(AnalysisJob, jid)
    if j is None or j.project_id != pid:
        raise api_error(404, "NOT_FOUND", "job not found")
    return j


class JobIn(BaseModel):
    dataset_version_id: int
    config: dict


@router.post("/jobs", status_code=202)
def create_job(body: JobIn, access=Depends(analyst), user: User = Depends(current_user), db: Session = Depends(get_db),
               idempotency_key: str | None = Header(None, alias="Idempotency-Key", max_length=100)):
    p, _ = access
    dv = db.get(DatasetVersion, body.dataset_version_id)
    if dv is None or db.get(Dataset, dv.dataset_id).project_id != p.id:
        raise api_error(404, "NOT_FOUND", "dataset version not found")
    try:
        job, created = submit(db, p.id, dv, body.config, user.id, idempotency_key)
    except QuotaError as exc:
        raise api_error(429, "QUOTA", str(exc)) from None
    except (ConfigError, ValueError, TimeParseError) as exc:
        raise api_error(422, "INVALID_CONFIG", str(exc)) from None
    return {**_job(job), "created": created}


@router.get("/jobs")
def list_jobs(limit: int = 50, offset: int = 0, access=Depends(viewer), db: Session = Depends(get_db)):
    p, _ = access
    limit, offset = paginate(limit, offset)
    total = db.scalar(select(func.count()).select_from(AnalysisJob).where(AnalysisJob.project_id == p.id))
    rows = db.scalars(select(AnalysisJob).where(AnalysisJob.project_id == p.id).order_by(AnalysisJob.id.desc()).limit(limit).offset(offset))
    return {"total": total, "items": [_job(j) for j in rows]}


@router.get("/jobs/{jid}")
def get_job(jid: int, access=Depends(viewer), db: Session = Depends(get_db)):
    p, _ = access
    return _job(_get_job(db, p.id, jid))


@router.post("/jobs/{jid}/cancel")
def cancel_job(jid: int, access=Depends(analyst), user: User = Depends(current_user), db: Session = Depends(get_db)):
    p, _ = access
    j = _get_job(db, p.id, jid)
    if j.status == "queued":
        j.status = "cancelled"
        j.progress_message = "cancelled before start"
    elif j.status == "running":
        j.cancel_requested = True  # honoured at the next safe point in the screening loop
    else:
        raise api_error(409, "CONFLICT", f"job already {j.status}")
    audit.record(db, "analysis.cancel", user.id, p.id, f"job:{jid}")
    db.commit()
    return _job(j)


@router.post("/jobs/{jid}/rerun", status_code=202)
def rerun_job(jid: int, access=Depends(analyst), user: User = Depends(current_user), db: Session = Depends(get_db)):
    p, _ = access
    j = _get_job(db, p.id, jid)
    dv = db.get(DatasetVersion, j.dataset_version_id)
    try:
        nj, _ = submit(db, p.id, dv, j.config, user.id, rerun_of=j.id)
    except QuotaError as exc:
        raise api_error(429, "QUOTA", str(exc)) from None
    return _job(nj)


@router.get("/jobs/{a}/compare/{b}")
def compare_jobs(a: int, b: int, access=Depends(viewer), db: Session = Depends(get_db)):
    """Match encounters of two runs by object pair and TCA (±60 s)."""
    p, _ = access
    ja, jb = _get_job(db, p.id, a), _get_job(db, p.id, b)
    ea = list(db.scalars(select(Encounter).where(Encounter.job_id == ja.id)))
    eb = list(db.scalars(select(Encounter).where(Encounter.job_id == jb.id)))
    used = set()
    rows = []
    for x in ea:
        best = None
        for y in eb:
            if y.id in used or (x.primary_id, x.secondary_id) != (y.primary_id, y.secondary_id):
                continue
            dt = abs((x.tca - y.tca).total_seconds())
            if dt <= 60 and (best is None or dt < best[0]):
                best = (dt, y)
        if best:
            used.add(best[1].id)
            y = best[1]
            rows.append({"pair": [x.primary_id, x.secondary_id], "a": x.id, "b": y.id, "tca_shift_s": (y.tca - x.tca).total_seconds(),
                         "miss_a_km": x.miss_km, "miss_b_km": y.miss_km, "miss_change_km": y.miss_km - x.miss_km})
        else:
            rows.append({"pair": [x.primary_id, x.secondary_id], "a": x.id, "b": None, "miss_a_km": x.miss_km})
    for y in eb:
        if y.id not in used:
            rows.append({"pair": [y.primary_id, y.secondary_id], "a": None, "b": y.id, "miss_b_km": y.miss_km})
    same_inputs = ja.dataset_version_id == jb.dataset_version_id
    return {"a": _job(ja), "b": _job(jb), "same_dataset_version": same_inputs, "same_config": ja.config_sha256 == jb.config_sha256,
            "software_changed": ja.software != jb.software, "rows": rows}


# ----------------------------------------------------------------- encounters

def _enc(e: Encounter) -> dict:
    return {"id": e.id, "job_id": e.job_id, "primary_id": e.primary_id, "secondary_id": e.secondary_id, "primary_name": e.primary_name,
            "secondary_name": e.secondary_name, "tca_utc": e.tca_iso, "miss_km": e.miss_km, "rel_speed_km_s": e.rel_speed_km_s,
            "geometry": e.geometry, "frame": e.frame, "refinement_status": e.refinement_status, "flags": e.flags,
            "data_age_days": e.data_age_days, "propagators": e.propagators, "covariance_available": e.covariance_available,
            "pc_status": e.pc_status, "pc_value": e.pc_value, "ml_priority_experimental": e.ml_priority, "ml_model": e.ml_model_version}


def _get_enc(db: Session, pid: int, eid: int) -> tuple[Encounter, AnalysisJob]:
    e = db.get(Encounter, eid)
    if e is None:
        raise api_error(404, "NOT_FOUND", "encounter not found")
    j = db.get(AnalysisJob, e.job_id)
    if j.project_id != pid:
        raise api_error(404, "NOT_FOUND", "encounter not found")
    return e, j


@router.get("/encounters")
def list_encounters(job_id: int | None = None, max_miss_km: float | None = None, object_id: str | None = None, sort: str = "tca",
                    limit: int = 100, offset: int = 0, access=Depends(viewer), db: Session = Depends(get_db)):
    p, _ = access
    limit, offset = paginate(limit, offset)
    q = select(Encounter).join(AnalysisJob).where(AnalysisJob.project_id == p.id)
    if job_id:
        q = q.where(Encounter.job_id == job_id)
    if max_miss_km is not None:
        q = q.where(Encounter.miss_km <= max_miss_km)
    if object_id:
        q = q.where((Encounter.primary_id == object_id) | (Encounter.secondary_id == object_id))
    order = {"tca": Encounter.tca, "miss": Encounter.miss_km, "pc": Encounter.pc_value.desc(), "ml": Encounter.ml_priority.desc()}.get(sort, Encounter.tca)
    total = db.scalar(select(func.count()).select_from(q.subquery()))
    rows = db.scalars(q.order_by(order, Encounter.id).limit(limit).offset(offset))
    return {"total": total, "items": [_enc(e) for e in rows]}


@router.get("/encounters/{eid}")
def get_encounter(eid: int, access=Depends(viewer), db: Session = Depends(get_db)):
    p, _ = access
    e, j = _get_enc(db, p.id, eid)
    pcs = db.scalars(select(ProbabilityCalculation).where(ProbabilityCalculation.encounter_id == e.id))
    history = db.scalars(select(Encounter).join(AnalysisJob).where(AnalysisJob.project_id == p.id, Encounter.primary_id == e.primary_id,
                                                                  Encounter.secondary_id == e.secondary_id).order_by(Encounter.job_id))
    dv = db.get(DatasetVersion, j.dataset_version_id)
    ds = db.get(Dataset, dv.dataset_id)
    return {**_enc(e), "job": _job(j), "probability": [{"method": c.method, "algorithm_version": c.algorithm_version, "status": c.status,
                                                         "value": c.value, "result": c.result} for c in pcs],
            "dataset": {"id": ds.id, "name": ds.name, "version": dv.version, "synthetic": ds.is_synthetic, "snapshot_sha256": dv.snapshot_sha256},
            "history": [{"encounter_id": h.id, "job_id": h.job_id, "tca_utc": h.tca_iso, "miss_km": h.miss_km} for h in history
                        if abs((h.tca - e.tca).total_seconds()) < 3600]}


def _props_for_job(db: Session, j: AnalysisJob):
    dv = db.get(DatasetVersion, j.dataset_version_id)
    records, _ = load_snapshot(dv)
    chosen, _ = select_records(records)
    return records, chosen


@router.get("/encounters/{eid}/relative-motion")
def relative_motion(eid: int, span_s: float = 600, points: int = 241, access=Depends(viewer), db: Session = Depends(get_db)):
    """Relative position of the secondary in the primary's RTN frame around TCA,
    from the same propagators used for screening. Nominal states only."""
    p, _ = access
    e, j = _get_enc(db, p.id, eid)
    span_s = float(min(max(span_s, 10), 6 * 3600))
    points = int(min(max(points, 11), 2001))
    tca = Time(e.tca_iso.rstrip("Z"), scale="utc")
    if j.kind == "cdm_assessment":
        # A CDM gives states at TCA only. The short-encounter model used for Pc
        # assumes rectilinear *relative* motion, so show exactly that: Δr + Δv·t
        # in the primary's RTN frame fixed at TCA, over at most ±120 s.
        span_s = min(span_s, 120.0)
        offs = np.linspace(-span_s, span_s, points)
        st1, st2 = np.asarray(e.primary_state), np.asarray(e.secondary_state)
        b = rtn_basis(st1[:3], st1[3:])
        rel = (st2[:3] - st1[:3]) + np.outer(offs, st2[3:] - st1[3:])
        rtn = rel @ b.T
        return {"encounter_id": e.id, "tca_utc": e.tca_iso, "frame": "primary RTN at TCA", "units": {"t": "s from TCA", "position": "km"},
                "data_kind": "rectilinear relative motion from CDM states at TCA (the 2D Pc model's assumption; span limited to ±120 s)",
                "t_s": offs.round(3).tolist(), "rtn_km": rtn.round(6).tolist(), "range_km": np.linalg.norm(rel, axis=1).round(6).tolist()}
    offs = np.linspace(-span_s, span_s, points)
    _, chosen = _props_for_job(db, j)
    pa, pb = make_propagator(chosen[e.primary_id]), make_propagator(chosen[e.secondary_id])
    ra, rb = pa.propagate(tca, offs), pb.propagate(tca, offs)
    ok = ra.valid & rb.valid
    if not ok.any():
        raise api_error(409, "NO_STATES", "no valid states around TCA")
    r1, v1, r2 = ra.r_km, ra.v_km_s, rb.r_km
    kind = f"propagated: {pa.method} / {pb.method}"
    rel = r2 - r1
    rtn = np.array([rtn_basis(r1[k], v1[k]) @ rel[k] for k in range(points)])
    return {"encounter_id": e.id, "tca_utc": e.tca_iso, "frame": f"primary RTN ({e.frame}-based)", "units": {"t": "s from TCA", "position": "km"},
            "data_kind": kind, "t_s": offs.round(3).tolist(), "rtn_km": rtn.round(6).tolist(),
            "range_km": np.linalg.norm(rel, axis=1).round(6).tolist()}


@router.get("/viz/positions")
def viz_positions(vid: int, at: str | None = None, access=Depends(viewer), db: Session = Depends(get_db)):
    """Overview markers: one GCRF position per propagatable object at an instant."""
    p, _ = access
    dv = db.get(DatasetVersion, vid)
    if dv is None or db.get(Dataset, dv.dataset_id).project_id != p.id:
        raise api_error(404, "NOT_FOUND", "dataset version not found")
    try:
        t = parse_epoch(at.rstrip("Z"), "UTC") if at else Time.now()
    except TimeParseError as exc:
        raise api_error(422, "INVALID_TIME", str(exc)) from None
    records, _ = load_snapshot(dv)
    chosen, notes = select_records(records)
    out = []
    groups: dict[Frame, list] = {}
    for oid, rec in chosen.items():
        prop = make_propagator(rec)
        res = prop.propagate(t, np.array([0.0]))
        if res.valid[0]:
            groups.setdefault(res.frame, []).append((oid, rec, res.r_km[0], res.v_km_s[0], prop.method))
    for frame, items in groups.items():
        r = np.array([x[2] for x in items])
        v = np.array([x[3] for x in items])
        rg, vg = convert(r, v, frame, Frame.GCRF, Time([t] * len(items)))
        for (oid, rec, _, _, method), rr, vv in zip(items, rg, vg):
            out.append({"object_id": oid, "name": rec.object_name, "r_km": rr.round(3).tolist(), "v_km_s": vv.round(5).tolist(),
                        "age_days": round(float((t - rec.epoch).jd), 3), "kind": rec.kind.value, "method": method})
    era, real_ut1 = earth_rotation_angle_deg(t)
    notes = list(notes)
    if not real_ut1:
        notes.append("UT1-UTC unavailable for this instant (bundled IERS table ends "
                     f"{iso_utc(eop_table_end())}); Earth orientation approximated with UT1=UTC (visualisation only)")
    return {"at_utc": iso_utc(t), "frame": "GCRF", "earth_rotation_angle_deg": era, "earth_rotation_uses_ut1": real_ut1, "objects": out,
            "not_shown": len(chosen) - len(out), "notes": notes,
            "data_kind": "propagated nominal positions (no uncertainty)"}


@router.get("/viz/trajectory")
def viz_trajectory(vid: int, object_id: str, start: str, duration_s: float = 6000, points: int = 200, access=Depends(viewer),
                   db: Session = Depends(get_db)):
    p, _ = access
    dv = db.get(DatasetVersion, vid)
    if dv is None or db.get(Dataset, dv.dataset_id).project_id != p.id:
        raise api_error(404, "NOT_FOUND", "dataset version not found")
    duration_s = float(min(max(duration_s, 60), 3 * 86400))
    points = int(min(max(points, 10), 2000))
    t0 = parse_epoch(start.rstrip("Z"), "UTC")
    records, _ = load_snapshot(dv)
    chosen, _ = select_records(records)
    if object_id not in chosen:
        raise api_error(404, "NOT_FOUND", "object not propagatable in this dataset")
    prop = make_propagator(chosen[object_id])
    offs = np.linspace(0, duration_s, points)
    res = prop.propagate(t0, offs)
    ok = res.valid
    times = t0 + TimeDelta(offs[ok], format="sec")
    rg, _ = convert(res.r_km[ok], res.v_km_s[ok], res.frame, Frame.GCRF, times) if ok.any() else (np.zeros((0, 3)), None)
    return {"object_id": object_id, "frame": "GCRF", "start_utc": iso_utc(t0), "t_s": offs[ok].round(2).tolist(), "r_km": rg.round(3).tolist(),
            "data_kind": f"propagated nominal trajectory ({prop.method}); line segments between samples are visual interpolation"}


_PROP_CACHE: dict[str, tuple] = {}
_PROP_CACHE_MAX = 4


def _cached_propagators(dv: DatasetVersion):
    """Parsed records + propagators per immutable snapshot (keyed by its hash)."""
    hit = _PROP_CACHE.get(dv.snapshot_sha256)
    if hit is not None:
        return hit
    records, _ = load_snapshot(dv)
    chosen, notes = select_records(records)
    props = {}
    for oid, rec in chosen.items():
        try:
            props[oid] = make_propagator(rec)
        except ValueError:
            continue
    if len(_PROP_CACHE) >= _PROP_CACHE_MAX:
        _PROP_CACHE.pop(next(iter(_PROP_CACHE)))
    _PROP_CACHE[dv.snapshot_sha256] = (chosen, props, notes)
    return chosen, props, notes


def _display_order(chosen: dict, include: list[str]) -> list[str]:
    """Deterministic display priority: requested objects, then non-debris
    (active satellites, stations), then an even sample of the rest."""
    inc = [i for i in include if i in chosen]
    rest = [i for i in sorted(chosen) if i not in set(inc)]
    named = [i for i in rest if "DEB" not in (chosen[i].object_name or "").upper()]
    debris = [i for i in rest if i not in set(named)]
    # interleave debris so any prefix is spread across the catalogue
    k = max(1, len(debris) // 997)
    spread = [debris[j] for s in range(k) for j in range(s, len(debris), k)]
    return inc + named + spread


@router.get("/viz/tracks")
def viz_tracks(vid: int, start: str, duration_s: float = 10800, step_s: float = 120, limit: int = 500, include: str = "",
               access=Depends(viewer), db: Session = Depends(get_db)):
    """Positions of up to `limit` objects on a time grid, in GCRF, for client-side
    animation. One request covers a whole window; the browser interpolates
    between samples (visual interpolation only)."""
    p, _ = access
    dv = db.get(DatasetVersion, vid)
    if dv is None or db.get(Dataset, dv.dataset_id).project_id != p.id:
        raise api_error(404, "NOT_FOUND", "dataset version not found")
    try:
        t0 = parse_epoch(start.rstrip("Z"), "UTC")
    except TimeParseError as exc:
        raise api_error(422, "INVALID_TIME", str(exc)) from None
    duration_s = float(min(max(duration_s, 600), 24 * 3600))
    step_s = float(min(max(step_s, 10), 600))
    limit = int(min(max(limit, 10), 3000))
    chosen, props, notes = _cached_propagators(dv)
    order = [i for i in _display_order(chosen, [s for s in include.split(",") if s]) if i in props][:limit]
    offs = np.arange(0.0, duration_s + 1e-9, step_s)
    times = t0 + TimeDelta(offs, format="sec")
    rot_cache: dict[Frame, np.ndarray] = {}
    objects = []
    for oid in order:
        prop = props[oid]
        res = prop.propagate(t0, offs)
        r = res.r_km
        if res.frame is Frame.TEME:
            m = rot_cache.get(Frame.TEME)
            if m is None:
                m = rot_cache[Frame.TEME] = teme_to_gcrf_matrices(times)
            r = np.einsum("nij,nj->ni", m, np.nan_to_num(r))
        elif res.frame is not Frame.GCRF and res.valid.any():
            idx = np.where(res.valid)[0]
            rg, _ = convert(r[idx], res.v_km_s[idx], res.frame, Frame.GCRF, times[idx])
            r = np.full_like(r, np.nan)
            r[idx] = rg
        flat = np.where(res.valid[:, None], np.round(r, 1), np.nan).ravel()
        rec = chosen[oid]
        objects.append({"object_id": oid, "name": rec.object_name, "kind": rec.kind.value,
                        "age_days": round(float((t0 - rec.epoch).jd), 2),
                        "r": [None if not np.isfinite(x) else float(x) for x in flat]})
    return {"start_utc": iso_utc(t0), "step_s": step_s, "samples": len(offs), "frame": "GCRF", "total_objects": len(props),
            "shown_objects": len(objects), "objects": objects, "notes": notes,
            "data_kind": "propagated nominal positions; motion between samples is visual interpolation"}


# ------------------------------------------------------------------ scenarios

class ScenarioIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    burn_minutes_before_tca: float = Field(gt=0, le=7 * 24 * 60)
    dv_r_m_s: float = Field(0.0, ge=-50, le=50)
    dv_t_m_s: float = Field(0.0, ge=-50, le=50)
    dv_n_m_s: float = Field(0.0, ge=-50, le=50)
    spacecraft_mass_kg: float | None = Field(None, gt=0, le=1e6)
    isp_s: float | None = Field(None, gt=0, le=1e4)
    screen_other_objects: bool = True


@router.post("/encounters/{eid}/scenarios", status_code=201)
def create_scenario(eid: int, body: ScenarioIn, access=Depends(analyst), user: User = Depends(current_user), db: Session = Depends(get_db)):
    p, _ = access
    e, j = _get_enc(db, p.id, eid)
    if j.kind != "screening":
        raise api_error(409, "NOT_SUPPORTED", "scenarios need propagatable inputs; CDM-only encounters have states at TCA only")
    dv = db.get(DatasetVersion, j.dataset_version_id)
    _, props, _ = _cached_propagators(dv)
    tca = Time(e.tca_iso.rstrip("Z"), scale="utc")
    spec = ManeuverSpec(burn_time=tca - TimeDelta(body.burn_minutes_before_tca * 60, format="sec"),
                        dv_rtn_m_s=(body.dv_r_m_s, body.dv_t_m_s, body.dv_n_m_s), spacecraft_mass_kg=body.spacecraft_mass_kg, isp_s=body.isp_s)
    others = props if body.screen_other_objects else None
    try:
        res = simulate(props[e.primary_id], props[e.secondary_id], tca, spec, others, j.config.get("threshold_km", 5.0))
    except ValueError as exc:
        raise api_error(422, "INVALID_SCENARIO", str(exc)) from None
    result = res.to_dict()
    # How many other objects the new trajectory was actually checked against (0 = not checked).
    result["others_checked"] = max(len(others) - 2, 0) if others else 0
    sc = Scenario(project_id=p.id, encounter_id=e.id, name=body.name, params=body.model_dump(), result=result,
                  algorithm_version=ALGORITHM_VERSIONS["maneuver_sim"], created_by=user.id)
    db.add(sc)
    db.flush()
    audit.record(db, "scenario.create", user.id, p.id, f"scenario:{sc.id}", {"encounter": e.id})
    db.commit()
    return {"id": sc.id, "name": sc.name, "params": sc.params, "result": sc.result, "created_at": sc.created_at}


_OPTIONS_CACHE: dict[tuple[int, str, int], dict] = {}


@router.get("/encounters/{eid}/maneuver-options")
def maneuver_options_route(eid: int, access=Depends(viewer), db: Session = Depends(get_db)):
    """Predicted miss distance for a grid of hypothetical avoidance burns
    (½, 1 and 2 orbits before TCA; five directions; 0.05–0.5 m/s)."""
    p, _ = access
    e, j = _get_enc(db, p.id, eid)
    if j.kind != "screening":
        raise api_error(409, "NOT_SUPPORTED", "manoeuvre options need propagatable inputs; this encounter comes from a CDM (states at TCA only)")
    dv = db.get(DatasetVersion, j.dataset_version_id)
    key = (e.id, dv.snapshot_sha256, int(Time.now().unix // 600))
    if key not in _OPTIONS_CACHE:
        _, props, _ = _cached_propagators(dv)
        try:
            out = maneuver_options(props[e.primary_id], props[e.secondary_id], Time(e.tca_iso.rstrip("Z"), scale="utc"))
        except (KeyError, ValueError) as exc:
            raise api_error(422, "NOT_COMPUTABLE", str(exc)) from None
        if len(_OPTIONS_CACHE) > 200:
            _OPTIONS_CACHE.clear()
        _OPTIONS_CACHE[key] = out
    return {"encounter_id": e.id, "primary": e.primary_name or e.primary_id, "secondary": e.secondary_name or e.secondary_id,
            "screening_miss_km": e.miss_km, **_OPTIONS_CACHE[key]}


@router.get("/encounters/{eid}/scenarios")
def list_scenarios(eid: int, access=Depends(viewer), db: Session = Depends(get_db)):
    p, _ = access
    e, _ = _get_enc(db, p.id, eid)
    rows = db.scalars(select(Scenario).where(Scenario.encounter_id == e.id).order_by(Scenario.id))
    return {"items": [{"id": s.id, "name": s.name, "params": s.params, "result": s.result, "algorithm_version": s.algorithm_version,
                       "created_at": s.created_at} for s in rows]}


@router.delete("/scenarios/{sid}")
def delete_scenario(sid: int, access=Depends(analyst), user: User = Depends(current_user), db: Session = Depends(get_db)):
    p, _ = access
    sc = db.get(Scenario, sid)
    if sc is None or sc.project_id != p.id:
        raise api_error(404, "NOT_FOUND", "scenario not found")
    db.delete(sc)
    audit.record(db, "scenario.delete", user.id, p.id, f"scenario:{sid}")
    db.commit()
    return {"ok": True}


# -------------------------------------------------------------------- reports

FORMATS = {"pdf": ("application/pdf", ".pdf"), "csv": ("text/csv", ".csv"), "json": ("application/json", ".json")}


@router.post("/jobs/{jid}/reports", status_code=201)
def create_report(jid: int, fmt: str = "pdf", access=Depends(viewer), user: User = Depends(current_user), db: Session = Depends(get_db)):
    p, _ = access
    j = _get_job(db, p.id, jid)
    if j.status != "succeeded":
        raise api_error(409, "NOT_READY", "reports are available for succeeded jobs only")
    if fmt not in FORMATS:
        raise api_error(422, "INVALID_FORMAT", "fmt must be pdf, csv or json")
    data = {"pdf": reports.report_pdf, "csv": reports.encounters_csv, "json": reports.report_json}[fmt](db, j)
    key, sha = storage.put("reports", data, FORMATS[fmt][1])
    r = Report(project_id=p.id, job_id=j.id, format=fmt, storage_key=key, sha256=sha, generator_version=reports.REPORT_VERSION, created_by=user.id)
    db.add(r)
    db.flush()
    audit.record(db, "export.report", user.id, p.id, f"report:{r.id}", {"job": j.id, "format": fmt, "sha256": sha})
    db.commit()
    return {"id": r.id, "format": fmt, "sha256": sha, "job_id": j.id, "created_at": r.created_at}


@router.get("/reports")
def list_reports(access=Depends(viewer), db: Session = Depends(get_db)):
    p, _ = access
    rows = db.scalars(select(Report).where(Report.project_id == p.id).order_by(Report.id.desc()))
    return {"items": [{"id": r.id, "job_id": r.job_id, "format": r.format, "sha256": r.sha256, "generator_version": r.generator_version,
                       "created_at": r.created_at} for r in rows]}


@router.get("/reports/{rid}/download")
def download_report(rid: int, access=Depends(viewer), db: Session = Depends(get_db)):
    p, _ = access
    r = db.get(Report, rid)
    if r is None or r.project_id != p.id:
        raise api_error(404, "NOT_FOUND", "report not found")
    data = storage.get(r.storage_key)
    if storage.sha256(data) != r.sha256:
        raise api_error(500, "INTEGRITY", "stored report failed its integrity check")
    mt, ext = FORMATS[r.format]
    return Response(data, media_type=mt, headers={"Content-Disposition": f'attachment; filename="astral-job{r.job_id}-report{r.id}{ext}"'})


@router.get("/encounters/{eid}/export/cdm")
def export_cdm(eid: int, access=Depends(viewer), user: User = Depends(current_user), db: Session = Depends(get_db)):
    p, _ = access
    e, _ = _get_enc(db, p.id, eid)
    try:
        text = reports.export_cdm(db, e)
    except ValueError as exc:
        raise api_error(409, "NOT_EXPORTABLE", str(exc)) from None
    audit.record(db, "export.cdm", user.id, p.id, f"encounter:{eid}")
    db.commit()
    return Response(text, media_type="text/plain", headers={"Content-Disposition": f'attachment; filename="astral-encounter-{eid}.cdm"'})


@router.get("/dataset-versions/{vid}/export/oem")
def export_oem(vid: int, object_id: str, start: str, duration_s: float = 86400, step_s: float = 60, access=Depends(viewer),
               user: User = Depends(current_user), db: Session = Depends(get_db)):
    p, _ = access
    dv = db.get(DatasetVersion, vid)
    if dv is None or db.get(Dataset, dv.dataset_id).project_id != p.id:
        raise api_error(404, "NOT_FOUND", "dataset version not found")
    duration_s = float(min(max(duration_s, 60), 7 * 86400))
    step_s = float(min(max(step_s, 1), 3600))
    records, _ = load_snapshot(dv)
    try:
        text = reports.export_oem(records, object_id, parse_epoch(start.rstrip("Z"), "UTC"), duration_s, step_s)
    except (ValueError, TimeParseError) as exc:
        raise api_error(422, "NOT_EXPORTABLE", str(exc)) from None
    audit.record(db, "export.oem", user.id, p.id, f"dataset_version:{vid}", {"object": object_id})
    db.commit()
    return Response(text, media_type="text/plain", headers={"Content-Disposition": f'attachment; filename="{object_id}.oem"'})
