# Changelog

## 2.0.0 — 2026-10-12

Second release, prepared for public presentation.

* **Real data:** `seed-live` loads public CelesTrak element sets (stations, bright satellites, Iridium-33, Cosmos-2251 and Fengyun-1C debris; ~2,850 objects) and screens them; `--project` refreshes an existing project and re-runs the search when the data is still recent.
* **Avoidance manoeuvres:** 60 simulated pushes per close approach (5 directions × 4 sizes × 3 timings), a chart of predicted distance against push size, the most efficient options in plain words, and a one-click check against every other object. The no-manoeuvre baseline equals the screening result; burn times already in the past are marked "too late".
* **3D view:** client-side animation of a prioritised subset (250/500/1000 objects) from one request per 3-hour window, with playback at 60×–1200×.
* **Plain language:** new navigation, an "At a glance" summary, "What this shows" notes under every chart, and an in-app "How it works" guide; `WALKTHROUGH.md` with a demo script and Q&A.
* **Fixes:** timestamps from the database are read as UTC; the manoeuvre check now covers every object (previously skipped above 500 objects while the UI implied it had run); the CDM relative-motion view is limited to the validity of its straight-line model; dependency security upgrades.


## 0.1.0 — 2026-10-12

First implementation.

* Scientific core: parsers (TLE, OMM KVN/XML/JSON/CSV, OEM KVN, CDM KVN, astral-states CSV/JSON), validation and dataset-level checks, time systems, frames (fast interpolated TEME↔GCRF), SGP4 / Hermite ephemeris / J2 propagators, screening with a provably conservative proximity bound, encounter geometry, covariance validation, 2D Pc with Monte Carlo cross-check, manoeuvre comparison, synthetic data generator.
* Backend: FastAPI app, SQLAlchemy models and Alembic migration, local and production profiles, Argon2id auth with sessions/CSRF/API tokens, project RBAC, audit log, rate limits and quotas, DB-backed job queue with in-process or external workers, reports (PDF/CSV/JSON), OEM/CDM export, CelesTrak provider (Space-Track unverified), ML lab.
* Frontend: 11 views implementing the "ASTRAL Pairings" design (pairings D Ignition / E Kyoto), 3D environment, analytics with CSV export.
* Deployment: Dockerfile, Docker Compose (PostgreSQL, API, worker), CI workflow.
* Validation fixes during the build: proximity bound tightened (800-object screening 78.5 s → 6.0 s, identical results); manoeuvre simulation 73.6 s → 6.2 s; Pc underflow now reported explicitly; security upgrades (starlette 1.7, pytest 9, react-router 7).
