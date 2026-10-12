"""Synthetic demonstration data. EVERYTHING produced here is SYNTHETIC.

Generated objects use names prefixed ``SMP-`` and catalogue numbers in the
range 90000-99999 (not assigned to real objects in the public catalogue's
5-digit range at the time of writing — still, never mix with real data).
Encounters are engineered by placing a secondary near the primary's
position at a chosen instant and are then *computed* by the normal
screening pipeline; no result value is written by hand.
"""

from __future__ import annotations

import math

import numpy as np
from astropy.time import Time, TimeDelta
from scipy.optimize import minimize_scalar
from sgp4.api import WGS72, Satrec
from sgp4.exporter import export_tle

from .covariance import inertial_to_rtn
from .frames import Frame, convert
from .timeutil import utc_jd_pair

SYNTHETIC_ORIGINATOR = "ASTRAL"


def _sat(catnum: int, epoch: Time, inc, raan, ecc, argp, ma, n_rev_day, bstar=1e-5) -> Satrec:
    s = Satrec()
    epoch_days = (epoch.utc.jd1 - 2433281.5) + epoch.utc.jd2
    s.sgp4init(WGS72, "i", catnum, epoch_days, bstar, 0.0, 0.0, ecc, math.radians(argp), math.radians(inc),
               math.radians(ma), n_rev_day / 720.0 * math.pi, math.radians(raan))
    s.classification = "U"
    s.intldesg = "99999A"
    return s


def _pos(s: Satrec, t: Time) -> np.ndarray:
    jd, fr = utc_jd_pair(t, 0.0)
    e, r, _ = s.sgp4(float(jd[0]), float(fr[0]))
    return np.array(r) if e == 0 else np.full(3, np.nan)


def _tle(s: Satrec, name: str) -> str:
    l1, l2 = export_tle(s)
    return f"{name}\n{l1}\n{l2}\n"


def demo_catalogue(epoch: Time, n_background: int = 40, n_engineered: int = 6, seed: int = 7) -> str:
    """Return TLE text for a synthetic catalogue with engineered near-encounters."""
    rng = np.random.default_rng(seed)
    out = []
    cat = 90001
    primaries = []
    for k in range(n_engineered):
        inc = float(rng.uniform(45, 99))
        raan = float(rng.uniform(0, 360))
        n = float(rng.uniform(14.2, 15.4))
        s = _sat(cat, epoch, inc, raan, 0.0005 + 0.001 * rng.random(), float(rng.uniform(0, 360)), float(rng.uniform(0, 360)), n)
        primaries.append((cat, s, inc, raan, n))
        out.append(_tle(s, f"SMP-A{k + 1:02d}"))
        cat += 1
    for k, (_cat, ps, inc, _raan, n) in enumerate(primaries):
        t_star = epoch + TimeDelta(float(rng.uniform(4, 60)) * 3600.0, format="sec")
        target = _pos(ps, t_star)
        d_inc = float(rng.uniform(5, 60)) * (1 if rng.random() < 0.5 else -1)
        inc2 = min(max(inc + d_inc, 1.0), 179.0)
        best = None
        for raan2 in np.linspace(0, 360, 73)[:-1]:
            s2 = _sat(cat, epoch, inc2, raan2, 0.0006, 0.0, 0.0, n)
            # choose mean anomaly that minimises distance to target at t_star
            def dist(ma: float, raan2=raan2) -> float:
                s3 = _sat(cat, epoch, inc2, raan2, 0.0006, 0.0, ma % 360, n)
                return float(np.linalg.norm(_pos(s3, t_star) - target))
            grid = np.linspace(0, 360, 73)
            ds = [dist(m) for m in grid]
            m0 = grid[int(np.nanargmin(ds))]
            res = minimize_scalar(dist, bounds=(m0 - 5, m0 + 5), method="bounded", options={"xatol": 1e-7})
            if best is None or res.fun < best[0]:
                best = (res.fun, raan2, res.x)
        _, raan2, ma2 = best
        # refine RAAN locally as well
        def dist2(x):
            s3 = _sat(cat, epoch, inc2, x[0] % 360, 0.0006, 0.0, x[1] % 360, n)
            return float(np.linalg.norm(_pos(s3, t_star) - target))
        from scipy.optimize import minimize
        opt = minimize(dist2, [raan2, ma2], method="Nelder-Mead", options={"xatol": 1e-8, "fatol": 1e-6, "maxiter": 2000})
        # deliberately offset by a random along-track amount so that misses span ~0.05-4 km
        offset_deg = float(rng.uniform(0.0005, 0.03))
        s2 = _sat(cat, epoch, inc2, opt.x[0] % 360, 0.0006, 0.0, (opt.x[1] + offset_deg) % 360, n)
        out.append(_tle(s2, f"SMP-B{k + 1:02d}"))
        cat += 1
    for k in range(n_background):
        inc = float(rng.uniform(0, 100))
        n = float(rng.uniform(13.0, 15.6))
        s = _sat(cat, epoch, inc, float(rng.uniform(0, 360)), float(rng.uniform(0.0001, 0.02)), float(rng.uniform(0, 360)),
                 float(rng.uniform(0, 360)), n)
        out.append(_tle(s, f"SMP-C{k + 1:02d}"))
        cat += 1
    return "".join(out)


