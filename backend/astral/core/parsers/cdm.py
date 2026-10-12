"""CCSDS Conjunction Data Message (CDM) KVN parser.

Reference: CCSDS 508.0-B-1 (see DATA_FORMATS.md for edition notes).
Each CDM yields two STATE records (OBJECT1, OBJECT2) at TCA with their 6x6
RTN covariances, converted from the CDM's m / m/s units to km / km/s (factor
1e-6 for every covariance element; recorded as a transformation).

The originator's MISS_DISTANCE and COLLISION_PROBABILITY are kept for
comparison only; ASTRAL never re-labels them as its own results.
"""

from __future__ import annotations

import numpy as np

from ..covariance import lower_triangle_to_matrix, validate
from ..findings import Finding, Severity
from ..frames import FrameError, parse_frame
from ..records import Covariance, OrbitalRecord, RecordKind
from ..timeutil import TimeParseError, parse_epoch

COV_KEYS = (
    "CR_R",
    "CT_R", "CT_T",
    "CN_R", "CN_T", "CN_N",
    "CRDOT_R", "CRDOT_T", "CRDOT_N", "CRDOT_RDOT",
    "CTDOT_R", "CTDOT_T", "CTDOT_N", "CTDOT_RDOT", "CTDOT_TDOT",
    "CNDOT_R", "CNDOT_T", "CNDOT_N", "CNDOT_RDOT", "CNDOT_TDOT", "CNDOT_NDOT",
)
STATE_KEYS = ("X", "Y", "Z", "X_DOT", "Y_DOT", "Z_DOT")


def _value(v: str) -> str:
    return v.split("[", 1)[0].strip()


def parse_cdm_kvn(text: str) -> tuple[list[OrbitalRecord], list[Finding]]:
    findings: list[Finding] = []
    top: dict[str, str] = {}
    objs: list[dict[str, str]] = []
    cur = top
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("COMMENT"):
            continue
        if "=" not in line:
            findings.append(Finding(Severity.WARNING, "CDM_SYNTAX", f"line {n} ignored: not KEY = VALUE", f"line {n}"))
            continue
        k, v = line.split("=", 1)
        k, v = k.strip().upper(), _value(v)
        if k == "OBJECT":
            cur = {"OBJECT": v.upper()}
            objs.append(cur)
            continue
        cur[k] = v
    msg_id = top.get("MESSAGE_ID", "?")
    if "CCSDS_CDM_VERS" not in top:
        findings.append(Finding(Severity.WARNING, "CDM_HEADER_VERSION", "CCSDS_CDM_VERS missing", msg_id))
    if "TCA" not in top:
        findings.append(Finding(Severity.ERROR, "CDM_TCA_MISSING", "TCA is required", msg_id))
        return [], findings
    if len(objs) != 2 or {o["OBJECT"] for o in objs} != {"OBJECT1", "OBJECT2"}:
        findings.append(Finding(Severity.ERROR, "CDM_OBJECTS", "a CDM must contain exactly OBJECT1 and OBJECT2 sections", msg_id))
        return [], findings
    try:
        tca = parse_epoch(top["TCA"], "UTC")  # CDM TCA is UTC by definition (508.0-B-1 §3.5)
    except TimeParseError as exc:
        findings.append(Finding(Severity.ERROR, "CDM_TCA", str(exc), msg_id))
        return [], findings

    summary = {
        "message_id": msg_id,
        "originator": top.get("ORIGINATOR"),
        "creation_date": top.get("CREATION_DATE"),
        "cdm_version": top.get("CCSDS_CDM_VERS"),
        "tca": top["TCA"],
        "originator_miss_distance_m": _float_or_none(top.get("MISS_DISTANCE")),
        "originator_relative_speed_m_s": _float_or_none(top.get("RELATIVE_SPEED")),
        "originator_pc": _float_or_none(top.get("COLLISION_PROBABILITY")),
        "originator_pc_method": top.get("COLLISION_PROBABILITY_METHOD"),
    }
    records: list[OrbitalRecord] = []
    for o in sorted(objs, key=lambda x: x["OBJECT"]):
        role = o["OBJECT"]
        oid = o.get("OBJECT_DESIGNATOR") or role
        missing = [k for k in STATE_KEYS if k not in o]
        if missing:
            findings.append(Finding(Severity.ERROR, "CDM_STATE_MISSING", f"{role}: missing {', '.join(missing)}", oid))
            continue
        try:
            frame = parse_frame(o.get("REF_FRAME", ""))
        except FrameError as exc:
            findings.append(Finding(Severity.ERROR, "CDM_FRAME", f"{role}: {exc}", oid))
            continue
        try:
            sv = np.array([float(o[k]) for k in STATE_KEYS])
        except ValueError:
            findings.append(Finding(Severity.ERROR, "CDM_STATE_NUMERIC", f"{role}: non-numeric state", oid))
            continue
        cov = None
        rejected = None
        transformations = []
        if all(k in o for k in COV_KEYS):
            try:
                m = lower_triangle_to_matrix([float(o[k]) for k in COV_KEYS], 6) * 1e-6
                transformations.append("covariance m^2-based units -> km^2-based units (x1e-6)")
                chk = validate(m, oid)
                findings.extend(chk.findings)
                if chk.valid:
                    cov = Covariance(m, "RTN", tca, f"CDM {msg_id} {role}")
                else:
                    rejected = {"matrix_km": m.tolist(), "frame": "RTN", "epoch": tca.utc.isot, "source": f"CDM {msg_id} {role}"}
            except ValueError as exc:
                findings.append(Finding(Severity.ERROR, "CDM_COV_NUMERIC", f"{role}: {exc}", oid))
        else:
            present = [k for k in COV_KEYS if k in o]
            sev = Severity.WARNING if not present else Severity.ERROR
            findings.append(Finding(sev, "CDM_COV_INCOMPLETE", f"{role}: 6x6 RTN covariance {'absent' if not present else 'incomplete'}; Pc cannot be computed", oid))
        rec = OrbitalRecord(
            object_id=oid,
            object_name=o.get("OBJECT_NAME"),
            kind=RecordKind.STATE,
            source_format="CDM_KVN",
            epoch=tca,
            frame=frame,
            time_system="UTC",
            position_km=sv[:3],
            velocity_km_s=sv[3:],
            covariance=cov,
            source_ref=f"CDM {msg_id} {role}",
            transformations=transformations,
            extra={
                "cdm": summary,
                "cdm_role": role,
                "catalog_name": o.get("CATALOG_NAME"),
                "international_designator": o.get("INTERNATIONAL_DESIGNATOR"),
                "maneuverable": o.get("MANEUVERABLE"),
                "covariance_method": o.get("COVARIANCE_METHOD"),
                "area_pc_m2": _float_or_none(o.get("AREA_PC")),
                "time_lastob_end": o.get("TIME_LASTOB_END"),
                **({"rejected_covariance": rejected} if rejected else {}),
            },
        )
        records.append(rec)
    return records, findings


def _float_or_none(v: str | None) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except ValueError:
        return None
