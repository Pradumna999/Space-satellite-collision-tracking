"""Upload -> validation -> immutable dataset version."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import numpy as np
from astropy.time import Time
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core.covariance import nearest_psd, validate
from ..core.findings import Severity
from ..core.parsers import FormatError, ingest
from ..core.records import Covariance, OrbitalRecord, RecordKind
from ..core.timeutil import from_datetime
from ..db.models import CovarianceRecord, Dataset, DatasetVersion, ObjectRecord, Transformation, UploadedFile, ValidationFinding
from ..settings import get_settings
from . import audit, storage


class UploadRejected(ValueError):
    pass


def _decode(data: bytes) -> str:
    if b"\x00" in data[:8192]:
        raise UploadRejected("binary content is not accepted")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            return data.decode("ascii")
        except UnicodeDecodeError as exc:
            raise UploadRejected("file must be UTF-8 or ASCII text") from exc


def snapshot_bytes(records: list[OrbitalRecord], findings: list[dict], meta: dict) -> bytes:
    doc = {"schema": "astral-snapshot/1", "meta": meta, "records": [r.to_dict() for r in records], "findings": findings}
    return json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()


def load_snapshot(dv: DatasetVersion) -> tuple[list[OrbitalRecord], dict]:
    raw = storage.get(dv.snapshot_key)
    if storage.sha256(raw) != dv.snapshot_sha256:
        raise RuntimeError(f"dataset version {dv.id} snapshot hash mismatch — refusing to use altered input")
    doc = json.loads(raw)
    return [OrbitalRecord.from_dict(r) for r in doc["records"]], doc


def _status(findings) -> str:
    if any(f.severity is Severity.ERROR for f in findings):
        return "needs_review"
    return "validated"


def _index(db: Session, dv: DatasetVersion, records: list[OrbitalRecord]) -> None:
    for r in records:
        me = r.mean_elements or {}
        db.add(ObjectRecord(
            dataset_version_id=dv.id, object_id=r.object_id, object_name=r.object_name, kind=r.kind.value,
            source_format=r.source_format, epoch=r.epoch.utc.to_datetime(timezone=UTC), frame=r.frame.value,
            has_covariance=r.covariance is not None, perigee_alt_km=me.get("perigee_alt_km"), apogee_alt_km=me.get("apogee_alt_km"),
            inclination_deg=me.get("inclination_deg"), period_min=me.get("period_min"), source_ref=r.source_ref,
            usable=not (r.extra.get("duplicate_of") or r.extra.get("conflict_with")),
        ))
        if r.covariance is not None:
            chk = validate(r.covariance.matrix)
            db.add(CovarianceRecord(dataset_version_id=dv.id, object_id=r.object_id, epoch_iso=r.covariance.epoch.utc.isot,
                                    frame=r.covariance.frame, matrix_km=r.covariance.matrix.tolist(), valid=chk.valid,
                                    eigenvalues=chk.eigenvalues, source=r.covariance.source))


def _propose(db: Session, dv: DatasetVersion, records: list[OrbitalRecord], findings) -> None:
    dup = [r.source_ref for r in records if r.extra.get("duplicate_of")]
    if dup:
        db.add(Transformation(dataset_version_id=dv.id, kind="exclude_records",
                              description=f"Exclude {len(dup)} exact duplicate record(s); the first occurrence is kept.",
                              params={"source_refs": dup}))
    conflicts = [r for r in records if r.extra.get("conflict_with")]
    for r in conflicts:
        db.add(Transformation(dataset_version_id=dv.id, kind="exclude_records",
                              description=f"Exclude conflicting record {r.source_ref} for {r.object_id} (keeps {r.extra['conflict_with']}).",
                              params={"source_refs": [r.source_ref]}))
    for r in records:
        rej = r.extra.get("rejected_covariance")
        if rej:
            db.add(Transformation(dataset_version_id=dv.id, kind="nearest_psd_covariance",
                                  description=f"Replace {r.object_id}'s non-PSD covariance with its nearest PSD matrix (eigenvalue clipping). This changes Pc inputs.",
                                  params={"source_ref": r.source_ref}))


def create_version(db: Session, project_id: int, user_id: int, filename: str, data: bytes, dataset_id: int | None = None,
                   dataset_name: str | None = None, origin: str = "upload", is_synthetic: bool = False,
                   provenance: dict | None = None, fmt: str | None = None) -> DatasetVersion:
    s = get_settings()
    if len(data) > s.max_upload_mb * 1024 * 1024:
        raise UploadRejected(f"file exceeds {s.max_upload_mb} MB limit")
    if not data.strip():
        raise UploadRejected("empty file")
    text = _decode(data)
    ref_time = Time.now()
    try:
        res = ingest(text, filename, ref_time, fmt)
    except FormatError as exc:
        raise UploadRejected(str(exc)) from exc
    if not res.records:
        codes = sorted({f.code for f in res.findings})[:8]
        raise UploadRejected(f"no usable records ({', '.join(codes) or 'no data'})")
    raw_key, raw_sha = storage.put("uploads", data)
    safe_name = "".join(c for c in filename if c.isalnum() or c in "._- ")[:200] or "upload"
    uf = UploadedFile(project_id=project_id, original_name=safe_name, storage_key=raw_key, sha256=raw_sha, size_bytes=len(data),
                      detected_format=res.format, uploaded_by=user_id, origin=origin,
                      retain_until=datetime.now(UTC) + timedelta(days=s.retention_days_uploads))
    db.add(uf)
    db.flush()
    if dataset_id is None:
        ds = Dataset(project_id=project_id, name=(dataset_name or safe_name)[:200], is_synthetic=is_synthetic)
        db.add(ds)
        db.flush()
    else:
        ds = db.get(Dataset, dataset_id)
        if ds is None or ds.project_id != project_id:
            raise UploadRejected("dataset not found in this project")
    ver = (db.scalar(select(func.max(DatasetVersion.version)).where(DatasetVersion.dataset_id == ds.id)) or 0) + 1
    fdicts = [f.to_dict() for f in res.findings]
    meta = {"format": res.format, "file_sha256": raw_sha, "reference_time": ref_time.utc.isot, "synthetic": is_synthetic,
            "origin": origin, "provenance": provenance or {}, "stats": res.stats}
    snap = snapshot_bytes(res.records, fdicts, meta)
    snap_key, snap_sha = storage.put("snapshots", snap, ".json")
    dv = DatasetVersion(dataset_id=ds.id, version=ver, file_id=uf.id, status=_status(res.findings), format=res.format,
                        snapshot_key=snap_key, snapshot_sha256=snap_sha, reference_time=ref_time.utc.to_datetime(timezone=UTC),
                        stats=res.stats, provenance={"origin": origin, "file_sha256": raw_sha, "filename": safe_name, **(provenance or {})})
    db.add(dv)
    db.flush()
    for f in res.findings:
        db.add(ValidationFinding(dataset_version_id=dv.id, severity=f.severity.value, code=f.code, message=f.message[:2000],
                                 record_ref=f.record, suggestion=f.suggestion))
    _index(db, dv, res.records)
    _propose(db, dv, res.records, res.findings)
    audit.record(db, "dataset.upload", user_id, project_id, f"dataset_version:{dv.id}",
                 {"file_sha256": raw_sha, "format": res.format, "records": len(res.records), "status": dv.status})
    db.commit()
    return dv


def approve(db: Session, dv: DatasetVersion, user_id: int, project_id: int) -> DatasetVersion:
    """Analyst accepts a version with findings for analysis (records with errors are already excluded)."""
    dv.status = "approved"
    dv.approved_by = user_id
    dv.approved_at = datetime.now(UTC)
    audit.record(db, "dataset.approve", user_id, project_id, f"dataset_version:{dv.id}")
    db.commit()
    return dv


def apply_transformation(db: Session, tr: Transformation, user_id: int, project_id: int) -> DatasetVersion:
    """Approve a proposed transformation: creates a NEW dataset version; the
    original is never modified."""
    src = db.get(DatasetVersion, tr.dataset_version_id)
    records, doc = load_snapshot(src)
    applied = f"{tr.kind} (transformation {tr.id}, approved by user {user_id})"
    if tr.kind == "exclude_records":
        drop = set(tr.params.get("source_refs", []))
        records = [r for r in records if r.source_ref not in drop]
        for r in records:
            if r.extra.get("conflict_with") in drop:
                r.extra.pop("conflict_with", None)
    elif tr.kind == "nearest_psd_covariance":
        for r in records:
            if r.source_ref == tr.params.get("source_ref") and r.extra.get("rejected_covariance"):
                rc = r.extra.pop("rejected_covariance")
                m = nearest_psd(np.asarray(rc["matrix_km"]))
                r.covariance = Covariance(m, rc["frame"], Time(rc["epoch"], scale="utc"), rc["source"] + " [nearest-PSD]")
                r.transformations.append("covariance replaced by nearest PSD matrix (eigenvalue clipping), explicitly approved")
    else:
        raise ValueError(f"unknown transformation {tr.kind}")
    for r in records:
        r.transformations.append(applied)
    meta = dict(doc["meta"])
    meta["derived_from_version"] = src.id
    meta["transformation"] = {"id": tr.id, "kind": tr.kind, "params": tr.params}
    snap = snapshot_bytes(records, doc["findings"], meta)
    key, sha = storage.put("snapshots", snap, ".json")
    ver = (db.scalar(select(func.max(DatasetVersion.version)).where(DatasetVersion.dataset_id == src.dataset_id)) or 0) + 1
    dv = DatasetVersion(dataset_id=src.dataset_id, version=ver, file_id=src.file_id, status="approved", format=src.format,
                        snapshot_key=key, snapshot_sha256=sha, reference_time=src.reference_time,
                        stats={**src.stats, "records": len(records)}, provenance={**src.provenance, "derived_from_version": src.id,
                                                                                   "transformation_id": tr.id},
                        approved_by=user_id, approved_at=datetime.now(UTC))
    db.add(dv)
    db.flush()
    _index(db, dv, records)
    tr.status = "approved"
    tr.decided_by = user_id
    tr.decided_at = datetime.now(UTC)
    tr.result_version_id = dv.id
    audit.record(db, "dataset.transformation.approve", user_id, project_id, f"transformation:{tr.id}", {"new_version": dv.id})
    db.commit()
    return dv


def records_at(records: list[OrbitalRecord], kind: RecordKind) -> list[OrbitalRecord]:
    return [r for r in records if r.kind is kind]


def age_days(epoch_dt: datetime, at: Time) -> float:
    return float((at - from_datetime(epoch_dt)).jd)
