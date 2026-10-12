"""Command-line administration.

    python -m astral.cli migrate
    python -m astral.cli create-admin --email a@b.c --name "Admin"   (password read from ASTRAL_ADMIN_PASSWORD or prompted)
    python -m astral.cli seed-live --email a@b.c                      (real public CelesTrak data; needs internet)
    python -m astral.cli seed-demo --email a@b.c                      (generated sample scenarios with covariance)
    python -m astral.cli train-ml [--activate]
    python -m astral.cli run-jobs                                     (process queued jobs once, synchronously)
    python -m astral.cli benchmark [--sizes 50,200,800]
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import platform
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from astropy.time import Time
from sqlalchemy import select

from .db.models import Dataset, MLModel, Project, ProjectMember, SystemInfo, User


def migrate() -> None:
    from alembic.config import Config

    from alembic import command

    cfg = Config(str(Path(__file__).resolve().parent.parent / "alembic.ini"))
    cfg.set_main_option("script_location", str(Path(__file__).resolve().parent.parent / "alembic"))
    command.upgrade(cfg, "head")
    print("database at head")


def create_admin(email: str, name: str) -> None:
    from .db.session import SessionLocal
    from .services.auth import create_user

    pw = os.environ.get("ASTRAL_ADMIN_PASSWORD") or getpass.getpass("Admin password (min 12 chars): ")
    db = SessionLocal()
    try:
        u = create_user(db, email, pw, name, is_admin=True)
        print(f"created admin user {u.email} (id {u.id})")
    finally:
        db.close()


def seed_demo(email: str) -> None:
    from .core.frames import Frame
    from .core.parsers import ingest
    from .core.propagation import make_propagator, select_records
    from .core.screening import ScreeningConfig, screen
    from .core.synthetic import demo_catalogue, synthetic_cdm
    from .db.session import SessionLocal
    from .services.datasets import create_version
    from .services.jobs import run_pending_sync, submit

    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.email == email.lower()))
        if user is None:
            sys.exit(f"no user {email}; create it first")
        epoch = Time(datetime.now(UTC).replace(minute=0, second=0, microsecond=0, tzinfo=None), scale="utc")
        p = Project(name="Covariance & manoeuvre studies", description="Sample scenarios for covariance-based probability assessment and manoeuvre comparison.",
                    is_demo=True, created_by=user.id)
        db.add(p)
        db.flush()
        db.add(ProjectMember(project_id=p.id, user_id=user.id, role="owner"))
        db.commit()
        tle = demo_catalogue(epoch, n_background=60, n_engineered=8, seed=11)
        dv = create_version(db, p.id, user.id, "sample-catalogue.tle", tle.encode(), dataset_name="Sample catalogue (TLE)",
                            origin="sample", is_synthetic=True, provenance={"generator": "astral.core.synthetic.demo_catalogue", "seed": 11,
                                                                                 "epoch": epoch.isot})
        cfg = {"kind": "screening", "start_utc": epoch.isot + "Z", "duration_hours": 72, "step_s": 30, "threshold_km": 5.0}
        submit(db, p.id, dv, cfg, user.id)
        # CDMs: computed geometry for the engineered encounters + ASSUMED covariances
        res = ingest(tle, reference_time=epoch)
        chosen, _ = select_records(res.records)
        props = {k: make_propagator(v) for k, v in chosen.items()}
        sr = screen(props, ScreeningConfig(start=epoch, duration_s=72 * 3600, step_s=30, threshold_km=5.0))
        cdms = []
        for i, e in enumerate(sr.encounters[:4]):
            names = (chosen[e.primary].object_name or e.primary, chosen[e.secondary].object_name or e.secondary)
            cdms.append(synthetic_cdm(e.primary_state[:3], e.primary_state[3:], e.secondary_state[:3], e.secondary_state[3:], e.tca,
                                      Frame(e.frame), msg_id=f"SMP-{i + 1:04d}",
                                      ids=(e.primary, e.secondary), names=names))
        for i, c in enumerate(cdms):
            dvc = create_version(db, p.id, user.id, f"sample-{i + 1}.cdm", c.encode(), dataset_name=f"Conjunction data message {i + 1}",
                                 origin="sample", is_synthetic=True, provenance={"generator": "astral.core.synthetic.synthetic_cdm",
                                                                                    "covariance": "assumed diagonal RTN"})
            submit(db, p.id, dvc, {"kind": "cdm_assessment", "hbr_m": 20.0, "monte_carlo_samples": 200000, "seed": i}, user.id)
        n = run_pending_sync()
        print(f"demo project {p.id} created; {n} jobs executed")
    finally:
        db.close()


LIVE_GROUPS = ("stations", "visual", "iridium-33-debris", "cosmos-2251-debris", "fengyun-1c-debris")


def seed_live(email: str, groups: list[str], hours: float, threshold_km: float, project_id: int | None = None) -> None:
    """Project with real public GP data from CelesTrak, screened over the next `hours`."""
    from .db.session import SessionLocal
    from .services.datasets import create_version
    from .services.jobs import run_pending_sync, submit
    from .services.providers import ProviderError, celestrak_fetch

    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.email == email.lower()))
        if user is None:
            sys.exit(f"no user {email}; create it first")
        parts, fetched = [], []
        for g in groups:
            try:
                data, prov = celestrak_fetch(db, group=g, fmt="tle")
            except ProviderError as exc:
                print(f"skipped {g}: {exc}")
                continue
            text = data.decode("utf-8", "replace").strip() + "\n"
            parts.append(text)
            fetched.append(prov)
            print(f"fetched {g}: {sum(1 for ln in text.splitlines() if ln.startswith('1 '))} element sets")
        complete = len(parts) == len(groups)
        dataset_id = None
        if project_id is not None:
            p = db.get(Project, project_id)
            if p is None:
                sys.exit(f"no project {project_id}")
            ds = db.scalar(select(Dataset).where(Dataset.project_id == p.id, Dataset.name == "CelesTrak LEO selection"))
            dataset_id = ds.id if ds else None
            if not complete:
                # Some groups were not re-downloaded (CelesTrak's 2-hour rule or an outage). A new version
                # would hold only part of the catalogue, so re-run the search on the latest complete version.
                latest = ds.versions[-1] if ds and ds.versions else None
                if latest is None:
                    sys.exit("no data fetched and no existing dataset to re-search")
                start = Time(datetime.now(UTC).replace(minute=0, second=0, microsecond=0, tzinfo=None), scale="utc")
                submit(db, p.id, latest, {"kind": "screening", "start_utc": start.isot + "Z", "duration_hours": hours, "step_s": 30,
                                          "threshold_km": threshold_km}, user.id)
                n = run_pending_sync()
                print(f"Data is recent (downloaded at {latest.created_at:%Y-%m-%d %H:%M} UTC), so it was kept.")
                print(f"New search from {start.isot[:16]} UTC over the next {hours:g} h on dataset version {latest.version}; {n} job(s) executed.")
                return
        elif not complete:
            sys.exit("not every group could be downloaded; nothing created")
        else:
            p = Project(name="Low Earth Orbit — public catalogue",
                        description="Public GP element sets from CelesTrak: crewed stations, bright satellites and three major debris clouds.",
                        created_by=user.id)
            db.add(p)
            db.flush()
            db.add(ProjectMember(project_id=p.id, user_id=user.id, role="owner"))
            db.commit()
        dv = create_version(db, p.id, user.id, "celestrak-leo.tle", "".join(parts).encode(), dataset_id=dataset_id, dataset_name="CelesTrak LEO selection",
                            origin="provider", provenance={"provider": "CelesTrak", "groups": groups, "fetches": fetched,
                                                           "authority": "public GP data; not operationally authoritative"})
        start = Time(datetime.now(UTC).replace(minute=0, second=0, microsecond=0, tzinfo=None), scale="utc")
        submit(db, p.id, dv, {"kind": "screening", "start_utc": start.isot + "Z", "duration_hours": hours, "step_s": 30,
                              "threshold_km": threshold_km}, user.id)
        n = run_pending_sync()
        print(f"live project {p.id}: dataset version {dv.version} ({dv.stats.get('objects')} objects); {n} jobs executed")
    finally:
        db.close()


def train_ml(activate: bool) -> None:
    from .api.routes_system import train_and_register
    from .db.session import SessionLocal

    mid = train_and_register(None)
    db = SessionLocal()
    try:
        m = db.get(MLModel, mid)
        if activate:
            for o in db.scalars(select(MLModel).where(MLModel.status == "active_experimental")):
                o.status = "experimental"
            m.status = "active_experimental"
            db.commit()
        print(json.dumps({"model_id": mid, "status": m.status, "algorithm": m.params["algorithm"],
                          "test": {k: {kk: v.get(kk) for kk in ("average_precision", "precision", "recall", "brier", "positives", "n")}
                                   for k, v in m.metrics["test"].items()}}, indent=2))
    finally:
        db.close()


def benchmark(sizes: list[int], hours: float, step: float, out: str | None) -> None:
    import psutil

    from .core.parsers import ingest
    from .core.propagation import make_propagator, select_records
    from .core.screening import ScreeningConfig, screen
    from .core.synthetic import demo_catalogue

    epoch = Time("2026-10-10T00:00:00", scale="utc")
    rows = []
    for n in sizes:
        tle = demo_catalogue(epoch, n_background=max(n - 8, 0), n_engineered=4, seed=5)
        res = ingest(tle, reference_time=epoch)
        chosen, _ = select_records(res.records)
        props = {k: make_propagator(v) for k, v in chosen.items()}
        rss0 = psutil.Process().memory_info().rss
        t0 = time.perf_counter()
        r = screen(props, ScreeningConfig(start=epoch, duration_s=hours * 3600, step_s=step, threshold_km=5.0))
        dt = time.perf_counter() - t0
        st = r.stats
        rows.append({"objects": st["objects"], "window_h": hours, "step_s": step, "runtime_s": round(dt, 3), "pairs_total": st["pairs_total"],
                     "pairs_radial_band_overlap": st["pairs_radial_band_overlap"], "pairs_flagged": st["pairs_flagged"], "encounters": st["encounters"],
                     "propagation_evaluations": st["propagation_evaluations"], "peak_traced_memory_mb": round(st["peak_traced_memory_mb"], 1),
                     "rss_delta_mb": round((psutil.Process().memory_info().rss - rss0) / 1e6, 1)})
        print(json.dumps(rows[-1]))
    env = {"python": platform.python_version(), "platform": platform.platform(), "processor": platform.processor(),
           "cpus": psutil.cpu_count(), "memory_gb": round(psutil.virtual_memory().total / 1e9, 1), "measured_utc": datetime.now(UTC).isoformat(),
           "data": "generated sample catalogue (astral.core.synthetic.demo_catalogue, seed 5)", "threshold_km": 5.0}
    doc = {"environment": env, "results": rows}
    if out:
        Path(out).write_text(json.dumps(doc, indent=2))
    try:
        from .db.session import SessionLocal

        db = SessionLocal()
        db.merge(SystemInfo(key="benchmark", value=doc))
        db.commit()
        db.close()
    except Exception as exc:
        print(f"(benchmark not stored in database: {exc})")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="astral")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("migrate")
    a = sub.add_parser("create-admin")
    a.add_argument("--email", required=True)
    a.add_argument("--name", default="Administrator")
    d = sub.add_parser("seed-demo")
    d.add_argument("--email", required=True)
    lv = sub.add_parser("seed-live")
    lv.add_argument("--email", required=True)
    lv.add_argument("--groups", default=",".join(LIVE_GROUPS))
    lv.add_argument("--hours", type=float, default=24.0)
    lv.add_argument("--threshold", type=float, default=2.0)
    lv.add_argument("--project", type=int, help="refresh an existing project instead of creating one")
    t = sub.add_parser("train-ml")
    t.add_argument("--activate", action="store_true")
    sub.add_parser("run-jobs")
    b = sub.add_parser("benchmark")
    b.add_argument("--sizes", default="50,200,800")
    b.add_argument("--hours", type=float, default=24.0)
    b.add_argument("--step", type=float, default=30.0)
    b.add_argument("--out")
    args = ap.parse_args(argv)
    if args.cmd == "migrate":
        migrate()
    elif args.cmd == "create-admin":
        create_admin(args.email, args.name)
    elif args.cmd == "seed-demo":
        seed_demo(args.email)
    elif args.cmd == "seed-live":
        seed_live(args.email, [g.strip() for g in args.groups.split(",") if g.strip()], args.hours, args.threshold, args.project)
    elif args.cmd == "train-ml":
        train_ml(args.activate)
    elif args.cmd == "run-jobs":
        from .services.jobs import run_pending_sync

        print(f"{run_pending_sync()} jobs executed")
    elif args.cmd == "benchmark":
        benchmark([int(x) for x in args.sizes.split(",")], args.hours, args.step, args.out)


if __name__ == "__main__":
    main()

