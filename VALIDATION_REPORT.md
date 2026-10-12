# Validation report

Build of 2026-10-11/12 (ASTRAL 0.1.0). Everything below was **executed** in this build unless marked otherwise. Host: Intel Core i5-11260H (6 cores/12 threads, 2.6 GHz), 16 GB RAM, Windows 11, Python 3.11.9, Node 24.

## 1. Automated tests (executed)

| Suite | Command | Result |
|---|---|---|
| Backend reference (scientific) | `pytest tests/reference` | 56 passed |
| Backend unit | `pytest tests/unit` | 21 passed |
| Backend integration (HTTP API end-to-end) | `pytest tests/integration` | 4 passed |
| Backend security | `pytest tests/security` | 13 passed |
| Backend ML verification | `pytest tests/ml` | 8 passed |
| **Backend total** | `python -m pytest -q` | **102 passed, 0 failed, 0 skipped** |
| Frontend unit | `npm test` | 7 passed |
| Frontend typecheck / lint / build | `npm run typecheck`, `npm run lint`, `npm run build` | clean |
| Backend lint | `ruff check astral tests` | clean |
| Dependency audit | `pip-audit -r requirements.lock.txt`; `npm audit --omit=dev` | no known vulnerabilities **after** upgrading starlette 0.46→1.7 (FastAPI 0.143), pytest 8→9, react-router 6→7 |

The CI workflow (`.github/workflows/ci.yml`) is written but has **not been run** on a CI service from this environment.

## 2. Scientific reference comparisons

| Test | Reference (independent of ASTRAL's implementation) | Tolerance & rationale | Result |
|---|---|---|---|
| SGP4 | Vallado et al. 2006 (AIAA 2006-6753) `tcppver.out`, 23 element sets, all time steps | 1e-6 km, 1e-9 km/s: reference printed to 1e-8 km; residuals arise only from float ordering | Pass. The 3 deliberately malformed sets (33333–33335) are rejected with `TLE_CHECKSUM`, as intended |
| TEME→ITRF | Vallado 2006 worked example (2004-04-06) | 1 m / 1 mm/s: IAU 2006/2000A vs IAU-76/FK5 and different EOP source | Pass; observed 0.28 m |
| Interpolated TEME→GCRF | Direct astropy at 37 off-knot instants over 5 days | 1 mm | Pass |
| Frame round trips, frame-bias magnitude, RTN orthonormality | Analytic | 1e-9 km | Pass |
| Time scales | TAI−UTC = 37 s (IERS Bulletin C), GPS = TAI−19 s, TT = TAI+32.184 s, DOY form | 1 µs | Pass |
| Pc, zero miss, isotropic | Closed form 1 − exp(−R²/2σ²) | rel 1e-8 | Pass (4 cases) |
| Pc, offset, isotropic | Non-central χ² CDF (scipy.stats) | rel 1e-6; 1e-5 for Pc ≈ 1e-26 | Pass (6 cases) |
| Pc, anisotropic | Brute-force 2D `dblquad` | rel 1e-7 | Pass (3 cases) |
| Pc, correlated 3D projection | Monte Carlo 2×10⁶ samples | 3.29σ binomial | Pass |
| Screening completeness | Brute-force 1 s sampling of every pair + closed-form rectilinear refinement | every minimum found; TCA ≤ 10 ms, miss ≤ 10 m | Pass |
| Refined TCA stationarity | Range rate at TCA | < 1e-4 km/s | Pass |
| Hermite interpolation | Analytic circular orbit | ≤ theoretical bound r(nh)⁴/384 | Pass (error equals the bound: 3.19e-4 km) |
| J2 integrator | Energy integral; secular RAAN rate −1.5nJ2(R/p)²cos i | 1e-9 relative; 1 % | Pass |

**Not obtained:** NASA CARA published Pc test cases (`nasa/CARA_Analysis_Tools`). Network access to GitHub was blocked in this build environment, so no comparison against CARA's Pc2D implementation was made. This is the most important open verification item (ROADMAP R1).

## 3. End-to-end runs (executed)

* Local profile (SQLite, in-process worker): synthetic demo seeded; screening, CDM re-assessment (Pc + Monte Carlo), scenario simulation, PDF/CSV/JSON reports, OEM/CDM export all exercised through the browser UI and API.
* Docker Compose (PostgreSQL 16, API, external worker): image built; migrations ran; health checks green; external worker and CLI processed jobs concurrently without double execution (`SELECT … FOR UPDATE SKIP LOCKED`); audit events recorded.

## 4. Performance (executed, synthetic catalogue, 24 h window, 30 s step, 5 km threshold)

| Objects | Runtime | Pairs | Radial-band overlap | Flagged pairs | Encounters | Peak traced memory |
|---|---|---|---|---|---|---|
| 50 | 1.19 s | 1,225 | 781 | 1 | 1 | 14 MB |
| 200 | 3.49 s | 19,900 | 13,201 | 2 | 1 | 56 MB |
| 800 | 5.96 s | 319,600 | 214,562 | 55 | 23 | 224 MB |
| 2,000 | 11.64 s | 1,999,000 | 1,344,002 | 294 | 150 | 559 MB |

Raw data: `docs/benchmark-results.json`; reproduce with `python -m astral.cli benchmark --sizes 50,200,800,2000`. Inside the Compose worker (2-CPU limit), a 76-object, 72 h job took 23 s. Memory grows as N × steps (the full state grid is held); **a full public catalogue (~30k objects) has not been run** and would need grid chunking (ROADMAP R5). Results on synthetic data do not establish performance on real catalogues.

Performance defects found and fixed during validation: the first proximity bound flagged 10,937 pairs at 800 objects (78.5 s), and the tight linear+curvature bound brought this to 5.96 s with identical encounters. The manoeuvre simulation took 73.6 s (astropy frame transforms + J2 re-integration); interpolated rotations and dense output brought it to 6.2 s.

### Real public data (executed 2026-10-12)

CelesTrak GP groups `stations`, `visual`, `iridium-33-debris`, `cosmos-2251-debris`, `fengyun-1c-debris` (2,850 element sets, 2,847 objects, epochs within days of the run): 24 h screen, 30 s step, 2 km threshold → **147 encounters**, job runtime 57 s on the local profile. A 5 km threshold gave 915 encounters in 55 s. These are TLE-based geometric results (no Pc).

## 5. Known limitations and unresolved issues

* No comparison with NASA CARA or any operational Pc tool (see §2).
* CCSDS standard editions are recorded from memory and are **unverified** (DATA_FORMATS.md).
* Space-Track provider is implemented per documentation but **never exercised** (no credentials).
* OIDC/SSO is a documented path, not implemented.
* No covariance propagation; Pc only at CDM-supplied TCA.
* The ML model is trained only on synthetic data; it has no demonstrated real-world validity.
* Rate limiting is per-process (not shared across replicas).

## 6. Classification of capabilities

* **Verified functionality (research grade):** parsing/validation, SGP4 invocation, frame/time conversions, screening completeness on test data, 2D Pc numerics, reports, security controls listed in SECURITY.md.
* **Research demonstrations:** manoeuvre comparison, ML prioritisation, synthetic demo data.
* **Operationally qualified:** none.
