"""CCSDS Orbit Mean-Elements Message (OMM) parser: KVN, XML, JSON, CSV.

Reference: CCSDS 502.0-B-3, Orbit Data Messages (see DATA_FORMATS.md for the
edition note). JSON and CSV follow the field naming used by CelesTrak's GP
data service, which reuses OMM keywords.

Only OMMs whose MEAN_ELEMENT_THEORY is SGP4 (or SGP/SGP4 equivalents in
CelesTrak exports) with REF_FRAME TEME and TIME_SYSTEM UTC are accepted for
propagation, because those are the conditions under which the elements are
consistent with SGP4. SGP4-XP elements are rejected: ASTRAL does not
implement SGP4-XP.
"""

from __future__ import annotations

import csv
import io
import json
import math
from typing import Any

import defusedxml.ElementTree as DET
from sgp4.api import WGS72, Satrec

from ..findings import Finding, Severity
from ..frames import Frame
from ..records import OrbitalRecord, RecordKind
from ..timeutil import TimeParseError, parse_epoch

REQUIRED = (
    "EPOCH",
    "MEAN_MOTION",
    "ECCENTRICITY",
    "INCLINATION",
    "RA_OF_ASC_NODE",
    "ARG_OF_PERICENTER",
    "MEAN_ANOMALY",
    "NORAD_CAT_ID",
    "BSTAR",
)
# OMM gives MEAN_MOTION_DOT in rev/day^2 and MEAN_MOTION_DDOT in rev/day^3;
# sgp4init expects the TLE convention (rad/min^2, rad/min^3 after its own
# internal scaling). These factors match the sgp4 library's own OMM loader.
_NDOT_UNITS = 1440.0 * 1440.0 / (2 * math.pi)
_NDDOT_UNITS = 1440.0 * 1440.0 * 1440.0 / (2 * math.pi)


def _num(fields: dict[str, Any], key: str, default: float | None = None) -> float:
    v = fields.get(key, default)
    if v is None or v == "":
        if default is not None:
            return default
        raise KeyError(key)
    x = float(v)
    if not math.isfinite(x):
        raise ValueError(f"{key} is not finite")
    return x


def satrec_from_omm(fields: dict[str, Any]) -> tuple[Satrec, float]:
    """Initialise SGP4 from OMM mean elements. Returns (satrec, epoch_days_since_1949_12_31)."""
    epoch_t = parse_epoch(str(fields["EPOCH"]), "UTC")
    epoch_days = (epoch_t.utc.jd1 - 2433281.5) + epoch_t.utc.jd2  # JD of 1949-12-31 00:00 UTC
    sat = Satrec()
    sat.sgp4init(
        WGS72,
        "i",
        int(float(fields["NORAD_CAT_ID"])),
        float(epoch_days),
        _num(fields, "BSTAR"),
        _num(fields, "MEAN_MOTION_DOT", 0.0) / _NDOT_UNITS,
        _num(fields, "MEAN_MOTION_DDOT", 0.0) / _NDDOT_UNITS,
        _num(fields, "ECCENTRICITY"),
        math.radians(_num(fields, "ARG_OF_PERICENTER")),
        math.radians(_num(fields, "INCLINATION")),
        math.radians(_num(fields, "MEAN_ANOMALY")),
        _num(fields, "MEAN_MOTION") / 720.0 * math.pi,
        math.radians(_num(fields, "RA_OF_ASC_NODE")),
    )
    return sat, float(epoch_days)


