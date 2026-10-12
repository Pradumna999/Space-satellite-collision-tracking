# Architecture

A modular monolith with a strict dependency direction: **web → services → core**. The scientific core never imports the web layer and can be used on its own.

```
frontend/ (React 18, TypeScript strict, Vite, three.js via @react-three/fiber, Recharts)
   │  /api/v1 (JSON; cookie session + CSRF, or bearer token)
backend/astral/
   api/        FastAPI routers, auth dependencies, middleware (request id, security headers, rate limit, body limit)
   services/   datasets (ingest → immutable versions), jobs (queue, worker, runners), reports/exports,
               providers (CelesTrak, Space-Track), auth, audit, storage (object store)
   ml/         features, synthetic labelled data, training/evaluation, inference (+ OOD)
   core/       parsers, records, findings, timeutil, frames, propagation, screening,
               encounter, covariance, pc, maneuver, synthetic  (no web dependencies)
   db/         SQLAlchemy 2 models, session; alembic/ migrations
```

## Data flow

1. **Upload** → size/encoding checks → format detection → parser → record-level and dataset-level validation → raw file and normalised snapshot written to the object store with SHA-256 → `DatasetVersion` (immutable) + index rows (`ObjectRecord`, `CovarianceRecord`, `ValidationFinding`) + proposed `Transformation`s.
2. **Review** → versions with errors need explicit approval. Approving a correction creates a **new** version; originals never change.
3. **Job submission** → config validated (pydantic) → quotas → `AnalysisJob` with config hash, snapshot reference, software versions; idempotency key supported.
4. **Worker** claims jobs (`FOR UPDATE SKIP LOCKED` on PostgreSQL) → loads the snapshot and **verifies its hash** → runs screening or CDM assessment → stores encounters, probability records and ML scores (if an active model exists) → heartbeat, progress, cancellation, categorised errors, retries only for transient infrastructure errors, stale-worker recovery.
5. **Investigation** → encounter detail, relative motion (recomputed from the same propagators), 3D positions/trajectories (backend-propagated, decimated), scenarios (synchronous simulation, saved with parameters and algorithm version).
6. **Reports** → PDF/CSV/JSON stored with SHA-256 and verified on download; CCSDS OEM/CDM export validated by re-parsing.

## Key decisions

| Decision | Rationale |
|---|---|
| python-sgp4 (Vallado C++) rather than Orekit for GP elements | Reference implementation of SGP4; verified against the Vallado test set; no JVM/data download. Orekit remains the candidate for high-fidelity numerical propagation (ROADMAP). |
| astropy/ERFA for time and frames | Maintained IAU 2006/2000A implementation, bundled leap-second and EOP tables, no run-time downloads. |
| DB-backed queue, no Redis | Fewer moving parts; adequate for laptop and single-node deployments; SKIP LOCKED for concurrency. |
| Immutable snapshots in the object store | Reproducibility: a rerun references the identical bytes; the hash is checked before use. |
| Pc as a separate, gated step | Geometry is always computed; probability only with sufficient inputs. |
| ML subordinate | Scores stored in their own columns, never in Pc fields; the pipeline works with ML absent. |
| Admins have no implicit project data access | Project-level data isolation; administration ≠ data access. |

## Interfaces

* `core.propagation.Propagator` protocol: `propagate(start, offsets_s) -> PropagationResult(r, v, valid, frame, method, warnings)`.
* `core.screening.screen(propagators, ScreeningConfig, progress, cancelled) -> ScreeningResult`.
* `core.pc.foster_2d(r1, v1, C1, r2, v2, C2, hbr_km) -> PcResult(status, value, method, reasons, warnings, details)`.
* REST API: see [API.md](API.md) and `/api/v1/openapi.json`.
