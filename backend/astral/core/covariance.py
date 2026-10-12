"""Covariance validation and transformation.

A covariance is accepted for probability calculations only if it is finite,
symmetric to a relative tolerance, and positive semidefinite to a tolerance
scaled by its largest eigenvalue. Matrices that fail are *never* repaired
automatically: the finding includes the nearest-PSD suggestion so an analyst
can decide.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .findings import Finding, Severity
from .frames import rtn_basis

SYMMETRY_RTOL = 1e-9
# Eigenvalues below -PSD_RTOL * max_eig mark the matrix as not PSD. 1e-10 is
# well above float64 round-off for a well-scaled 6x6 matrix (≈1e-15 relative)
# but far below any physically meaningful variance ratio.
PSD_RTOL = 1e-10


@dataclass
class CovarianceCheck:
    valid: bool
    findings: list[Finding] = field(default_factory=list)
    eigenvalues: list[float] = field(default_factory=list)
    condition_number: float | None = None


def lower_triangle_to_matrix(values: list[float], n: int = 6) -> np.ndarray:
    """CCSDS lower-triangular row order (C11, C21, C22, C31, ...) -> full matrix."""
    expected = n * (n + 1) // 2
    if len(values) != expected:
        raise ValueError(f"expected {expected} lower-triangular values, got {len(values)}")
    m = np.zeros((n, n))
    k = 0
    for i in range(n):
        for j in range(i + 1):
            m[i, j] = m[j, i] = values[k]
            k += 1
    return m


def validate(matrix: np.ndarray, ref: str | None = None) -> CovarianceCheck:
    m = np.asarray(matrix, dtype=float)
    out: list[Finding] = []
    if m.ndim != 2 or m.shape[0] != m.shape[1] or m.shape[0] not in (3, 6):
        return CovarianceCheck(False, [Finding(Severity.ERROR, "COV_SHAPE", f"covariance must be 3x3 or 6x6, got {m.shape}", ref)])
    if not np.all(np.isfinite(m)):
        return CovarianceCheck(False, [Finding(Severity.ERROR, "COV_NONFINITE", "covariance contains NaN or infinite values", ref)])
    scale = np.max(np.abs(m)) or 1.0
    asym = np.max(np.abs(m - m.T)) / scale
    if asym > SYMMETRY_RTOL:
        out.append(Finding(Severity.ERROR, "COV_ASYMMETRIC", f"covariance asymmetric (max relative difference {asym:.2e})", ref,
                           suggestion="Symmetrise as (C + C^T)/2 only if the source confirms a transcription error."))
    diag = np.diag(m)
    if np.any(diag <= 0):
        out.append(Finding(Severity.ERROR, "COV_NONPOSITIVE_VARIANCE", "covariance has zero or negative variances on the diagonal", ref))
    sym = 0.5 * (m + m.T)
    eig = np.linalg.eigvalsh(sym)
    emax = float(np.max(eig))
    if emax <= 0:
        out.append(Finding(Severity.ERROR, "COV_NOT_PSD", "covariance has no positive eigenvalue", ref))
        return CovarianceCheck(False, out, eig.tolist(), None)
    if float(np.min(eig)) < -PSD_RTOL * emax:
        out.append(Finding(Severity.ERROR, "COV_NOT_PSD", f"covariance not positive semidefinite (min eigenvalue {np.min(eig):.3e}, max {emax:.3e})", ref,
                           suggestion="Nearest-PSD projection (eigenvalue clipping) is available as an explicit, recorded transformation."))
    cond = float(emax / max(float(np.min(np.abs(eig))), np.finfo(float).tiny))
    if cond > 1e12:
        out.append(Finding(Severity.WARNING, "COV_ILL_CONDITIONED", f"covariance condition number {cond:.2e}; numerical results may be unreliable", ref))
    for i in range(m.shape[0]):
        for j in range(i):
            if diag[i] > 0 and diag[j] > 0:
                rho = sym[i, j] / np.sqrt(diag[i] * diag[j])
                if abs(rho) > 1 + 1e-9:
                    out.append(Finding(Severity.ERROR, "COV_CORRELATION", f"|correlation| > 1 between elements {i},{j}", ref))
    valid = not any(f.severity is Severity.ERROR for f in out)
    return CovarianceCheck(valid, out, eig.tolist(), cond)


def nearest_psd(matrix: np.ndarray) -> np.ndarray:
    """Eigenvalue-clipping projection. Only ever applied after explicit approval."""
    sym = 0.5 * (matrix + matrix.T)
    w, v = np.linalg.eigh(sym)
    w = np.clip(w, 0.0, None)
    return (v * w) @ v.T


def rtn_to_inertial(cov_rtn: np.ndarray, r: np.ndarray, v: np.ndarray) -> np.ndarray:
    """Rotate a 3x3 or 6x6 RTN covariance into the inertial frame of (r, v).

    The velocity block is rotated with the same instantaneous rotation; the
    RTN frame's angular rate is neglected, which is the convention used for
    CDM covariances when forming conjunction-plane covariances at TCA.
    """
    b = rtn_basis(r, v)  # rows = R,T,N in inertial coordinates
    n = cov_rtn.shape[0]
    rot = np.zeros((n, n))
    rot[:3, :3] = b.T
    if n == 6:
        rot[3:, 3:] = b.T
    return rot @ cov_rtn @ rot.T


def inertial_to_rtn(cov: np.ndarray, r: np.ndarray, v: np.ndarray) -> np.ndarray:
    b = rtn_basis(r, v)
    n = cov.shape[0]
    rot = np.zeros((n, n))
    rot[:3, :3] = b
    if n == 6:
        rot[3:, 3:] = b
    return rot @ cov @ rot.T


def sigma_ellipse(cov2: np.ndarray, k: float = 1.0) -> tuple[float, float, float]:
    """Semi-axes (a >= b) and orientation (rad) of the k-sigma ellipse of a 2x2 covariance."""
    w, v = np.linalg.eigh(0.5 * (cov2 + cov2.T))
    order = np.argsort(w)[::-1]
    w, v = w[order], v[:, order]
    a, b = k * np.sqrt(max(w[0], 0.0)), k * np.sqrt(max(w[1], 0.0))
    angle = float(np.arctan2(v[1, 0], v[0, 0]))
    return float(a), float(b), angle
