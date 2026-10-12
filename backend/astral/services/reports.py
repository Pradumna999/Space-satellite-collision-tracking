"""Reproducible reports (PDF, CSV, JSON) and CCSDS exports (OEM, CDM)."""

from __future__ import annotations

import csv
import io
import json
from datetime import UTC, datetime

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from astropy.time import Time, TimeDelta  # noqa: E402
from reportlab.lib import colors  # noqa: E402
from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.lib.styles import getSampleStyleSheet  # noqa: E402
from reportlab.lib.units import mm  # noqa: E402
from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from .. import ALGORITHM_VERSIONS, __version__  # noqa: E402
from ..core.covariance import inertial_to_rtn  # noqa: E402
from ..core.frames import Frame  # noqa: E402
from ..core.parsers.cdm import COV_KEYS  # noqa: E402
from ..core.parsers.oem import parse_oem_kvn  # noqa: E402
from ..core.propagation import make_propagator, select_records  # noqa: E402
from ..db.models import AnalysisJob, Dataset, DatasetVersion, Encounter, ProbabilityCalculation, ValidationFinding  # noqa: E402
from .datasets import load_snapshot  # noqa: E402

REPORT_VERSION = ALGORITHM_VERSIONS["report"]

LIMITATIONS = [
    "Encounters satisfy a geometric screening threshold. A small miss distance is not a collision prediction.",
    "Positions from public TLE/OMM elements (SGP4) have errors of order kilometres growing with data age; they support screening and research only.",
    "Probability of collision is reported only where both covariances and an explicit hard-body radius were available; otherwise the status INSUFFICIENT_DATA_FOR_PC is shown.",
    "ML priority scores (if present) are experimental, not validated on operational data, and are not probabilities of collision.",
    "This report has not been reviewed by a qualified conjunction-assessment authority and is not suitable for operational decisions.",
]


def _context(db: Session, job: AnalysisJob) -> dict:
    dv = db.get(DatasetVersion, job.dataset_version_id)
    ds = db.get(Dataset, dv.dataset_id)
    encs = list(db.scalars(select(Encounter).where(Encounter.job_id == job.id).order_by(Encounter.tca)))
    findings = list(db.scalars(select(ValidationFinding).where(ValidationFinding.dataset_version_id == dv.id)))
    return {"dv": dv, "ds": ds, "encs": encs, "findings": findings}


def encounters_csv(db: Session, job: AnalysisJob) -> bytes:
    c = _context(db, job)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["# ASTRAL encounter export", f"job={job.id}", f"config_sha256={job.config_sha256}", f"dataset_snapshot_sha256={c['dv'].snapshot_sha256}",
                f"report={REPORT_VERSION}"])
    w.writerow(["encounter_id", "primary_id", "secondary_id", "tca_utc", "miss_km", "rel_speed_km_s", "radial_km", "intrack_km", "crosstrack_km",
                "approach_angle_deg", "frame", "refinement_status", "covariance_available", "pc_status", "pc_value", "ml_priority_experimental",
                "flags"])
    for e in c["encs"]:
        rtn = e.geometry["rel_pos_rtn_km"]
        w.writerow([e.id, e.primary_id, e.secondary_id, e.tca_iso, f"{e.miss_km:.6f}", f"{e.rel_speed_km_s:.6f}", f"{rtn[0]:.6f}", f"{rtn[1]:.6f}",
                    f"{rtn[2]:.6f}", f"{e.geometry['approach_angle_deg']:.3f}", e.frame, e.refinement_status, e.covariance_available, e.pc_status,
                    "" if e.pc_value is None else f"{e.pc_value:.6e}", "" if e.ml_priority is None else f"{e.ml_priority:.4f}", ";".join(e.flags)])
    return buf.getvalue().encode()


