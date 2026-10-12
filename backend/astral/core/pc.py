"""Probability of collision (Pc) — short-term encounter, 2D formulation.

Method (Foster & Estes 1992; Chan 2008; Alfano 2005)
------------------------------------------------------
Assumptions, all of which are checked or reported:
  * rectilinear relative motion during the encounter,
  * position uncertainty constant over the encounter, Gaussian,
  * primary and secondary errors uncorrelated (combined C = C1 + C2),
  * both objects are spheres; their radii sum to the hard-body radius HBR.

The combined 3x3 position covariance is projected onto the encounter plane
(perpendicular to the relative velocity). Rotating to the principal axes of
the projected covariance (the HBR disc is rotation-invariant) gives

    Pc = ∫_{-R}^{R} N(x; mx, σx) · ½[erf((√(R²-x²) - my)/(√2 σy))
                                       - erf((-√(R²-x²) - my)/(√2 σy))] dx

which is evaluated with adaptive Gauss–Kronrod quadrature (QUADPACK via
scipy). Results are verified against closed forms (isotropic covariance:
non-central chi-square, independent implementation in scipy.stats), against
brute-force 2D integration and against Monte Carlo sampling.

Pc is **never** computed without both covariances and an explicit HBR. The
caller receives ``INSUFFICIENT_DATA_FOR_PC`` with the missing inputs listed.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from enum import Enum

import numpy as np
from scipy import integrate, special

from .covariance import validate
from .encounter import encounter_frame


class PcStatus(str, Enum):
    COMPUTED = "COMPUTED"
    INSUFFICIENT_DATA_FOR_PC = "INSUFFICIENT_DATA_FOR_PC"
    INVALID_COVARIANCE = "INVALID_COVARIANCE"
    NUMERICAL_FAILURE = "NUMERICAL_FAILURE"
    NOT_APPLICABLE = "NOT_APPLICABLE"


@dataclass
class PcResult:
    status: PcStatus
    value: float | None = None
    method: str | None = None
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "status": self.status.value,
            "value": self.value,
            "method": self.method,
            "reasons": self.reasons,
            "warnings": self.warnings,
            "details": self.details,
        }


FOSTER_METHOD = "2D Foster/Alfano erf-quadrature (rectilinear, static Gaussian covariance)"
# Heuristic applicability thresholds (not a validated criterion; see
# SCIENTIFIC_METHODS.md). They raise warnings, never change the number.
LOW_REL_SPEED_KM_S = 0.5
LONG_ENCOUNTER_S = 300.0


def insufficient(reasons: list[str]) -> PcResult:
    return PcResult(PcStatus.INSUFFICIENT_DATA_FOR_PC, None, None, reasons)


def pc_2d_principal(mx: float, my: float, sx: float, sy: float, R: float, notes: list[str] | None = None) -> tuple[float, float]:
    """Pc for a disc of radius R centred at the origin, Gaussian centred at (mx, my)
    with independent standard deviations sx, sy. Returns (pc, abs_error_estimate).
    QUADPACK warnings are captured into ``notes`` instead of being printed."""
    s2y = np.sqrt(2.0) * sy
    norm = 1.0 / (np.sqrt(2.0 * np.pi) * sx)

    def f(x: float) -> float:
        h = np.sqrt(max(R * R - x * x, 0.0))
        gy = 0.5 * (special.erf((h - my) / s2y) - special.erf((-h - my) / s2y))
        return norm * np.exp(-((x - mx) ** 2) / (2 * sx * sx)) * gy

    pts = [p for p in (mx, mx - 3 * sx, mx + 3 * sx) if -R < p < R]
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", integrate.IntegrationWarning)
        val, err = integrate.quad(f, -R, R, points=pts or None, epsabs=0.0, epsrel=1e-9, limit=400)
    if notes is not None:
        for w in caught:
            if issubclass(w.category, integrate.IntegrationWarning):
                notes.append("quadrature: " + str(w.message).split(".")[0])
    return float(val), float(err)


def project(dr: np.ndarray, dv: np.ndarray, c3: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    ef = encounter_frame(dr, dv)
    p = ef[:2]
    return ef, p @ c3 @ p.T, p @ dr


def foster_2d(r1, v1, cov1, r2, v2, cov2, hbr_km: float | None) -> PcResult:
    """Pc from inertial states and inertial covariances (3x3 or 6x6, km units)."""
    reasons = []
    if cov1 is None:
        reasons.append("primary covariance unavailable")
    if cov2 is None:
        reasons.append("secondary covariance unavailable")
    if hbr_km is None or not np.isfinite(hbr_km) or hbr_km <= 0:
        reasons.append("hard-body radius not specified")
    if reasons:
        return insufficient(reasons)
    c1 = np.asarray(cov1, float)[:3, :3]
    c2 = np.asarray(cov2, float)[:3, :3]
    for name, c in (("primary", c1), ("secondary", c2)):
        chk = validate(c)
        if not chk.valid:
            return PcResult(PcStatus.INVALID_COVARIANCE, None, FOSTER_METHOD, [f"{name}: {f.message}" for f in chk.findings])
    dr = np.asarray(r2, float) - np.asarray(r1, float)
    dv = np.asarray(v2, float) - np.asarray(v1, float)
    speed = float(np.linalg.norm(dv))
    if speed <= 0:
        return PcResult(PcStatus.NOT_APPLICABLE, None, FOSTER_METHOD, ["zero relative velocity: 2D method undefined"])
    c = c1 + c2
    ef, cp, m = project(dr, dv, c)
    w, vecs = np.linalg.eigh(cp)
    if np.min(w) <= 0:
        return PcResult(PcStatus.NUMERICAL_FAILURE, None, FOSTER_METHOD, ["projected covariance is singular"])
    mm = vecs.T @ m
    sx, sy = np.sqrt(w)
    notes: list[str] = []
    pc, err = pc_2d_principal(float(mm[0]), float(mm[1]), float(sx), float(sy), float(hbr_km), notes)
    warns = list(dict.fromkeys(notes))
    sz = float(np.sqrt(ef[2] @ c @ ef[2]))
    t_enc = 2 * 5 * sz / speed
    if speed < LOW_REL_SPEED_KM_S:
        warns.append(f"relative speed {speed:.3f} km/s is low; rectilinear-motion assumption may not hold")
    if t_enc > LONG_ENCOUNTER_S:
        warns.append(f"estimated encounter duration {t_enc:.0f} s exceeds {LONG_ENCOUNTER_S:.0f} s; static-covariance assumption questionable")
    if not np.isfinite(pc) or pc < -1e-15 or pc > 1 + 1e-12:
        return PcResult(PcStatus.NUMERICAL_FAILURE, None, FOSTER_METHOD, [f"quadrature returned {pc}"])
    if pc == 0.0:
        warns.append("Pc below the float64 range (< 1e-300); integrand underflows. Reported as 0 meaning 'numerically negligible', not 'impossible'.")
    elif err > max(1e-6 * abs(pc), 1e-300):
        warns.append(f"quadrature error estimate {err:.2e} is large relative to Pc")
    return PcResult(
        PcStatus.COMPUTED,
        float(min(max(pc, 0.0), 1.0)),
        FOSTER_METHOD,
        [],
        warns,
        {
            "hbr_km": hbr_km,
            "miss_in_plane_km": m.tolist(),
            "projected_cov_km2": cp.tolist(),
            "sigma_major_km": float(max(sx, sy)),
            "sigma_minor_km": float(min(sx, sy)),
            "sigma_along_relvel_km": sz,
            "encounter_duration_est_s": t_enc,
            "quadrature_abs_error": err,
            "combined_cov_assumption": "C = C1 + C2 (uncorrelated errors)",
        },
    )


def monte_carlo_rectilinear(dr, dv, c3_combined, hbr_km: float, n: int = 1_000_000, seed: int = 0) -> dict:
    """Cross-check: sample relative-position errors, propagate rectilinearly,
    count trajectories whose closest approach is inside the HBR sphere.
    Shares the 2D method's motion assumptions; it checks the integration, not
    the physics. Returns value with a 95% Wilson interval."""
    rng = np.random.default_rng(seed)
    dr = np.asarray(dr, float)
    dv = np.asarray(dv, float)
    z = dv / np.linalg.norm(dv)
    samples = rng.multivariate_normal(dr, np.asarray(c3_combined, float)[:3, :3], size=n, method="cholesky")
    perp = samples - np.outer(samples @ z, z)
    hits = int(np.sum(np.einsum("ij,ij->i", perp, perp) < hbr_km * hbr_km))
    p = hits / n
    zq = 1.959963984540054
    denom = 1 + zq * zq / n
    centre = (p + zq * zq / (2 * n)) / denom
    half = zq * np.sqrt(p * (1 - p) / n + zq * zq / (4 * n * n)) / denom
    return {"value": p, "hits": hits, "samples": n, "seed": seed, "ci95": [max(centre - half, 0.0), min(centre + half, 1.0)],
            "method": "Monte Carlo, rectilinear relative motion"}
