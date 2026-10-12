# Scientific methods

Units: km, km/s, seconds unless stated. Covariances: km², km²/s, km²/s². Time: UTC unless stated.

## 1. Time systems

* Parsing accepts ISO-8601 calendar (`YYYY-MM-DDThh:mm:ss[.f]`) and CCSDS day-of-year (`YYYY-DDDThh:mm:ss[.f]`) forms in UTC, TAI, TT, GPS (TAI − 19 s, exact) and TDB. Conversion uses ERFA via astropy.
* Internal instants are UTC Julian dates split `(jd_day, jd_frac)` (≈1 µs resolution). Analysis windows are UTC-day arithmetic; **a window that contains a leap second is rejected** rather than mis-timed.
* The leap-second table is astropy's bundled table (expires 2027-06-28 in this build). Epochs beyond it are flagged `LEAP_SECOND_TABLE_EXPIRED`. ASTRAL never downloads IERS data at run time.
* Earth-orientation parameters (UT1−UTC, polar motion) come from the bundled IERS table, which ends **2026-08-28** in this build. Beyond it astropy assumes UT1−UTC = 0. This affects only ITRF conversions (≲ 0.9 s of Earth rotation ≈ ≤ 0.5 km for LEO). ITRF inputs beyond the table get `EOP_UNAVAILABLE`; the 3D view says when Earth orientation uses UT1 = UTC.

## 2. Reference frames

TEME (SGP4 output), GCRF, EME2000 (constant IAU 2000 frame bias, `erfa.bp00`), ITRF. TEME↔GCRF uses astropy's IAU 2006/2000A chain evaluated exactly at hourly knots and interpolated element-wise, then re-orthonormalised (SVD polar decomposition); the reference test bounds the interpolation error below 1 mm at 7000 km. TEME's own rotation rate (~1e-11 rad/s) is neglected for velocities (< 1e-7 km/s). ITRF uses astropy directly.

Distances and relative speeds between two objects in the same inertial frame at the same instant are rotation-invariant, so all-TEME catalogues are screened in TEME; mixed catalogues are converted to GCRF.

RTN: R = r/|r|, N = (r×v)/|r×v|, T = N×R. Encounter plane: z along relative velocity, x along the in-plane miss component, y = z×x.

## 3. Propagation

| Input | Method | Notes |
|---|---|---|
| TLE / OMM (SGP4 theory, TEME, UTC) | SGP4/SDP4, python-sgp4 2.24 (Vallado C++), WGS-72, opsmode `i` | No covariance. Public TLE accuracy ~1 km at epoch, growing several km/day. Flagged `TLE_ACCURACY_LIMITED`; stale > 3 days flagged. SGP4-XP rejected. |
| OEM / operator ephemeris | Cubic Hermite between bracketing samples using supplied velocities | Never extrapolates; refuses to interpolate across gaps > 3× median step. Error bound r(nh)⁴/384 (3.2e-4 km for 60 s LEO steps) is verified. |
| Single state (CDM, states CSV/JSON) | Not propagated | Valid only at its epoch; no force model is silently introduced. |
| Scenario comparisons | Two-body + J2 (WGS-84 μ, Rₑ, J2), DOP853 rtol 1e-11 atol 1e-9 km, dense output | J2 about the GCRF z-axis (pole-direction error ≈ 0.4° vs. true-of-date). Verified by the J2 energy integral and the secular RAAN rate. |

Not implemented (and never implied): drag beyond SGP4's B*, solar radiation pressure, third-body perturbations, high-order gravity, covariance propagation. Orekit was evaluated as a candidate engine but not integrated (see ROADMAP.md).

## 4. Conjunction screening

1. Propagate all eligible objects on a uniform grid of step Δt (end point included).
2. **Radial-band filter** (funnel statistic): band = [min|r|, max|r|] ± max|v|·Δt/2; pairs whose bands are further apart than D cannot approach within D because |r₁−r₂| ≥ ||r₁|−|r₂||.
3. **Proximity flagging.** k-d tree candidates within D + v_rel,max·Δt/2 + ½a_max(Δt/2)². Each candidate is then tested with the tight bound: Δr(t_k+τ) = Δr_k + Δv_k τ + e(τ), |e(τ)| ≤ ½ a_max τ², where a_max = 1.01 · 2μ/r_min² bounds the relative acceleration. If the true minimum d* ≤ D occurs at t*, the nearest grid point has |t*−t_k| ≤ Δt/2, so the linear-motion minimum over |τ| ≤ Δt/2 satisfies d_lin ≤ D + ½ a_max (Δt/2)². **No minimum ≤ D is missed while the propagator is valid at t_k.**
4. **Refinement.** For each flagged (pair, t_k), the range-rate function f(t) = Δr·Δv is sub-sampled on [t_{k−1}, t_{k+1}]; sign changes (− → +) are refined with Brent's method (xtol 1e-6 s). A minimum on the window edge is reported as `WINDOW_BOUNDARY`. Duplicates within 1 s are merged.
5. **Step guard.** Δt ≤ P_min/20, so each bracket contains at most one close approach per pair.

