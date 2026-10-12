"""CCSDS Orbit Ephemeris Message (OEM) KVN parser.

Reference: CCSDS 502.0-B-3 section 5. Supports multiple META/DATA segments,
optional acceleration columns (ignored, recorded), and COVARIANCE blocks.
Covariance blocks are attached to the segment; the covariance nearest the
segment start is used as the record's representative covariance and every
block is retained in ``extra`` for traceability.
"""

from __future__ import annotations

import numpy as np
from astropy.time import Time

from ..covariance import lower_triangle_to_matrix, validate
from ..findings import Finding, Severity
from ..frames import FrameError, parse_frame
from ..records import Covariance, OrbitalRecord, RecordKind
from ..timeutil import TimeParseError, parse_epoch

_META_REQUIRED = ("OBJECT_NAME", "OBJECT_ID", "CENTER_NAME", "REF_FRAME", "TIME_SYSTEM", "START_TIME", "STOP_TIME")
# A gap larger than this multiple of the segment's median step is reported as
# a discontinuity; interpolation is refused across it.
GAP_FACTOR = 3.0


def _kv(line: str) -> tuple[str, str]:
    k, v = line.split("=", 1)
    return k.strip().upper(), v.strip()


def parse_oem_kvn(text: str) -> tuple[list[OrbitalRecord], list[Finding]]:
    lines = text.splitlines()
    findings: list[Finding] = []
    records: list[OrbitalRecord] = []
    header: dict[str, str] = {}
    i = 0
    n = len(lines)
    seg_no = 0
    while i < n:
        line = lines[i].strip()
        if not line or line.startswith("COMMENT"):
            i += 1
            continue
        if line == "META_START":
            seg_no += 1
            meta: dict[str, str] = {}
            i += 1
            while i < n and lines[i].strip() != "META_STOP":
                ln = lines[i].strip()
                if ln and not ln.startswith("COMMENT") and "=" in ln:
                    k, v = _kv(ln)
                    meta[k] = v
                i += 1
            i += 1  # META_STOP
            epochs: list[str] = []
            rows: list[list[float]] = []
            covs: list[tuple[str, str | None, list[float]]] = []
            data_line_nos: list[int] = []
            while i < n and lines[i].strip() != "META_START":
                ln = lines[i].strip()
                if not ln or ln.startswith("COMMENT"):
                    i += 1
                    continue
                if ln == "COVARIANCE_START":
                    i += 1
                    cur_epoch, cur_frame, vals = None, None, []
                    while i < n and lines[i].strip() != "COVARIANCE_STOP":
                        c = lines[i].strip()
                        if c.startswith("EPOCH"):
                            if cur_epoch is not None:
                                covs.append((cur_epoch, cur_frame, vals))
                            cur_epoch, cur_frame, vals = _kv(c)[1], None, []
                        elif c.startswith("COV_REF_FRAME"):
                            cur_frame = _kv(c)[1]
                        elif c and not c.startswith("COMMENT"):
                            vals.extend(float(x) for x in c.split())
                        i += 1
                    if cur_epoch is not None:
                        covs.append((cur_epoch, cur_frame, vals))
                    i += 1
                    continue
                parts = ln.split()
                if len(parts) not in (7, 10):
                    findings.append(Finding(Severity.ERROR, "OEM_DATA_COLUMNS", f"line {i + 1}: expected 7 or 10 columns, got {len(parts)}", f"line {i + 1}"))
                    i += 1
                    continue
                try:
                    vals6 = [float(x) for x in parts[1:7]]
                except ValueError:
                    findings.append(Finding(Severity.ERROR, "OEM_DATA_NUMERIC", f"line {i + 1}: non-numeric state", f"line {i + 1}"))
                    i += 1
                    continue
                epochs.append(parts[0])
                rows.append(vals6)
                data_line_nos.append(i + 1)
                i += 1
            rec = _build_segment(seg_no, header, meta, epochs, rows, covs, data_line_nos, findings)
            if rec:
                records.append(rec)
            continue
        if "=" in line:
            k, v = _kv(line)
            header[k] = v
        i += 1
    if "CCSDS_OEM_VERS" not in header:
        findings.append(Finding(Severity.WARNING, "OEM_HEADER_VERSION", "CCSDS_OEM_VERS header keyword missing"))
    if seg_no == 0:
        findings.append(Finding(Severity.ERROR, "OEM_NO_SEGMENTS", "no META_START/META_STOP segments found"))
    return records, findings