def record_from_fields(fields: dict[str, Any], ref: str, fmt: str, findings: list[Finding]) -> OrbitalRecord | None:
    fields = {k.strip().upper(): (v.strip() if isinstance(v, str) else v) for k, v in fields.items()}
    oid = str(fields.get("NORAD_CAT_ID") or fields.get("OBJECT_ID") or ref)
    missing = [k for k in REQUIRED if fields.get(k) in (None, "")]
    if missing:
        findings.append(Finding(Severity.ERROR, "OMM_MISSING_FIELD", f"missing required fields: {', '.join(missing)}", oid))
        return None
    theory = str(fields.get("MEAN_ELEMENT_THEORY", "SGP4")).upper()
    if theory not in ("SGP4", "SGP/SGP4"):
        findings.append(Finding(Severity.ERROR, "OMM_THEORY", f"MEAN_ELEMENT_THEORY {theory!r} is not supported (SGP4 only)", oid))
        return None
    frame = str(fields.get("REF_FRAME", "TEME")).upper()
    tsys = str(fields.get("TIME_SYSTEM", "UTC")).upper()
    if frame != "TEME" or tsys != "UTC":
        findings.append(Finding(Severity.ERROR, "OMM_FRAME_TIME", f"SGP4 elements require REF_FRAME TEME and TIME_SYSTEM UTC; got {frame}/{tsys}", oid))
        return None
    center = str(fields.get("CENTER_NAME", "EARTH")).upper()
    if center != "EARTH":
        findings.append(Finding(Severity.ERROR, "OMM_CENTER", f"CENTER_NAME {center!r} unsupported", oid))
        return None
    try:
        epoch = parse_epoch(str(fields["EPOCH"]), "UTC")
        sat, _ = satrec_from_omm(fields)
    except (TimeParseError, ValueError, KeyError) as exc:
        findings.append(Finding(Severity.ERROR, "OMM_FIELD", f"invalid field: {exc}", oid))
        return None
    if sat.error != 0:
        findings.append(Finding(Severity.ERROR, "OMM_SGP4_INIT", f"SGP4 initialisation error code {sat.error}", oid))
        return None
    ecc = float(fields["ECCENTRICITY"])
    n = float(fields["MEAN_MOTION"])
    if not 0 <= ecc < 1:
        findings.append(Finding(Severity.ERROR, "OMM_ECCENTRICITY", f"eccentricity {ecc} outside [0,1)", oid))
        return None
    if n <= 0:
        findings.append(Finding(Severity.ERROR, "OMM_MEAN_MOTION", "non-positive mean motion", oid))
        return None
    period = 1440.0 / n
    if period >= 225.0:
        findings.append(Finding(Severity.INFO, "TLE_DEEP_SPACE", f"period {period:.1f} min >= 225 min; SDP4 deep-space branch is used", oid))
    a_er = sat.a
    norad = str(int(float(fields["NORAD_CAT_ID"])))
    return OrbitalRecord(
        object_id=norad,
        object_name=fields.get("OBJECT_NAME") or None,
        kind=RecordKind.GP_ELEMENTS,
        source_format=fmt,
        epoch=epoch,
        frame=Frame.TEME,
        time_system="UTC",
        mean_elements={
            "eccentricity": ecc,
            "inclination_deg": float(fields["INCLINATION"]),
            "raan_deg": float(fields["RA_OF_ASC_NODE"]),
            "arg_perigee_deg": float(fields["ARG_OF_PERICENTER"]),
            "mean_anomaly_deg": float(fields["MEAN_ANOMALY"]),
            "mean_motion_rev_day": n,
            "bstar": float(fields["BSTAR"]),
            "mean_motion_dot": float(fields.get("MEAN_MOTION_DOT") or 0.0),
            "mean_motion_ddot": float(fields.get("MEAN_MOTION_DDOT") or 0.0),
            "period_min": period,
            "perigee_alt_km": a_er * (1 - ecc) * 6378.135 - 6378.135,
            "apogee_alt_km": a_er * (1 + ecc) * 6378.135 - 6378.135,
            "intl_designator": fields.get("OBJECT_ID"),
            "omm_fields": {k: fields[k] for k in fields if isinstance(fields[k], (str, int, float))},
        },
        source_ref=ref,
    )


def parse_omm_kvn(text: str) -> tuple[list[OrbitalRecord], list[Finding]]:
    fields: dict[str, str] = {}
    findings: list[Finding] = []
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("COMMENT"):
            continue
        if "=" not in line:
            findings.append(Finding(Severity.WARNING, "OMM_KVN_SYNTAX", f"line {n} ignored: not KEY = VALUE", f"line {n}"))
            continue
        k, v = line.split("=", 1)
        v = v.strip()
        if "[" in v:  # strip optional unit annotation, e.g. "0.1 [rev/day]"
            v = v.split("[", 1)[0].strip()
        fields[k.strip().upper()] = v
    rec = record_from_fields(fields, "KVN", "OMM_KVN", findings)
    return ([rec] if rec else []), findings


def parse_omm_xml(text: str) -> tuple[list[OrbitalRecord], list[Finding]]:
    findings: list[Finding] = []
    records: list[OrbitalRecord] = []
    try:
        root = DET.fromstring(text)
    except Exception as exc:  # defusedxml raises several exception types for hostile/malformed XML
        return [], [Finding(Severity.ERROR, "OMM_XML_PARSE", f"XML rejected: {type(exc).__name__}: {exc}")]

    def local(tag: str) -> str:
        return tag.rsplit("}", 1)[-1]

    omms = [el for el in root.iter() if local(el.tag) == "omm"]
    for idx, omm in enumerate(omms, 1):
        fields: dict[str, str] = {}
        for el in omm.iter():
            if len(el) == 0 and el.text and el.text.strip():
                fields[local(el.tag).upper()] = el.text.strip()
        rec = record_from_fields(fields, f"omm[{idx}]", "OMM_XML", findings)
        if rec:
            records.append(rec)
    if not omms:
        findings.append(Finding(Severity.ERROR, "OMM_XML_EMPTY", "no <omm> elements found"))
    return records, findings


def parse_omm_json(items: list[dict[str, Any]]) -> tuple[list[OrbitalRecord], list[Finding]]:
    findings: list[Finding] = []
    records: list[OrbitalRecord] = []
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            findings.append(Finding(Severity.ERROR, "OMM_JSON_ITEM", f"item {i} is not an object", f"item {i}"))
            continue
        rec = record_from_fields(item, f"item {i}", "OMM_JSON", findings)
        if rec:
            records.append(rec)
    return records, findings


def parse_omm_csv(text: str) -> tuple[list[OrbitalRecord], list[Finding]]:
    findings: list[Finding] = []
    records: list[OrbitalRecord] = []
    reader = csv.DictReader(io.StringIO(text))
    for i, row in enumerate(reader, 2):
        rec = record_from_fields(row, f"row {i}", "OMM_CSV", findings)
        if rec:
            records.append(rec)
    return records, findings


def loads_json(text: str) -> Any:
    return json.loads(text)