An encounter means *geometric* proximity within D. It is not a collision prediction.

## 5. Probability of collision

Short-term encounter, 2D formulation (Foster & Estes 1992; Chan 2008; Alfano 2005). Pc is computed **only** when both objects have validated covariances at TCA and a hard-body radius (HBR) is specified. Otherwise the status is `INSUFFICIENT_DATA_FOR_PC`, with the missing inputs listed.

* RTN covariances are rotated to the inertial frame of each object's state; combined C = C₁ + C₂ (uncorrelated errors assumed); projected on the encounter plane; rotated to principal axes (σx, σy).
* Pc = ∫₋ᴿᴿ N(x; mx, σx) · ½[erf((√(R²−x²) − my)/(√2σy)) − erf((−√(R²−x²) − my)/(√2σy))] dx, evaluated with adaptive Gauss–Kronrod (QUADPACK, epsrel 1e-9). QUADPACK warnings are captured into the result. Values below the float64 range are reported as 0 with an explicit underflow warning; the UI shows "< 1e-300".
* **Heuristic warnings** (not validated criteria; they never change the number): relative speed < 0.5 km/s; estimated encounter duration 10σ_z/v_rel > 300 s.
* Monte Carlo cross-check (rectilinear motion, same assumptions) with a 95 % Wilson interval and a recorded seed.
* "3D" Pc is **not implemented**; the UI control is disabled rather than silently substituting another method.
* Display bands (Pc ≥ 1e-4, 1e-7–1e-4, < 1e-7) are presentation aids, not operational thresholds.

## 6. Covariance validation

Finite; symmetric to 1e-9 relative; positive variances; PSD with min eigenvalue ≥ −1e-10·max; |ρ| ≤ 1; condition number > 1e12 warned. Invalid matrices are never used. The nearest-PSD projection (eigenvalue clipping) is offered as an explicit transformation that creates a new dataset version on approval.

## 7. Manoeuvre comparison (simulation only)

Both objects' states at the burn epoch come from their source propagators. Baseline and alternative are integrated with the same J2 model, so differences are attributable to the impulsive Δv (given in the primary's RTN frame). Reported alongside: model divergence from the source propagator at TCA, propellant (Tsiolkovsky, only if mass and Isp are given), and other encounters of the alternative trajectory within the screening threshold (≤ 500 objects). Uncertainty is not propagated. The result is never labelled safe or recommended.

## 8. Assumptions register

| # | Area | Assumption | Consequence / mitigation |
|---|---|---|---|
| A1 | Orbital data quality | Public TLE/OMM are mean elements with km-level, undocumented errors | Screening/research only; `TLE_ACCURACY_LIMITED`; no Pc |
| A2 | Propagation fidelity | SGP4 as implemented by python-sgp4 is the reference for GP elements | Verified against Vallado (2006) |
| A3 | Force models | Scenario model is two-body + J2 only | Model divergence reported; compare arms, not absolutes |
| A4 | Frames | IAU 2006/2000A (astropy) for TEME/GCRF/ITRF; EME2000 via constant frame bias; ICRF treated as geocentric GCRF axes | Sub-metre differences vs. FK5-based tools (Vallado example: 0.28 m) |
| A5 | Time | Leap-second table valid to 2027-06-28; EOP table to 2026-08-28 | Flags beyond validity; windows across leap seconds rejected |
| A6 | Covariance availability | Only CDM/OEM/states inputs carry covariance; no covariance propagation | Pc only at supplied epochs (CDM TCA) |
| A7 | Covariance correlation | Primary and secondary errors uncorrelated | Stated in every Pc result |
| A8 | Physical dimensions | Objects modelled as spheres; combined HBR supplied by the analyst | Pc not computed without HBR |
| A9 | Numerical tolerances | Brent xtol 1e-6 s; QUADPACK epsrel 1e-9; DOP853 rtol 1e-11/atol 1e-9 km | Tolerances justified in tests |
| A10 | Screening thresholds | D ≤ 200 km, Δt ≤ min(600 s, P_min/20), window ≤ 14 days | Enforced by validation |
| A11 | Relative acceleration bound | a_max = 1.01·2μ/r_min² over sampled radii | J2 and other perturbations < 1 % of central gravity in LEO+ |
| A12 | ML labels | Synthetic labels from an assumed covariance-growth model | Model is experimental; no real-world claim |
| A13 | Operational applicability | None claimed | Readiness statement in UI, reports and docs |
| A14 | Stale data | GP > 3 days, states/ephemerides > 7 days | Flag only; analyst decides |