def report_json(db: Session, job: AnalysisJob) -> bytes:
    c = _context(db, job)
    pcs = {p.encounter_id: p for p in db.scalars(select(ProbabilityCalculation).join(Encounter).where(Encounter.job_id == job.id))}
    doc = {
        "schema": "astral-report/1",
        "report_version": REPORT_VERSION,
        "generated_utc": datetime.now(UTC).isoformat(),
        "analysis": {"job_id": job.id, "kind": job.kind, "status": job.status, "config": job.config, "config_sha256": job.config_sha256,
                     "started": job.started_at.isoformat() if job.started_at else None,
                     "finished": job.finished_at.isoformat() if job.finished_at else None, "software": job.software,
                     "stats": job.stats, "warnings": job.warnings},
        "input": {"dataset": c["ds"].name, "dataset_version": c["dv"].version, "dataset_version_id": c["dv"].id,
                  "snapshot_sha256": c["dv"].snapshot_sha256, "provenance": c["dv"].provenance, "format": c["dv"].format,
                  "validation": {"errors": sum(f.severity == "error" for f in c["findings"]), "warnings": sum(f.severity == "warning" for f in c["findings"])}},
        "encounters": [{
            "id": e.id, "primary": e.primary_id, "secondary": e.secondary_id, "tca_utc": e.tca_iso, "miss_km": e.miss_km,
            "rel_speed_km_s": e.rel_speed_km_s, "geometry": e.geometry, "frame": e.frame, "refinement_status": e.refinement_status,
            "flags": e.flags, "data_age_days": e.data_age_days, "propagators": e.propagators,
            "probability": pcs[e.id].result if e.id in pcs else None,
            "ml_priority_experimental": e.ml_priority, "ml_model": e.ml_model_version,
        } for e in c["encs"]],
        "limitations": LIMITATIONS,
        "reproduce": {"how": "Re-run the job via POST /api/v1/projects/{pid}/jobs/{id}/rerun; inputs are the immutable snapshot above.",
                      "dataset_snapshot_sha256": c["dv"].snapshot_sha256, "config_sha256": job.config_sha256},
    }
    return json.dumps(doc, indent=2, default=str).encode()


