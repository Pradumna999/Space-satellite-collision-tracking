"""ASTRAL documented CSV and JSON state-vector schemas (``astral-states/1``).

CSV columns (header row required, order free):
    object_id, epoch, time_system, frame, x_km, y_km, z_km, vx_km_s, vy_km_s, vz_km_s
optional:
    object_name, hard_body_radius_m

JSON:
    {"schema": "astral-states/1",
     "objects": [{"object_id": "...", "object_name": "...", "epoch": "...",
                  "time_system": "UTC", "frame": "GCRF",
                  "position_km": [x,y,z], "velocity_km_s": [vx,vy,vz],
                  "hard_body_radius_m": 5.0,
                  "covariance": {"frame": "RTN", "units": "km",
                                 "matrix": [[...6x6...]]}}]}

Unit columns are fixed (km, km/s). Files using other units are rejected
rather than converted, because the unit cannot be inferred safely.
"""

from __future__ import annotations

import csv
import io
import math
from typing import Any

import numpy as np

from ..covariance import validate
from ..findings import Finding, Severity
from ..frames import FrameError, parse_frame
from ..records import Covariance, OrbitalRecord, RecordKind
from ..timeutil import TimeParseError, parse_epoch

CSV_REQUIRED = ("object_id", "epoch", "time_system", "frame", "x_km", "y_km", "z_km", "vx_km_s", "vy_km_s", "vz_km_s")
SCHEMA_ID = "astral-states/1"


def _state_record(d: dict[str, Any], ref: str, fmt: str, findings: list[Finding]) -> OrbitalRecord | None:
    oid = str(d.get("object_id") or "").strip()
    if not oid:
        findings.append(Finding(Severity.ERROR, "STATE_ID_MISSING", f"{ref}: object_id required", ref))
        return None
    try:
        frame = parse_frame(str(d.get("frame", "")))
    except FrameError as exc:
        findings.append(Finding(Severity.ERROR, "STATE_FRAME", f"{ref}: {exc}", oid))
        return None
    tsys = str(d.get("time_system", "")).upper()
    try:
        epoch = parse_epoch(str(d.get("epoch", "")), tsys or "UTC")
    except TimeParseError as exc:
        findings.append(Finding(Severity.ERROR, "STATE_EPOCH", f"{ref}: {exc}", oid))
        return None
    if not tsys:
        findings.append(Finding(Severity.ERROR, "STATE_TIME_SYSTEM", f"{ref}: time_system must be declared", oid))
        return None
    try:
        r = np.array([float(x) for x in d["position_km"]], dtype=float)
        v = np.array([float(x) for x in d["velocity_km_s"]], dtype=float)
    except (KeyError, TypeError, ValueError):
        findings.append(Finding(Severity.ERROR, "STATE_VECTOR", f"{ref}: position_km/velocity_km_s must be 3 numbers each", oid))
        return None
    if r.shape != (3,) or v.shape != (3,) or not (np.all(np.isfinite(r)) and np.all(np.isfinite(v))):
        findings.append(Finding(Severity.ERROR, "STATE_VECTOR", f"{ref}: state must be 3+3 finite numbers", oid))
        return None
    rn, vn = float(np.linalg.norm(r)), float(np.linalg.norm(v))
    if rn < 6378.137 * 0.99:
        findings.append(Finding(Severity.WARNING, "STATE_BELOW_SURFACE", f"{ref}: |r| = {rn:.1f} km is below the Earth's surface", oid))
    if rn > 2e6:
        findings.append(Finding(Severity.WARNING, "STATE_RADIUS_UNITS", f"{ref}: |r| = {rn:.3g} km; are units metres?", oid,
                                suggestion="If the file is in metres, divide by 1000 and re-upload; ASTRAL will not rescale automatically."))
    if vn > 12.0 and rn < 50000:
        findings.append(Finding(Severity.WARNING, "STATE_SPEED", f"{ref}: |v| = {vn:.2f} km/s exceeds Earth escape speed at this radius", oid))
    hbr = d.get("hard_body_radius_m")
    hbr_f = None
    if hbr not in (None, ""):
        try:
            hbr_f = float(hbr)
            if not (math.isfinite(hbr_f) and hbr_f > 0):
                raise ValueError
        except (TypeError, ValueError):
            findings.append(Finding(Severity.ERROR, "STATE_HBR", f"{ref}: hard_body_radius_m must be a positive number", oid))
            return None
    cov = None
    rejected = None
    if d.get("covariance"):
        c = d["covariance"]
        try:
            m = np.asarray(c["matrix"], dtype=float)
            if str(c.get("units", "km")).lower() != "km":
                raise ValueError("covariance units must be 'km' (km, km/s based)")
            cframe = str(c.get("frame", "RTN")).upper()
            cframe = "RTN" if cframe == "RTN" else parse_frame(cframe).value
            chk = validate(m, oid)
            findings.extend(chk.findings)
            if chk.valid:
                cov = Covariance(m, cframe, epoch, f"{fmt} {ref}")
            else:
                rejected = {"matrix_km": m.tolist(), "frame": cframe, "epoch": epoch.utc.isot, "source": f"{fmt} {ref}"}
        except (KeyError, TypeError, ValueError, FrameError) as exc:
            findings.append(Finding(Severity.ERROR, "STATE_COVARIANCE", f"{ref}: invalid covariance: {exc}", oid))
    return OrbitalRecord(
        object_id=oid,
        object_name=(str(d["object_name"]).strip() or None) if d.get("object_name") else None,
        kind=RecordKind.STATE,
        source_format=fmt,
        epoch=epoch,
        frame=frame,
        time_system=tsys,
        position_km=r,
        velocity_km_s=v,
        covariance=cov,
        hard_body_radius_m=hbr_f,
        source_ref=ref,
        extra={"rejected_covariance": rejected} if rejected else {},
    )