def _build_segment(seg_no, header, meta, epochs, rows, covs, line_nos, findings) -> OrbitalRecord | None:
    ref = f"segment {seg_no}"
    missing = [k for k in _META_REQUIRED if k not in meta]
    if missing:
        findings.append(Finding(Severity.ERROR, "OEM_META_MISSING", f"{ref}: missing metadata {', '.join(missing)}", ref))
        return None
    oid = meta["OBJECT_ID"]
    if meta["CENTER_NAME"].upper() != "EARTH":
        findings.append(Finding(Severity.ERROR, "OEM_CENTER", f"CENTER_NAME {meta['CENTER_NAME']!r} unsupported (EARTH only)", oid))
        return None
    try:
        frame = parse_frame(meta["REF_FRAME"])
    except FrameError as exc:
        findings.append(Finding(Severity.ERROR, "OEM_FRAME", str(exc), oid))
        return None
    tsys = meta["TIME_SYSTEM"].upper()
    if len(rows) < 2:
        findings.append(Finding(Severity.ERROR, "OEM_TOO_FEW_STATES", f"{ref}: at least 2 states required for interpolation", oid))
        return None
    try:
        t = Time([parse_epoch(e, tsys) for e in epochs])
        start = parse_epoch(meta["START_TIME"], tsys)
        stop = parse_epoch(meta["STOP_TIME"], tsys)
    except TimeParseError as exc:
        findings.append(Finding(Severity.ERROR, "OEM_EPOCH", f"{ref}: {exc}", oid))
        return None
    states = np.asarray(rows, dtype=float)
    if not np.all(np.isfinite(states)):
        findings.append(Finding(Severity.ERROR, "OEM_NONFINITE", f"{ref}: non-finite state values", oid))
        return None
    sec = (t.utc.jd1 - t.utc.jd1[0] + t.utc.jd2 - t.utc.jd2[0]) * 86400.0
    d = np.diff(sec)
    if np.any(d <= 0):
        bad = int(np.argmax(d <= 0))
        findings.append(Finding(Severity.ERROR, "OEM_NON_MONOTONIC", f"{ref}: epochs not strictly increasing at data line {line_nos[bad + 1]}", oid))
        return None
    med = float(np.median(d))
    gaps = np.where(d > GAP_FACTOR * med)[0]
    for g in gaps:
        findings.append(Finding(Severity.WARNING, "OEM_GAP", f"{ref}: gap of {d[g]:.1f} s after {epochs[g]} (median step {med:.1f} s); interpolation refused across gap", oid))
    if (t[0] - start).sec < -1e-3 or (t[-1] - stop).sec > 1e-3:
        findings.append(Finding(Severity.WARNING, "OEM_OUTSIDE_SPAN", f"{ref}: data outside START_TIME/STOP_TIME", oid))
    radii = np.linalg.norm(states[:, :3], axis=1)
    if np.any(radii < 6378.137 * 0.99):
        findings.append(Finding(Severity.WARNING, "OEM_BELOW_SURFACE", f"{ref}: some positions are below the Earth's surface", oid))
    if np.any(radii > 2.0e6):
        findings.append(Finding(Severity.WARNING, "OEM_IMPLAUSIBLE_RADIUS", f"{ref}: positions beyond 2e6 km; check units", oid))
    deg = int(meta.get("INTERPOLATION_DEGREE", "0") or 0)
    cov_obj = None
    cov_all = []
    for cep, cframe, vals in covs:
        try:
            m = lower_triangle_to_matrix(vals, 6)
        except ValueError as exc:
            findings.append(Finding(Severity.ERROR, "OEM_COV_SIZE", f"{ref}: covariance at {cep}: {exc}", oid))
            continue
        chk = validate(m, oid)
        findings.extend(chk.findings)
        cf = (cframe or meta["REF_FRAME"]).upper()
        cf_norm = "RTN" if cf in ("RTN", "RSW", "RIC", "UVW") else parse_frame(cf).value
        cov_all.append({"epoch": cep, "frame": cf_norm, "valid": chk.valid})
        if chk.valid and cov_obj is None:
            cov_obj = Covariance(m, cf_norm, parse_epoch(cep, tsys), f"OEM {ref}")
    rec = OrbitalRecord(
        object_id=oid,
        object_name=meta.get("OBJECT_NAME"),
        kind=RecordKind.EPHEMERIS,
        source_format="OEM_KVN",
        epoch=t[0],
        frame=frame,
        time_system=tsys,
        ephem_epochs=t,
        ephem_states=states,
        interpolation=meta.get("INTERPOLATION", "HERMITE").upper(),
        interpolation_degree=deg or None,
        covariance=cov_obj,
        source_ref=ref,
        extra={
            "originator": header.get("ORIGINATOR"),
            "creation_date": header.get("CREATION_DATE"),
            "oem_version": header.get("CCSDS_OEM_VERS"),
            "useable_start": meta.get("USEABLE_START_TIME"),
            "useable_stop": meta.get("USEABLE_STOP_TIME"),
            "gaps_after_index": [int(g) for g in gaps],
            "covariances": cov_all,
        },
    )
    if tsys != "UTC":
        rec.transformations.append(f"epochs converted {tsys} -> UTC (ERFA via astropy)")
    return rec
