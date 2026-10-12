"""Frame and time reference tests.

TEME -> ITRF: Vallado et al. (2006), AIAA 2006-6753, worked example
(2004-04-06 07:51:28.386009 UTC). Published ITRF state uses IERS EOP values
from that paper (dUT1 = -0.4399619 s, xp = -0.140682", yp = 0.333309") and the
IAU-76/FK5 model; ASTRAL uses astropy (IAU 2006/2000A, astropy's bundled
IERS series). Tolerance 1 m position / 1 mm/s velocity accounts for the model
and EOP-source differences; the observed difference is ~0.3 m.
"""

import numpy as np
from astropy.time import Time

from astral.core.frames import Frame, convert, rtn_basis
from astral.core.timeutil import parse_epoch, window_contains_leap_second


def test_teme_to_itrf_vallado_example():
    t = Time("2004-04-06T07:51:28.386009", scale="utc")
    r = np.array([[5094.18016210, 6127.64465950, 6380.34453270]])
    v = np.array([[-4.746131487, 0.785818041, 5.531931288]])
    ri, vi = convert(r, v, Frame.TEME, Frame.ITRF, t)
    ref_r = np.array([-1033.47938300, 7901.29527540, 6380.35659580])
    ref_v = np.array([-3.225636520, -2.872451450, 5.531924446])
    assert np.linalg.norm(ri[0] - ref_r) < 1e-3
    assert np.linalg.norm(vi[0] - ref_v) < 1e-6


def test_frame_round_trip():
    t = Time("2026-01-01T00:00:00", scale="utc")
    r = np.array([[7000.0, 100.0, -50.0]])
    v = np.array([[0.1, 7.5, 1.0]])
    for f in (Frame.TEME, Frame.EME2000, Frame.ITRF):
        r2, v2 = convert(*convert(r, v, Frame.GCRF, f, t), f, Frame.GCRF, t)
        assert np.allclose(r2, r, atol=1e-9)
        assert np.allclose(v2, v, atol=1e-12)


def test_eme2000_bias_is_small():
    # IAU 2000 frame bias is ~23 mas: at 7000 km that is < 1 m.
    t = Time("2026-01-01T00:00:00", scale="utc")
    r = np.array([[7000.0, 0.0, 0.0]])
    r2, _ = convert(r, np.zeros((1, 3)) + [[0, 7.5, 0]], Frame.EME2000, Frame.GCRF, t)
    d = np.linalg.norm(r2 - r)
    assert 1e-5 < d < 1e-3


def test_rtn_orthonormal():
    b = rtn_basis(np.array([7000.0, 10, 20]), np.array([0.2, 7.4, 1.1]))
    assert np.allclose(b @ b.T, np.eye(3), atol=1e-14)
    assert np.isclose(np.linalg.det(b), 1.0)


def test_leap_seconds_and_time_systems():
    # TAI-UTC = 37 s since 2017-01-01 (IERS Bulletin C 52).
    t = parse_epoch("2020-06-01T00:00:00", "UTC")
    assert abs((t.tai.jd1 - t.utc.jd1 + t.tai.jd2 - t.utc.jd2) * 86400 - 37.0) < 1e-6
    # GPS = TAI - 19 s exactly.
    g = parse_epoch("2020-06-01T00:00:18", "GPS")
    assert abs((g - t).sec) < 1e-6
    # TT = TAI + 32.184 s.
    tt = parse_epoch("2020-06-01T00:01:09.184", "TT")
    assert abs((tt - t).sec) < 1e-6
    # CCSDS day-of-year form.
    assert abs((parse_epoch("2020-153T00:00:00", "UTC") - t).sec) < 1e-9


def test_leap_second_window_detection():
    a = Time("2016-12-31T12:00:00", scale="utc")
    b = Time("2017-01-01T12:00:00", scale="utc")
    assert window_contains_leap_second(a, b)
    assert not window_contains_leap_second(b, Time("2017-06-01T00:00:00", scale="utc"))


def test_fast_teme_rotation_matches_astropy():
    """Interpolated TEME->GCRF rotation vs direct astropy at off-knot instants."""
    import astropy.units as u
    from astropy.coordinates import GCRS, TEME, CartesianRepresentation

    t = Time("2026-03-01T00:00:00", scale="utc") + np.linspace(0, 5 * 86400, 37) * u.s + 1234.5 * u.s
    rng = np.random.default_rng(0)
    r = rng.normal(size=(37, 3))
    r = 7000.0 * r / np.linalg.norm(r, axis=1, keepdims=True)
    fast, _ = convert(r, np.zeros_like(r), Frame.TEME, Frame.GCRF, t)
    ref = TEME(CartesianRepresentation(r.T * u.km), obstime=t).transform_to(GCRS(obstime=t)).cartesian.xyz.to_value(u.km).T
    assert np.max(np.linalg.norm(fast - ref, axis=1)) < 1e-6  # 1 mm
    back, _ = convert(fast, np.zeros_like(r), Frame.GCRF, Frame.TEME, t)
    assert np.allclose(back, r, atol=1e-9)