def parse_states_csv(text: str) -> tuple[list[OrbitalRecord], list[Finding]]:
    findings: list[Finding] = []
    records: list[OrbitalRecord] = []
    reader = csv.DictReader(io.StringIO(text))
    cols = [c.strip().lower() for c in (reader.fieldnames or [])]
    missing = [c for c in CSV_REQUIRED if c not in cols]
    if missing:
        return [], [Finding(Severity.ERROR, "CSV_SCHEMA", f"missing required columns: {', '.join(missing)}")]
    for i, row in enumerate(reader, 2):
        row = {k.strip().lower(): (v or "").strip() for k, v in row.items() if k}
        d = dict(row)
        d["position_km"] = [row.get("x_km"), row.get("y_km"), row.get("z_km")]
        d["velocity_km_s"] = [row.get("vx_km_s"), row.get("vy_km_s"), row.get("vz_km_s")]
        rec = _state_record(d, f"row {i}", "STATES_CSV", findings)
        if rec:
            records.append(rec)
    return records, findings


def parse_states_json(doc: dict[str, Any]) -> tuple[list[OrbitalRecord], list[Finding]]:
    findings: list[Finding] = []
    if doc.get("schema") != SCHEMA_ID:
        return [], [Finding(Severity.ERROR, "JSON_SCHEMA", f"schema must be {SCHEMA_ID!r}")]
    objs = doc.get("objects")
    if not isinstance(objs, list):
        return [], [Finding(Severity.ERROR, "JSON_SCHEMA", "'objects' must be a list")]
    records = []
    for i, o in enumerate(objs):
        if not isinstance(o, dict):
            findings.append(Finding(Severity.ERROR, "JSON_ITEM", f"objects[{i}] is not an object", f"objects[{i}]"))
            continue
        rec = _state_record(o, f"objects[{i}]", "STATES_JSON", findings)
        if rec:
            records.append(rec)
    return records, findings
