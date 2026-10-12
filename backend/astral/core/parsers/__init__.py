"""Format detection and dataset-level validation."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from astropy.time import Time

from ..findings import Finding, Severity
from ..frames import Frame, eop_covered
from ..records import OrbitalRecord, RecordKind
from ..timeutil import beyond_leap_second_validity, data_age_days
from .cdm import parse_cdm_kvn
from .oem import parse_oem_kvn
from .omm import parse_omm_csv, parse_omm_json, parse_omm_kvn, parse_omm_xml
from .tabular import parse_states_csv, parse_states_json
from .tle import parse_tle_text

FORMATS = ("TLE", "OMM_KVN", "OMM_XML", "OMM_JSON", "OMM_CSV", "OEM_KVN", "CDM_KVN", "STATES_CSV", "STATES_JSON")

# GP element sets older than this (relative to the dataset reference time)
# are flagged stale. Public TLE accuracy degrades by kilometres per day.
STALE_GP_DAYS = 3.0
STALE_STATE_DAYS = 7.0


class FormatError(ValueError):
    pass


@dataclass
class IngestResult:
    format: str
    records: list[OrbitalRecord]
    findings: list[Finding]
    stats: dict[str, Any] = field(default_factory=dict)


def detect_format(text: str, filename: str = "") -> str:
    head = text.lstrip()[:4096]
    upper = head.upper()
    if "CCSDS_OMM_VERS" in upper:
        return "OMM_KVN"
    if "CCSDS_OEM_VERS" in upper or "META_START" in upper:
        return "OEM_KVN"
    if "CCSDS_CDM_VERS" in upper:
        return "CDM_KVN"
    if head.startswith("<"):
        if "<OMM" in upper or "<NDM" in upper:
            return "OMM_XML"
        raise FormatError("XML document is not an OMM/NDM")
    if head.startswith("[") or head.startswith("{"):
        try:
            doc = json.loads(text)
        except json.JSONDecodeError as exc:
            raise FormatError(f"invalid JSON: {exc.msg} at line {exc.lineno}") from exc
        if isinstance(doc, dict) and doc.get("schema", "").startswith("astral-states"):
            return "STATES_JSON"
        if isinstance(doc, list) and doc and isinstance(doc[0], dict) and "MEAN_MOTION" in doc[0]:
            return "OMM_JSON"
        raise FormatError("JSON is neither astral-states/1 nor an OMM JSON array")
    first = head.splitlines()[0] if head else ""
    if "," in first:
        cols = {c.strip().lower() for c in first.split(",")}
        if "mean_motion" in cols:
            return "OMM_CSV"
        if "x_km" in cols:
            return "STATES_CSV"
        raise FormatError("CSV header matches neither OMM CSV nor astral-states CSV")
    for ln in head.splitlines():
        if ln.startswith("1 ") and len(ln.rstrip()) >= 60:
            return "TLE"
    raise FormatError("unrecognised format")


def parse(text: str, fmt: str) -> tuple[list[OrbitalRecord], list[Finding]]:
    if fmt == "TLE":
        return parse_tle_text(text)
    if fmt == "OMM_KVN":
        return parse_omm_kvn(text)
    if fmt == "OMM_XML":
        return parse_omm_xml(text)
    if fmt == "OMM_JSON":
        return parse_omm_json(json.loads(text))
    if fmt == "OMM_CSV":
        return parse_omm_csv(text)
    if fmt == "OEM_KVN":
        return parse_oem_kvn(text)
    if fmt == "CDM_KVN":
        return parse_cdm_kvn(text)
    if fmt == "STATES_CSV":
        return parse_states_csv(text)
    if fmt == "STATES_JSON":
        return parse_states_json(json.loads(text))
    raise FormatError(f"unsupported format {fmt}")


def dataset_checks(records: list[OrbitalRecord], reference_time: Time) -> list[Finding]:
    """Cross-record checks: duplicates, conflicts, staleness, epoch spread."""
    out: list[Finding] = []
    seen: dict[tuple[str, str], OrbitalRecord] = {}
    for r in records:
        k = r.key()
        if k in seen:
            prev = seen[k]
            same = prev.to_dict() | {"source_ref": None} == r.to_dict() | {"source_ref": None}
            if same:
                out.append(Finding(Severity.WARNING, "DUPLICATE_RECORD", f"identical record for {r.object_id} at {k[1]} ({prev.source_ref} and {r.source_ref})", r.object_id,
                                   suggestion="Remove the duplicate; only the first occurrence is used."))
                r.extra["duplicate_of"] = prev.source_ref
            else:
                out.append(Finding(Severity.ERROR, "CONFLICTING_RECORD", f"different data for {r.object_id} at the same epoch {k[1]} ({prev.source_ref} vs {r.source_ref})", r.object_id))
                r.extra["conflict_with"] = prev.source_ref
        else:
            seen[k] = r
    by_obj: dict[str, list[OrbitalRecord]] = {}
    for r in records:
        by_obj.setdefault(r.object_id, []).append(r)
    for oid, rs in by_obj.items():
        gp = [r for r in rs if r.kind is RecordKind.GP_ELEMENTS]
        if len(gp) > 1:
            out.append(Finding(Severity.INFO, "MULTIPLE_ELEMENT_SETS", f"{oid} has {len(gp)} element sets; the most recent epoch is used for propagation", oid))
    for r in records:
        age = data_age_days(r.epoch, reference_time)
        limit = STALE_GP_DAYS if r.kind is RecordKind.GP_ELEMENTS else STALE_STATE_DAYS
        if age > limit:
            out.append(Finding(Severity.WARNING, "STALE_DATA", f"{r.object_id} epoch is {age:.1f} days before the reference time (limit {limit} d)", r.object_id))
        if age < -1.0 and r.kind is not RecordKind.EPHEMERIS:
            out.append(Finding(Severity.WARNING, "FUTURE_EPOCH", f"{r.object_id} epoch is {-age:.1f} days after the reference time", r.object_id))
        if r.frame is Frame.ITRF and not eop_covered(r.epoch):
            out.append(Finding(Severity.WARNING, "EOP_UNAVAILABLE", f"{r.object_id}: ITRF data at an epoch beyond the bundled IERS EOP table; "
                               "conversion to inertial frames assumes UT1-UTC = 0 (up to ~0.5 km error in LEO)", r.object_id))
        if beyond_leap_second_validity(r.epoch):
            out.append(Finding(Severity.WARNING, "LEAP_SECOND_TABLE_EXPIRED", f"{r.object_id} epoch is beyond the bundled leap-second table validity", r.object_id))
    epochs = [r.epoch for r in records if r.kind is not RecordKind.EPHEMERIS]
    if len(epochs) > 1:
        t = Time(epochs)
        spread = float((t.max() - t.min()).jd)
        if spread > 30:
            out.append(Finding(Severity.WARNING, "EPOCH_SPREAD", f"record epochs span {spread:.0f} days; the dataset mixes widely separated epochs"))
    return out


def ingest(text: str, filename: str = "", reference_time: Time | None = None, fmt: str | None = None) -> IngestResult:
    fmt = fmt or detect_format(text, filename)
    records, findings = parse(text, fmt)
    ref = reference_time or Time.now()
    findings.extend(dataset_checks(records, ref))
    stats = {
        "records": len(records),
        "objects": len({r.object_id for r in records}),
        "errors": sum(f.severity is Severity.ERROR for f in findings),
        "warnings": sum(f.severity is Severity.WARNING for f in findings),
        "with_covariance": sum(r.covariance is not None for r in records),
        "kinds": {k.value: sum(r.kind is k for r in records) for k in RecordKind},
    }
    return IngestResult(fmt, records, findings, stats)
