import astropy.units as u
import numpy as np
import pytest
from astropy.time import Time

from astral.core.covariance import inertial_to_rtn, lower_triangle_to_matrix, nearest_psd, rtn_to_inertial, sigma_ellipse, validate
from astral.core.encounter import geometry
from astral.core.frames import Frame
from astral.core.maneuver import ManeuverSpec, simulate
from astral.core.propagation import J2Propagator


def test_lower_triangle_order():
    m = lower_triangle_to_matrix([1, 2, 3, 4, 5, 6], 3)
    assert m.tolist() == [[1, 2, 4], [2, 3, 5], [4, 5, 6]]
    with pytest.raises(ValueError):
        lower_triangle_to_matrix([1, 2], 3)


def test_validate_flags():
    assert validate(np.eye(6)).valid
    a = np.eye(3)
    a[0, 1] = 0.5
    assert "COV_ASYMMETRIC" in {f.code for f in validate(a).findings}
    b = np.array([[1, 2, 0], [2, 1, 0], [0, 0, 1.0]])
    chk = validate(b)
    assert not chk.valid and "COV_NOT_PSD" in {f.code for f in chk.findings}
    assert np.min(np.linalg.eigvalsh(nearest_psd(b))) >= -1e-12
    assert not validate(np.full((3, 3), np.nan)).valid
    assert not validate(np.eye(4)).valid


def test_rtn_round_trip_and_trace():
    r = np.array([7000.0, 1200.0, -300.0])
    v = np.array([-1.0, 7.2, 2.0])
    c = np.diag([1.0, 9.0, 0.25, 1e-6, 1e-6, 1e-6])
    ci = rtn_to_inertial(c, r, v)
    assert np.isclose(np.trace(ci), np.trace(c))
    assert np.allclose(inertial_to_rtn(ci, r, v), c, atol=1e-12)


def test_sigma_ellipse():
    a, b, ang = sigma_ellipse(np.diag([4.0, 1.0]))
    assert (a, b) == (2.0, 1.0) and abs(np.sin(ang)) < 1e-12


def test_geometry_basic():
    g = geometry(np.array([7000.0, 0, 0]), np.array([0, 7.5, 0]), np.array([7000.0, 0, 1.0]), np.array([0, 0, 7.5]))
    assert g.miss_km == pytest.approx(1.0)
    assert g.rel_speed_km_s == pytest.approx(7.5 * np.sqrt(2))
    assert g.approach_angle_deg == pytest.approx(90.0)
    assert np.allclose(g.rel_pos_rtn_km, [0, 0, 1.0])
    assert np.allclose(g.encounter_plane_basis @ g.encounter_plane_basis.T, np.eye(3), atol=1e-12)


def test_maneuver_simulation_is_labelled_and_changes_miss():
    t0 = Time("2026-01-01T00:00:00", scale="utc")
    p = J2Propagator("P", t0, np.array([7000.0, 0, 0]), np.array([0, 7.546, 0]), Frame.GCRF)
    # secondary meets primary after ~1/4 orbit in a polar plane
    pr = p.propagate(t0, np.array([1500.0]))
    q = J2Propagator("Q", t0 + 1500 * u.s, pr.r_km[0] + [0.05, 0, 0], np.array([0, 0, 7.546]), Frame.GCRF)
    tca = t0 + 1500 * u.s
    res = simulate(p, q, tca, ManeuverSpec(burn_time=t0 + 100 * u.s, dv_rtn_m_s=(0, 0.2, 0)))
    d = res.to_dict()
    assert d["label"].startswith("SIMULATION ONLY")
    assert d["baseline"]["miss_km"] < 0.2
    assert d["alternative"]["miss_km"] > d["baseline"]["miss_km"]
    assert any("broader consequences unassessed" in w for w in d["warnings"])
    assert "recommend" not in str(d).lower()
