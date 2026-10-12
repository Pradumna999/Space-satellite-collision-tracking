"""Ephemeris interpolation and numerical-propagator reference tests.

Hermite: an analytic circular two-body orbit is sampled every 60 s and
interpolated at mid-points. Cubic Hermite error bound for a circular orbit
of radius r and angular rate n with step h is r(nh)^4/384 ≈ 2e-5 km here;
tolerance 1e-4 km.

J2 propagator: (a) with the J2 term the specific energy
E = v²/2 - μ/r - μR²J2/(2r³)(3 sin²φ - 1)... (negative sign convention below)
is an exact integral of motion; drift over one day must stay below 1e-9 of
|E|. (b) The analytic secular RAAN rate dΩ/dt = -1.5 n J2 (R/p)² cos i must
be reproduced within 1% over 1 day for a near-circular LEO orbit.
"""

import math

import numpy as np
from astropy.time import Time, TimeDelta

from astral.core.constants import J2_EARTH, MU_EARTH_KM3_S2, R_EARTH_KM
from astral.core.frames import Frame
from astral.core.propagation import EphemerisInterpolator, J2Propagator
from astral.core.records import OrbitalRecord, RecordKind

T0 = Time("2026-01-01T00:00:00", scale="utc")


def _circ(t, r=7000.0):
    n = math.sqrt(MU_EARTH_KM3_S2 / r**3)
    th = n * t
    pos = np.stack([r * np.cos(th), r * np.sin(th), np.zeros_like(th)], axis=1)
    vel = np.stack([-r * n * np.sin(th), r * n * np.cos(th), np.zeros_like(th)], axis=1)
    return pos, vel


def test_hermite_against_analytic_orbit():
    ts = np.arange(0, 7200 + 1, 60.0)
    p, v = _circ(ts)
    rec = OrbitalRecord("X", RecordKind.EPHEMERIS, "TEST", T0, Frame.GCRF, "UTC",
                        ephem_epochs=T0 + TimeDelta(ts, format="sec"), ephem_states=np.hstack([p, v]))
    ip = EphemerisInterpolator(rec)
    q = ts[:-1] + 30.0
    res = ip.propagate(T0, q)
    pe, ve = _circ(q)
    assert res.valid.all()
    n = math.sqrt(MU_EARTH_KM3_S2 / 7000.0**3)
    bound = 7000.0 * (n * 60.0) ** 4 / 384.0
    assert np.max(np.linalg.norm(res.r_km - pe, axis=1)) <= bound * 1.01
    # velocity error bound for the derivative of a cubic Hermite: r n (nh)^3 / (72*sqrt(3)) (conservative /48 used)
    assert np.max(np.linalg.norm(res.v_km_s - ve, axis=1)) <= 7000.0 * n * (n * 60.0) ** 3 / 48.0


def test_hermite_never_extrapolates_or_crosses_gaps():
    ts = np.array([0, 60, 120, 600, 660.0])
    p, v = _circ(ts)
    rec = OrbitalRecord("X", RecordKind.EPHEMERIS, "TEST", T0, Frame.GCRF, "UTC",
                        ephem_epochs=T0 + TimeDelta(ts, format="sec"), ephem_states=np.hstack([p, v]), extra={"gaps_after_index": [2]})
    res = EphemerisInterpolator(rec).propagate(T0, np.array([-10.0, 30.0, 300.0, 630.0, 700.0]))
    assert res.valid.tolist() == [False, True, False, True, False]


def _energy(r, v):
    rn = np.linalg.norm(r)
    sinphi = r[2] / rn
    u = -MU_EARTH_KM3_S2 / rn * (1 - J2_EARTH * (R_EARTH_KM / rn) ** 2 * 0.5 * (3 * sinphi**2 - 1))
    return 0.5 * np.dot(v, v) + u


def test_j2_energy_integral():
    r0 = np.array([7000.0, 0.0, 0.0])
    v0 = np.array([0.0, 6.0, 4.5])
    p = J2Propagator("X", T0, r0, v0, Frame.GCRF)
    res = p.propagate(T0, np.array([0.0, 43200.0, 86400.0]))
    e0 = _energy(r0, v0)
    for k in range(3):
        assert abs(_energy(res.r_km[k], res.v_km_s[k]) - e0) / abs(e0) < 1e-9


def test_j2_secular_raan_rate():
    a, inc = 7000.0, math.radians(51.6)
    vc = math.sqrt(MU_EARTH_KM3_S2 / a)
    r0 = np.array([a, 0.0, 0.0])
    v0 = np.array([0.0, vc * math.cos(inc), vc * math.sin(inc)])
    p = J2Propagator("X", T0, r0, v0, Frame.GCRF)
    days = 1.0
    ts = np.linspace(0, days * 86400, 2001)
    res = p.propagate(T0, ts)
    h = np.cross(res.r_km, res.v_km_s)
    raan = np.unwrap(np.arctan2(h[:, 0], -h[:, 1]))
    rate_num = np.polyfit(ts, raan, 1)[0]
    n = math.sqrt(MU_EARTH_KM3_S2 / a**3)
    rate_ref = -1.5 * n * J2_EARTH * (R_EARTH_KM / a) ** 2 * math.cos(inc)
    assert abs(rate_num - rate_ref) / abs(rate_ref) < 0.01
