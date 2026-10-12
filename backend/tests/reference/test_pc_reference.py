"""Probability-of-collision reference tests.

Independent references (none uses ASTRAL's own quadrature):
1. Isotropic combined covariance, zero miss: Pc = 1 - exp(-R²/(2σ²))  (closed form).
2. Isotropic covariance, miss m: (x²+y²)/σ² is non-central χ² with 2 dof and
   non-centrality m²/σ², so Pc = F_ncx2(R²/σ²; 2, m²/σ²)  (scipy.stats).
3. Anisotropic, correlated: brute-force 2D integration with scipy dblquad.
4. Monte Carlo with fixed seed; reference within its 99.9% binomial interval.

NASA CARA published test cases (CARA_Analysis_Tools) could not be retrieved
from this build environment (network restricted); see VALIDATION_REPORT.md.
"""

import numpy as np
import pytest
from scipy import integrate, stats

from astral.core.pc import PcStatus, foster_2d, monte_carlo_rectilinear, pc_2d_principal


def _states(miss_km: float, speed=10.0):
    r1 = np.array([7000.0, 0.0, 0.0])
    v1 = np.array([0.0, 7.5, 0.0])
    r2 = r1 + np.array([miss_km, 0.0, 0.0])
    v2 = v1 + np.array([0.0, 0.0, speed])
    return r1, v1, r2, v2


@pytest.mark.parametrize("sigma,R", [(0.1, 0.01), (0.2, 0.02), (1.0, 0.005), (0.05, 0.1)])
def test_isotropic_zero_miss_closed_form(sigma, R):
    r1, v1, r2, v2 = _states(0.0)
    c = np.eye(3) * sigma**2 / 2  # split equally between the objects
    res = foster_2d(r1, v1, c, r2, v2, c, R)
    assert res.status is PcStatus.COMPUTED
    ref = -np.expm1(-R * R / (2 * sigma * sigma))
    assert res.value == pytest.approx(ref, rel=1e-8)


@pytest.mark.parametrize("sigma,R,m", [(0.1, 0.01, 0.05), (0.2, 0.02, 0.5), (0.3, 0.015, 1.2), (0.5, 0.02, 4.0), (0.05, 0.1, 0.02)])
def test_isotropic_offset_noncentral_chi2(sigma, R, m):
    r1, v1, r2, v2 = _states(m)
    c = np.eye(3) * sigma**2 / 2
    res = foster_2d(r1, v1, c, r2, v2, c, R)
    ref = stats.ncx2.cdf(R * R / sigma**2, 2, m * m / sigma**2)
    assert res.value == pytest.approx(ref, rel=1e-6)


@pytest.mark.parametrize("sx,sy,rho,mx,my,R", [
    (0.2, 0.05, 0.0, 0.1, 0.02, 0.02),
    (1.0, 0.1, 0.0, 0.5, 0.0, 0.01),
    (0.3, 0.08, 0.0, -0.2, 0.05, 0.03),
])
def test_anisotropic_dblquad(sx, sy, rho, mx, my, R):
    val, _ = pc_2d_principal(mx, my, sx, sy, R)

    def dens(y, x):
        return np.exp(-((x - mx) ** 2) / (2 * sx * sx) - ((y - my) ** 2) / (2 * sy * sy)) / (2 * np.pi * sx * sy)

    ref, _ = integrate.dblquad(dens, -R, R, lambda x: -np.sqrt(R * R - x * x), lambda x: np.sqrt(R * R - x * x), epsabs=0, epsrel=1e-11)
    assert val == pytest.approx(ref, rel=1e-7)


def test_correlated_projection_matches_monte_carlo():
    r1 = np.array([6800.0, 100.0, -20.0])
    v1 = np.array([0.5, 7.4, 1.2])
    r2 = r1 + np.array([0.12, -0.05, 0.03])
    v2 = np.array([-6.0, 1.0, 4.0])
    a = np.array([[0.04, 0.01, 0.0], [0.01, 0.09, 0.02], [0.0, 0.02, 0.02]])
    res = foster_2d(r1, v1, a, r2, v2, a * 0.5, 0.02)
    mc = monte_carlo_rectilinear(r2 - r1, v2 - v1, a * 1.5, 0.02, n=2_000_000, seed=11)
    p = mc["value"]
    half = 3.29 * np.sqrt(p * (1 - p) / mc["samples"])
    assert abs(res.value - p) < half + 1e-9


def test_missing_covariance_never_produces_a_number():
    r1, v1, r2, v2 = _states(0.1)
    res = foster_2d(r1, v1, None, r2, v2, np.eye(3), 0.01)
    assert res.status is PcStatus.INSUFFICIENT_DATA_FOR_PC and res.value is None
    res = foster_2d(r1, v1, np.eye(3), r2, v2, np.eye(3), None)
    assert res.status is PcStatus.INSUFFICIENT_DATA_FOR_PC and res.value is None


def test_invalid_covariance_rejected():
    r1, v1, r2, v2 = _states(0.1)
    bad = np.array([[1.0, 2.0, 0], [2.0, 1.0, 0], [0, 0, 1.0]])  # eigenvalue -1
    res = foster_2d(r1, v1, bad, r2, v2, np.eye(3), 0.01)
    assert res.status is PcStatus.INVALID_COVARIANCE


def test_tiny_probability_relative_accuracy():
    # Far miss: Pc ~ 1e-30; quadrature must keep relative accuracy.
    sigma, R, m = 0.1, 0.01, 1.2
    r1, v1, r2, v2 = _states(m)
    c = np.eye(3) * sigma**2 / 2
    res = foster_2d(r1, v1, c, r2, v2, c, R)
    ref = stats.ncx2.cdf(R * R / sigma**2, 2, m * m / sigma**2)
    assert ref < 1e-25
    assert res.value == pytest.approx(ref, rel=1e-5)
