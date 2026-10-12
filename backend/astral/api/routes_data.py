"""Projects, datasets, uploads, validation review, catalogue, providers."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..db.models import (
    CovarianceRecord,
    Dataset,
    DatasetVersion,
    ObjectRecord,
    Project,
    ProjectMember,
    Transformation,
    UploadedFile,
    User,
    ValidationFinding,
)
from ..db.session import get_db
from ..services import audit, storage
from ..services.datasets import UploadRejected, apply_transformation, approve, create_version
from ..services.providers import ProviderError, celestrak_fetch, spacetrack_configured
from ..settings import get_settings
from .deps import analyst, api_error, current_user, owner, paginate, viewer

router = APIRouter(prefix="/api/v1", tags=["projects & data"])


class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field("", max_length=2000)


def _proj(p: Project, role: str) -> dict:
    return {"id": p.id, "name": p.name, "description": p.description, "is_demo": p.is_demo, "role": role, "created_at": p.created_at}


@router.get("/projects")
def list_projects(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.execute(select(Project, ProjectMember.role).join(ProjectMember).where(ProjectMember.user_id == user.id).order_by(Project.id)).all()
    return {"items": [_proj(p, r) for p, r in rows]}


@router.post("/projects", status_code=201)
def create_project(body: ProjectIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    p = Project(name=body.name, description=body.description, created_by=user.id)
    db.add(p)
    db.flush()
    db.add(ProjectMember(project_id=p.id, user_id=user.id, role="owner"))
    audit.record(db, "project.create", user.id, p.id, f"project:{p.id}")
    db.commit()
    return _proj(p, "owner")


@router.get("/projects/{pid}")
def get_project(access=Depends(viewer), db: Session = Depends(get_db)):
    p, role = access
    members = db.execute(select(ProjectMember, User).join(User, User.id == ProjectMember.user_id).where(ProjectMember.project_id == p.id)).all()
    return {**_proj(p, role), "members": [{"user_id": u.id, "email": u.email, "display_name": u.display_name, "role": m.role} for m, u in members]}


class MemberIn(BaseModel):
    email: str
    role: str = Field(pattern="^(owner|analyst|viewer)$")


@router.post("/projects/{pid}/members", status_code=201)
def add_member(body: MemberIn, access=Depends(owner), user: User = Depends(current_user), db: Session = Depends(get_db)):
    p, _ = access
    u = db.scalar(select(User).where(User.email == body.email.strip().lower()))
    if u is None:
        raise api_error(404, "NOT_FOUND", "no such user")
    m = db.scalar(select(ProjectMember).where(ProjectMember.project_id == p.id, ProjectMember.user_id == u.id))
    if m:
        m.role = body.role
    else:
        db.add(ProjectMember(project_id=p.id, user_id=u.id, role=body.role))
    audit.record(db, "project.member.set", user.id, p.id, f"user:{u.id}", {"role": body.role})
    db.commit()
    return {"ok": True}


# ------------------------------------------------------------------ datasets

def _dv(dv: DatasetVersion) -> dict:
    return {"id": dv.id, "version": dv.version, "status": dv.status, "format": dv.format, "stats": dv.stats, "provenance": dv.provenance,
            "snapshot_sha256": dv.snapshot_sha256, "reference_time": dv.reference_time, "created_at": dv.created_at,
            "approved_at": dv.approved_at}


@router.get("/projects/{pid}/datasets")
def list_datasets(access=Depends(viewer), db: Session = Depends(get_db)):
    p, _ = access
    out = []
    for ds in db.scalars(select(Dataset).where(Dataset.project_id == p.id).order_by(Dataset.id.desc())):
        out.append({"id": ds.id, "name": ds.name, "is_synthetic": ds.is_synthetic, "created_at": ds.created_at, "versions": [_dv(v) for v in ds.versions]})
    return {"items": out}


async def _read_limited(f: UploadFile) -> bytes:
    limit = get_settings().max_upload_mb * 1024 * 1024
    chunks, size = [], 0
    while True:
        c = await f.read(1024 * 1024)
        if not c:
            break
        size += len(c)
        if size > limit:
            raise api_error(413, "PAYLOAD_TOO_LARGE", f"file exceeds {get_settings().max_upload_mb} MB")
        chunks.append(c)
    return b"".join(chunks)


@router.post("/projects/{pid}/datasets", status_code=201)
async def upload_dataset(file: UploadFile = File(...), name: str | None = Form(None), dataset_id: int | None = Form(None),
                         fmt: str | None = Form(None), access=Depends(analyst), user: User = Depends(current_user), db: Session = Depends(get_db)):
    p, _ = access
    data = await _read_limited(file)
    try:
        dv = create_version(db, p.id, user.id, file.filename or "upload", data, dataset_id=dataset_id, dataset_name=name, fmt=fmt or None)
    except UploadRejected as exc:
        audit.record(db, "dataset.upload", user.id, p.id, details={"filename": (file.filename or "")[:100], "reason": str(exc)[:300]}, outcome="rejected")
        db.commit()
        raise api_error(422, "UPLOAD_REJECTED", str(exc)) from None
    return _dv(dv)


def _get_dv(db: Session, pid: int, vid: int) -> DatasetVersion:
    dv = db.get(DatasetVersion, vid)
    if dv is None or db.get(Dataset, dv.dataset_id).project_id != pid:
        raise api_error(404, "NOT_FOUND", "dataset version not found")
    return dv


@router.get("/projects/{pid}/dataset-versions/{vid}")
def get_version(vid: int, access=Depends(viewer), db: Session = Depends(get_db)):
    p, _ = access
    dv = _get_dv(db, p.id, vid)
    ds = db.get(Dataset, dv.dataset_id)
    uf = db.get(UploadedFile, dv.file_id)
    sev = dict(db.execute(select(ValidationFinding.severity, func.count()).where(ValidationFinding.dataset_version_id == vid)
                          .group_by(ValidationFinding.severity)).all())
    trs = db.scalars(select(Transformation).where(Transformation.dataset_version_id == vid))
    return {**_dv(dv), "dataset": {"id": ds.id, "name": ds.name, "is_synthetic": ds.is_synthetic},
            "file": {"name": uf.original_name, "sha256": uf.sha256, "size_bytes": uf.size_bytes, "origin": uf.origin, "uploaded_at": uf.uploaded_at},
            "finding_counts": sev,
            "transformations": [{"id": t.id, "kind": t.kind, "description": t.description, "status": t.status, "result_version_id": t.result_version_id}
                                for t in trs]}


@router.get("/projects/{pid}/dataset-versions/{vid}/findings")
def list_findings(vid: int, severity: str | None = None, limit: int = 100, offset: int = 0, access=Depends(viewer), db: Session = Depends(get_db)):
    p, _ = access
    _get_dv(db, p.id, vid)
    limit, offset = paginate(limit, offset)
    q = select(ValidationFinding).where(ValidationFinding.dataset_version_id == vid)
    if severity:
        q = q.where(ValidationFinding.severity == severity)
    total = db.scalar(select(func.count()).select_from(q.subquery()))
    rows = db.scalars(q.order_by(ValidationFinding.id).limit(limit).offset(offset))
    return {"total": total, "items": [{"id": f.id, "severity": f.severity, "code": f.code, "message": f.message, "record": f.record_ref,
                                       "suggestion": f.suggestion} for f in rows]}


@router.get("/projects/{pid}/dataset-versions/{vid}/validation-report.csv")
def validation_report(vid: int, access=Depends(viewer), db: Session = Depends(get_db)):
    import csv
    import io

    p, _ = access
    dv = _get_dv(db, p.id, vid)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["dataset_version", dv.id, "snapshot_sha256", dv.snapshot_sha256])
    w.writerow(["severity", "code", "record", "message", "suggestion"])
    for f in db.scalars(select(ValidationFinding).where(ValidationFinding.dataset_version_id == vid)):
        w.writerow([f.severity, f.code, f.record_ref or "", f.message, f.suggestion or ""])
    audit.record(db, "export.validation_report", None, p.id, f"dataset_version:{vid}")
    db.commit()
    return Response(buf.getvalue(), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="validation-{vid}.csv"'})


@router.post("/projects/{pid}/dataset-versions/{vid}/approve")
def approve_version(vid: int, access=Depends(analyst), user: User = Depends(current_user), db: Session = Depends(get_db)):
    p, _ = access
    dv = _get_dv(db, p.id, vid)
    if dv.status == "approved":
        return _dv(dv)
    return _dv(approve(db, dv, user.id, p.id))


@router.post("/projects/{pid}/transformations/{tid}/approve")
def approve_transformation(tid: int, access=Depends(analyst), user: User = Depends(current_user), db: Session = Depends(get_db)):
    p, _ = access
    tr = db.get(Transformation, tid)
    if tr is None:
        raise api_error(404, "NOT_FOUND", "transformation not found")
    _get_dv(db, p.id, tr.dataset_version_id)
    if tr.status != "proposed":
        raise api_error(409, "CONFLICT", f"transformation already {tr.status}")
    return _dv(apply_transformation(db, tr, user.id, p.id))


@router.post("/projects/{pid}/transformations/{tid}/reject")
def reject_transformation(tid: int, access=Depends(analyst), user: User = Depends(current_user), db: Session = Depends(get_db)):
    p, _ = access
    tr = db.get(Transformation, tid)
    if tr is None:
        raise api_error(404, "NOT_FOUND", "transformation not found")
    _get_dv(db, p.id, tr.dataset_version_id)
    tr.status = "rejected"
    tr.decided_by = user.id
    audit.record(db, "dataset.transformation.reject", user.id, p.id, f"transformation:{tid}")
    db.commit()
    return {"ok": True}


@router.get("/projects/{pid}/dataset-versions/{vid}/raw")
def download_raw(vid: int, access=Depends(viewer), db: Session = Depends(get_db)):
    p, _ = access
    dv = _get_dv(db, p.id, vid)
    uf = db.get(UploadedFile, dv.file_id)
    data = storage.get(uf.storage_key)
    return Response(data, media_type="application/octet-stream", headers={"Content-Disposition": f'attachment; filename="dataset-{vid}-original.txt"'})


@router.get("/projects/{pid}/catalogue")
def catalogue(vid: int, q: str | None = None, kind: str | None = None, limit: int = 100, offset: int = 0, sort: str = "object_id",
              access=Depends(viewer), db: Session = Depends(get_db)):
    p, _ = access
    _get_dv(db, p.id, vid)
    limit, offset = paginate(limit, offset)
    stmt = select(ObjectRecord).where(ObjectRecord.dataset_version_id == vid)
    if q:
        like = f"%{q[:50]}%"
        stmt = stmt.where(or_(ObjectRecord.object_id.ilike(like), ObjectRecord.object_name.ilike(like)))
    if kind:
        stmt = stmt.where(ObjectRecord.kind == kind)
    col = {"object_id": ObjectRecord.object_id, "epoch": ObjectRecord.epoch, "perigee": ObjectRecord.perigee_alt_km,
           "inclination": ObjectRecord.inclination_deg}.get(sort, ObjectRecord.object_id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(col).limit(limit).offset(offset))
    return {"total": total, "items": [{"object_id": r.object_id, "object_name": r.object_name, "kind": r.kind, "format": r.source_format,
                                       "epoch": r.epoch, "frame": r.frame, "has_covariance": r.has_covariance, "perigee_alt_km": r.perigee_alt_km,
                                       "apogee_alt_km": r.apogee_alt_km, "inclination_deg": r.inclination_deg, "period_min": r.period_min,
                                       "usable": r.usable, "source_ref": r.source_ref} for r in rows]}


@router.get("/projects/{pid}/dataset-versions/{vid}/covariances")
def covariances(vid: int, access=Depends(viewer), db: Session = Depends(get_db)):
    p, _ = access
    _get_dv(db, p.id, vid)
    rows = db.scalars(select(CovarianceRecord).where(CovarianceRecord.dataset_version_id == vid))
    return {"items": [{"id": c.id, "object_id": c.object_id, "epoch": c.epoch_iso, "frame": c.frame, "matrix_km": c.matrix_km, "valid": c.valid,
                       "eigenvalues": c.eigenvalues, "source": c.source} for c in rows]}


class ProviderIn(BaseModel):
    provider: str = Field(pattern="^(celestrak)$")
    group: str | None = Field(None, max_length=40)
    catnr: int | None = None
    dataset_id: int | None = None


@router.post("/projects/{pid}/provider-fetch", status_code=201)
def provider_fetch(body: ProviderIn, access=Depends(analyst), user: User = Depends(current_user), db: Session = Depends(get_db)):
    p, _ = access
    try:
        data, prov = celestrak_fetch(db, body.group, body.catnr, "tle")
    except ProviderError as exc:
        raise api_error(502, "PROVIDER_ERROR", str(exc)) from None
    try:
        dv = create_version(db, p.id, user.id, f"celestrak-{body.group or body.catnr}.tle", data, dataset_id=body.dataset_id,
                            dataset_name=f"CelesTrak {body.group or body.catnr}", origin="provider", provenance=prov)
    except UploadRejected as exc:
        raise api_error(422, "UPLOAD_REJECTED", str(exc)) from None
    return _dv(dv)


@router.get("/providers")
def providers(_: User = Depends(current_user)):
    s = get_settings()
    return {"items": [
        {"id": "celestrak", "name": "CelesTrak GP", "enabled": s.celestrak_enabled, "auth": "none",
         "note": "public GP elements; not operationally authoritative", "verified": True},
        {"id": "spacetrack", "name": "Space-Track", "enabled": spacetrack_configured(), "auth": "credentials via environment",
         "note": "integration implemented per documentation but not exercised against the live service", "verified": False},
    ]}