def _fmt_cov_rtn_m(c_km: np.ndarray) -> list[str]:
    from .parsers.cdm import COV_KEYS

    vals = []
    for i in range(6):
        for j in range(i + 1):
            vals.append(c_km[i, j] * 1e6)
    unit = lambda key: "[m**2]" if "DOT" not in key else ("[m**2/s**2]" if key.count("DOT") == 2 else "[m**2/s]")  # noqa: E731
    return [f"{k:<20}= {v: .6e} {unit(k)}" for k, v in zip(COV_KEYS, vals)]


def synthetic_cdm(r1, v1, r2, v2, tca: Time, frame: Frame, sigma1_m=(80.0, 400.0, 40.0), sigma2_m=(150.0, 900.0, 80.0),
                  msg_id: str = "SMP-0001", ids=("90001", "90007"), names=("SMP-A01", "SMP-B01")) -> str:
    """Build a CDM (KVN) for a computed encounter with *assumed* diagonal RTN covariances.

    The covariance values are assumptions chosen for demonstration and are
    declared as such in COMMENT lines. The originator Pc field is left out so
    that nothing in the file looks like an authoritative risk estimate.
    """
    tca_s = Time(tca.utc, precision=3).isot
    rg, vg = convert(np.vstack([r1, r2]), np.vstack([v1, v2]), frame, Frame.GCRF, Time([tca, tca]))
    dr = rg[1] - rg[0]
    dv = vg[1] - vg[0]
    from .frames import rtn_basis
    b = rtn_basis(rg[0], vg[0])
    rel_p, rel_v = b @ dr * 1000.0, b @ dv * 1000.0
    lines = [
        "CCSDS_CDM_VERS = 1.0",
        "COMMENT Sample message generated by ASTRAL for covariance-based assessment. Not an operational product.",
        "COMMENT Covariances are assumed diagonal RTN values.",
        f"CREATION_DATE = {Time.now().utc.isot[:19]}",
        f"ORIGINATOR = {SYNTHETIC_ORIGINATOR}",
        "MESSAGE_FOR = ANALYST",
        f"MESSAGE_ID = {msg_id}",
        f"TCA = {tca_s}",
        f"MISS_DISTANCE = {np.linalg.norm(dr) * 1000:.3f} [m]",
        f"RELATIVE_SPEED = {np.linalg.norm(dv) * 1000:.3f} [m/s]",
        f"RELATIVE_POSITION_R = {rel_p[0]:.3f} [m]",
        f"RELATIVE_POSITION_T = {rel_p[1]:.3f} [m]",
        f"RELATIVE_POSITION_N = {rel_p[2]:.3f} [m]",
        f"RELATIVE_VELOCITY_R = {rel_v[0]:.3f} [m/s]",
        f"RELATIVE_VELOCITY_T = {rel_v[1]:.3f} [m/s]",
        f"RELATIVE_VELOCITY_N = {rel_v[2]:.3f} [m/s]",
    ]
    for role, oid, name, r, v, sig in (("OBJECT1", ids[0], names[0], rg[0], vg[0], sigma1_m), ("OBJECT2", ids[1], names[1], rg[1], vg[1], sigma2_m)):
        c = np.zeros((6, 6))
        c[0, 0], c[1, 1], c[2, 2] = (np.asarray(sig) / 1000.0) ** 2
        c[3, 3], c[4, 4], c[5, 5] = (np.asarray(sig) / 1000.0 * 1e-3) ** 2
        lines += [
            f"OBJECT = {role}",
            f"OBJECT_DESIGNATOR = {oid}",
            "CATALOG_NAME = ASTRAL-SAMPLE",
            f"OBJECT_NAME = {name}",
            "INTERNATIONAL_DESIGNATOR = 9999-999A",
            "EPHEMERIS_NAME = NONE",
            "COVARIANCE_METHOD = DEFAULT",
            "MANEUVERABLE = N/A",
            "REF_FRAME = GCRF",
            f"X = {r[0]:.6f} [km]", f"Y = {r[1]:.6f} [km]", f"Z = {r[2]:.6f} [km]",
            f"X_DOT = {v[0]:.9f} [km/s]", f"Y_DOT = {v[1]:.9f} [km/s]", f"Z_DOT = {v[2]:.9f} [km/s]",
        ]
        lines += _fmt_cov_rtn_m(c)
    return "\n".join(lines) + "\n"


__all__ = ["demo_catalogue", "synthetic_cdm", "SYNTHETIC_ORIGINATOR", "inertial_to_rtn"]