def _fig_png(fig) -> io.BytesIO:
    b = io.BytesIO()
    fig.savefig(b, format="png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    b.seek(0)
    return b


def report_pdf(db: Session, job: AnalysisJob) -> bytes:
    c = _context(db, job)
    ss = getSampleStyleSheet()
    out = io.BytesIO()
    doc = SimpleDocTemplate(out, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=16 * mm,
                            title=f"ASTRAL analysis {job.id}", author="ASTRAL")
    story = []
    h, p = ss["Heading1"], ss["BodyText"]
    small = ss["BodyText"].clone("small", fontSize=8, leading=10)
    story.append(Paragraph(f"ASTRAL analysis report — job {job.id}", h))
    story.append(Paragraph(f"Generated {datetime.now(UTC).isoformat(timespec='seconds')} · report {REPORT_VERSION} · ASTRAL {__version__}", small))
    story.append(Spacer(1, 6))
    meta = [["Analysis kind", job.kind], ["Status", job.status], ["Dataset", f"{c['ds'].name} v{c['dv'].version} ({c['dv'].format})"],
            ["Snapshot SHA-256", c["dv"].snapshot_sha256], ["Config SHA-256", job.config_sha256],
            ["Configuration", json.dumps(job.config)], ["Software", json.dumps({k: v for k, v in job.software.items() if k != 'algorithms'})],
            ["Algorithms", json.dumps(job.software.get("algorithms", {}))]]
    t = Table([[Paragraph(a, small), Paragraph(str(b), small)] for a, b in meta], colWidths=[35 * mm, 135 * mm])
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.25, colors.grey), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story += [t, Spacer(1, 8)]
    st = job.stats or {}
    if job.kind == "screening" and st:
        story.append(Paragraph("Screening funnel", ss["Heading2"]))
        labels = ["pairs total", "radial overlap", "flagged", "encounters"]
        vals = [st.get("pairs_total") or 0, st.get("pairs_radial_band_overlap") or 0, st.get("pairs_flagged") or 0, st.get("encounters") or 0]
        fig, ax = plt.subplots(figsize=(6, 2.2))
        ax.barh(labels[::-1], vals[::-1], color="#444")
        ax.set_xscale("symlog")
        ax.set_xlabel("object pairs (count)")
        ax.set_title(f"{st.get('objects')} objects · step {st.get('step_s')} s · threshold {st.get('threshold_km')} km · runtime {st.get('runtime_s', 0):.1f} s", fontsize=8)
        story += [Image(_fig_png(fig), width=150 * mm, height=55 * mm), Spacer(1, 6)]
    encs = c["encs"]
    if encs:
        story.append(Paragraph("Encounters (miss distance at TCA)", ss["Heading2"]))
        fig, ax = plt.subplots(figsize=(6, 2.6))
        tt = [Time(e.tca_iso.rstrip("Z"), scale="utc").datetime for e in encs]
        ax.scatter(tt, [e.miss_km for e in encs], s=14, color="#c21500")
        ax.set_ylabel("miss distance (km)")
        ax.set_xlabel("TCA (UTC)")
        ax.grid(alpha=0.3)
        fig.autofmt_xdate()
        story += [Image(_fig_png(fig), width=150 * mm, height=65 * mm), Spacer(1, 6)]
        rows = [["Primary", "Secondary", "TCA (UTC)", "Miss km", "v_rel km/s", "Pc status", "Pc"]]
        for e in encs[:200]:
            rows.append([e.primary_id, e.secondary_id, e.tca_iso, f"{e.miss_km:.3f}", f"{e.rel_speed_km_s:.2f}", e.pc_status.replace("_", " "),
                         "—" if e.pc_value is None else f"{e.pc_value:.2e}"])
        t = Table(rows, repeatRows=1)
        t.setStyle(TableStyle([("FONTSIZE", (0, 0), (-1, -1), 7), ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                               ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eeeeee"))]))
        story.append(t)
        if len(encs) > 200:
            story.append(Paragraph(f"{len(encs) - 200} further encounters in CSV/JSON exports.", small))
    else:
        story.append(Paragraph("No encounters satisfied the screening threshold in the analysed window.", p))
    story += [PageBreak(), Paragraph("Data quality", ss["Heading2"])]
    fc = {}
    for f in c["findings"]:
        fc.setdefault((f.severity, f.code), 0)
        fc[(f.severity, f.code)] += 1
    if fc:
        t = Table([["Severity", "Code", "Count"]] + [[a, b, n] for (a, b), n in sorted(fc.items())])
        t.setStyle(TableStyle([("FONTSIZE", (0, 0), (-1, -1), 8), ("GRID", (0, 0), (-1, -1), 0.25, colors.grey)]))
        story.append(t)
    else:
        story.append(Paragraph("No validation findings.", p))
    if job.warnings:
        story.append(Paragraph("Analysis warnings", ss["Heading2"]))
        for w in job.warnings[:40]:
            story.append(Paragraph("• " + w.replace("<", "&lt;"), small))
    story.append(Paragraph("Limitations", ss["Heading2"]))
    for lim in LIMITATIONS:
        story.append(Paragraph("• " + lim, small))
    story.append(Paragraph("Reproducibility", ss["Heading2"]))
    story.append(Paragraph(f"Inputs: immutable snapshot {c['dv'].snapshot_sha256}. Configuration hash {job.config_sha256}. "
                           "A rerun references the same snapshot; results can be compared run-to-run in the Reports view.", small))
    doc.build(story)
    return out.getvalue()


def export_oem(records, object_id: str, start: Time, duration_s: float, step_s: float = 60.0) -> str:
    """OEM (KVN) of an object's propagated nominal trajectory, verified by re-parsing."""
    chosen, _ = select_records(records)
    if object_id not in chosen:
        raise ValueError("object not propagatable in this dataset")
    p = make_propagator(chosen[object_id])
    offs = np.arange(0, duration_s + 1e-9, step_s)
    res = p.propagate(start, offs)
    frame = "TEME" if p.frame is Frame.TEME else p.frame.value
    lines = ["CCSDS_OEM_VERS = 2.0", f"COMMENT Generated by ASTRAL {__version__}; nominal propagation by {p.method}. No covariance.",
             f"CREATION_DATE = {Time.now().utc.isot[:19]}", "ORIGINATOR = ASTRAL", "META_START",
             f"OBJECT_NAME = {chosen[object_id].object_name or object_id}", f"OBJECT_ID = {object_id}", "CENTER_NAME = EARTH",
             f"REF_FRAME = {frame}", "TIME_SYSTEM = UTC"]
    ok = np.where(res.valid)[0]
    if len(ok) < 2:
        raise ValueError("fewer than two valid states in the requested span")
    t0 = start + TimeDelta(offs[ok[0]], format="sec")
    t1 = start + TimeDelta(offs[ok[-1]], format="sec")
    lines += [f"START_TIME = {Time(t0, precision=3).isot}", f"STOP_TIME = {Time(t1, precision=3).isot}", "INTERPOLATION = HERMITE",
              "INTERPOLATION_DEGREE = 3", "META_STOP"]
    for k in ok:
        t = Time(start + TimeDelta(offs[k], format="sec"), precision=3).isot
        r, v = res.r_km[k], res.v_km_s[k]
        lines.append(f"{t} {r[0]:.6f} {r[1]:.6f} {r[2]:.6f} {v[0]:.9f} {v[1]:.9f} {v[2]:.9f}")
    text = "\n".join(lines) + "\n"
    recs, findings = parse_oem_kvn(text)
    if not recs or any(f.severity.value == "error" for f in findings):
        raise RuntimeError("generated OEM failed ASTRAL's own OEM validation")
    return text


def export_cdm(db: Session, enc: Encounter) -> str:
    """CDM (KVN) for an encounter with both covariances (CDM requires them)."""
    pcs = db.scalar(select(ProbabilityCalculation).where(ProbabilityCalculation.encounter_id == enc.id))
    if enc.covariance_available != "both" or pcs is None:
        raise ValueError("CCSDS 508.0-B-1 requires covariance for both objects; this encounter has none or partial covariance")
    job = db.get(AnalysisJob, enc.job_id)
    dv = db.get(DatasetVersion, job.dataset_version_id)
    records, _ = load_snapshot(dv)
    covs = {r.object_id: r for r in records if r.covariance is not None and r.source_format == "CDM_KVN"}
    lines = ["CCSDS_CDM_VERS = 1.0", f"COMMENT Re-assessment by ASTRAL {__version__} (research software, not an operational product)",
             f"CREATION_DATE = {Time.now().utc.isot[:19]}", "ORIGINATOR = ASTRAL", "MESSAGE_FOR = ANALYST", f"MESSAGE_ID = ASTRAL-{enc.id}",
             f"TCA = {enc.tca_iso.rstrip('Z')}", f"MISS_DISTANCE = {enc.miss_km * 1000:.3f} [m]", f"RELATIVE_SPEED = {enc.rel_speed_km_s * 1000:.3f} [m/s]"]
    rtn = np.asarray(enc.geometry["rel_pos_rtn_km"]) * 1000
    vrtn = np.asarray(enc.geometry["rel_vel_rtn_km_s"]) * 1000
    lines += [f"RELATIVE_POSITION_{a} = {x:.3f} [m]" for a, x in zip("RTN", rtn)]
    lines += [f"RELATIVE_VELOCITY_{a} = {x:.3f} [m/s]" for a, x in zip("RTN", vrtn)]
    if enc.pc_value is not None:
        lines += [f"COLLISION_PROBABILITY = {enc.pc_value:.6e}", "COLLISION_PROBABILITY_METHOD = FOSTER-1992"]
    for role, oid, st in (("OBJECT1", enc.primary_id, enc.primary_state), ("OBJECT2", enc.secondary_id, enc.secondary_state)):
        rec = covs.get(oid)
        if rec is None:
            raise ValueError(f"covariance for {oid} not found in source snapshot")
        c = rec.covariance.matrix if rec.covariance.frame == "RTN" else inertial_to_rtn(rec.covariance.matrix, np.asarray(st[:3]), np.asarray(st[3:]))
        lines += [f"OBJECT = {role}", f"OBJECT_DESIGNATOR = {oid}", f"CATALOG_NAME = {rec.extra.get('catalog_name') or 'UNKNOWN'}",
                  f"OBJECT_NAME = {rec.object_name or oid}", f"INTERNATIONAL_DESIGNATOR = {rec.extra.get('international_designator') or 'UNKNOWN'}",
                  "EPHEMERIS_NAME = NONE", f"COVARIANCE_METHOD = {rec.extra.get('covariance_method') or 'DEFAULT'}",
                  f"MANEUVERABLE = {rec.extra.get('maneuverable') or 'N/A'}", f"REF_FRAME = {enc.frame}"]
        lines += [f"{k} = {x:.6f} [km]" for k, x in zip(("X", "Y", "Z"), st[:3])]
        lines += [f"{k} = {x:.9f} [km/s]" for k, x in zip(("X_DOT", "Y_DOT", "Z_DOT"), st[3:])]
        vals = [c[i, j] * 1e6 for i in range(6) for j in range(i + 1)]
        lines += [f"{k} = {v:.6e}" for k, v in zip(COV_KEYS, vals)]
    return "\n".join(lines) + "\n"
