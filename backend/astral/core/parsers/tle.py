"""Two-Line Element set parser and validator.

Format reference: CelesTrak "FAQs: Two-Line Element Set Format" and
Hoots & Roehrich, Spacetrack Report #3 (1980). Alpha-5 catalogue numbers are
accepted (handled by the ``sgp4`` library).

TLE mean elements are only meaningful with SGP4/SDP4. They are *not*
osculating elements and carry no covariance. Positions derived from public
TLEs typically have errors of order a kilometre at epoch growing by several
kilometres per day; they are suitable for screening and research only.
"""

from __future__ import annotations

import math

from sgp4.api import WGS72, Satrec

from ..findings import Finding, Severity
from ..frames import Frame
from ..records import OrbitalRecord, RecordKind
from ..timeutil import Time

_TO_DEG = 180.0 / math.pi


def checksum(line: str) -> int:
    s = 0
    for ch in line[:68]:
        if ch.isdigit():
            s += int(ch)
        elif ch == "-":
            s += 1
    return s % 10


def _epoch_from_satrec(sat: Satrec) -> Time:
    return Time(sat.jdsatepoch, sat.jdsatepochF, format="jd", scale="utc")


def satrec_from_lines(l1: str, l2: str) -> Satrec:
    return Satrec.twoline2rv(l1, l2, WGS72)


def _check_line(line: str, n: int, ref: str, out: list[Finding]) -> bool:
    ok = True
    if len(line) != 69:
        out.append(Finding(Severity.ERROR, "TLE_LINE_LENGTH", f"line {n} has {len(line)} characters; 69 required", ref))
        ok = False
    if not line.startswith(f"{n} "):
        out.append(Finding(Severity.ERROR, "TLE_LINE_NUMBER", f"line {n} must start with '{n} '", ref))
        ok = False
    if ok:
        last = line[68]
        if not last.isdigit():
            out.append(Finding(Severity.ERROR, "TLE_CHECKSUM_MISSING", f"line {n} checksum is not a digit", ref))
            ok = False
        elif int(last) != checksum(line):
            out.append(
                Finding(
                    Severity.ERROR,
                    "TLE_CHECKSUM",
                    f"line {n} checksum {last} does not match computed {checksum(line)}",
                    ref,
                    suggestion="Verify the element set against its source; ASTRAL will not alter checksums.",
                )
            )
            ok = False
    return ok


def parse_tle_text(text: str, source_format: str = "TLE") -> tuple[list[OrbitalRecord], list[Finding]]:
    lines = [ln.rstrip("\r\n").rstrip() for ln in text.splitlines()]
    records: list[OrbitalRecord] = []
    findings: list[Finding] = []
    i = 0
    name: str | None = None
    name_line: int | None = None
    while i < len(lines):
        ln = lines[i]
        if not ln.strip():
            i += 1
            continue
        if ln.startswith("1 ") and i + 1 < len(lines) and lines[i + 1].startswith("2 "):
            l1, l2 = ln, lines[i + 1]
            ref = f"lines {name_line or i + 1}-{i + 2}"
            rec = _parse_pair(l1, l2, name, ref, source_format, findings)
            if rec is not None:
                records.append(rec)
            name, name_line = None, None
            i += 2
            continue
        if ln.startswith(("1 ", "2 ")):
            findings.append(Finding(Severity.ERROR, "TLE_ORPHAN_LINE", f"unpaired element line at line {i + 1}", f"line {i + 1}"))
            i += 1
            continue
        if name is not None:
            findings.append(Finding(Severity.WARNING, "TLE_ORPHAN_NAME", f"name line {name!r} not followed by an element set", f"line {name_line}"))
        name = ln[2:].strip() if ln.startswith("0 ") else ln.strip()
        name_line = i + 1
        i += 1
    if name is not None:
        findings.append(Finding(Severity.WARNING, "TLE_ORPHAN_NAME", f"name line {name!r} not followed by an element set", f"line {name_line}"))
    return records, findings


def _parse_pair(l1: str, l2: str, name: str | None, ref: str, source_format: str, findings: list[Finding]) -> OrbitalRecord | None:
    local: list[Finding] = []
    ok1 = _check_line(l1, 1, ref, local)
    ok2 = _check_line(l2, 2, ref, local)
    findings.extend(local)
    if not (ok1 and ok2):
        return None
    if l1[2:7] != l2[2:7]:
        findings.append(Finding(Severity.ERROR, "TLE_CATNUM_MISMATCH", f"catalogue numbers differ: {l1[2:7]!r} vs {l2[2:7]!r}", ref))
        return None
    try:
        sat = satrec_from_lines(l1, l2)
    except (ValueError, IndexError) as exc:
        findings.append(Finding(Severity.ERROR, "TLE_FIELD", f"could not parse numeric fields: {exc}", ref))
        return None
    if sat.error != 0:
        findings.append(Finding(Severity.ERROR, "TLE_SGP4_INIT", f"SGP4 initialisation error code {sat.error}", ref))
        return None
    object_id = l1[2:7].strip()
    ecc, inc = sat.ecco, sat.inclo * _TO_DEG
    n_rev_day = sat.no_kozai * 1440.0 / (2 * math.pi)
    if not (0.0 <= ecc < 1.0):
        findings.append(Finding(Severity.ERROR, "TLE_ECCENTRICITY", f"eccentricity {ecc} outside [0,1)", object_id))
        return None
    if not (0.0 <= inc <= 180.0):
        findings.append(Finding(Severity.ERROR, "TLE_INCLINATION", f"inclination {inc} deg outside [0,180]", object_id))
        return None
    if n_rev_day <= 0.0:
        findings.append(Finding(Severity.ERROR, "TLE_MEAN_MOTION", "non-positive mean motion", object_id))
        return None
    if n_rev_day > 17.0:
        findings.append(Finding(Severity.WARNING, "TLE_MEAN_MOTION_HIGH", f"mean motion {n_rev_day:.3f} rev/day implies an orbit below ~150 km", object_id))
    period_min = 1440.0 / n_rev_day
    a_er = (sat.a if sat.a > 0 else 0.0)
    perigee_km = a_er * (1 - ecc) * 6378.135 - 6378.135
    if perigee_km < 100.0:
        findings.append(Finding(Severity.WARNING, "TLE_LOW_PERIGEE", f"perigee altitude {perigee_km:.0f} km; object may have decayed", object_id))
    if period_min >= 225.0:
        findings.append(Finding(Severity.INFO, "TLE_DEEP_SPACE", f"period {period_min:.1f} min >= 225 min; SDP4 deep-space branch is used", object_id))
    epoch = _epoch_from_satrec(sat)
    rec = OrbitalRecord(
        object_id=object_id,
        object_name=name,
        kind=RecordKind.GP_ELEMENTS,
        source_format=source_format,
        epoch=epoch,
        frame=Frame.TEME,
        time_system="UTC",
        tle_line1=l1,
        tle_line2=l2,
        mean_elements={
            "eccentricity": ecc,
            "inclination_deg": inc,
            "raan_deg": sat.nodeo * _TO_DEG,
            "arg_perigee_deg": sat.argpo * _TO_DEG,
            "mean_anomaly_deg": sat.mo * _TO_DEG,
            "mean_motion_rev_day": n_rev_day,
            "bstar": sat.bstar,
            "period_min": period_min,
            "perigee_alt_km": perigee_km,
            "apogee_alt_km": a_er * (1 + ecc) * 6378.135 - 6378.135,
            "classification": l1[7],
            "intl_designator": l1[9:17].strip(),
            "element_set_no": l1[64:68].strip(),
        },
        source_ref=ref,
    )
    return rec
