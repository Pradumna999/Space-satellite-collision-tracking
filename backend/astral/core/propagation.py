"""Propagation engine interface and implementations.

Implementations
---------------
SGP4Propagator         GP mean elements (TLE/OMM) via the ``sgp4`` library
                       (Vallado C++ port, WGS-72 constants, opsmode 'i').
                       Output frame: TEME. No covariance.
EphemerisInterpolator  Operator ephemerides (OEM, etc.). Cubic Hermite
                       interpolation using supplied positions and velocities
                       between bracketing samples. Never extrapolates; never
                       interpolates across a flagged gap.
J2Propagator           Two-body + J2 numerical integration (DOP853). Used only
                       for hypothetical manoeuvre scenarios, where both
                       baseline and alternative trajectories are integrated
                       with the same model.

A single Cartesian state (e.g. from a CDM) is *not* propagated by default:
the CDM states are only valid at TCA, and turning them into a trajectory
would silently introduce a force model the originator did not use.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from importlib.metadata import version as _pkg_version
from typing import Protocol

import numpy as np
from astropy.time import Time
from scipy.integrate import solve_ivp

from .constants import J2_EARTH, MU_EARTH_KM3_S2, R_EARTH_KM
from .frames import Frame
from .parsers.omm import satrec_from_omm
from .parsers.tle import satrec_from_lines
from .records import OrbitalRecord, RecordKind
from .timeutil import offsets_from, utc_jd_pair

SGP4_ERRORS = {
    1: "mean eccentricity outside [0,1) or semi-major axis < 0.95 er",
    2: "mean motion below zero",
    3: "perturbed eccentricity outside [0,1]",
    4: "semi-latus rectum below zero",
    5: "epoch elements are sub-orbital (deprecated code)",
    6: "satellite has decayed",
}


@dataclass
class PropagationResult:
    object_id: str
    frame: Frame
    r_km: np.ndarray  # (N,3)
    v_km_s: np.ndarray  # (N,3)
    valid: np.ndarray  # (N,) bool
    method: str
    warnings: list[str] = field(default_factory=list)
    error_codes: np.ndarray | None = None


class Propagator(Protocol):
    object_id: str
    frame: Frame
    method: str
    epoch: Time

    def propagate(self, start: Time, offsets_s: np.ndarray) -> PropagationResult: ...

    def coverage(self) -> tuple[Time | None, Time | None]: ...


class SGP4Propagator:
    method = f"SGP4 (python-sgp4 {_pkg_version('sgp4')}, WGS-72, opsmode i)"

    def __init__(self, record: OrbitalRecord):
        if record.kind is not RecordKind.GP_ELEMENTS:
            raise ValueError("SGP4 requires GP mean elements")
        if record.tle_line1 and record.tle_line2:
            self.sat = satrec_from_lines(record.tle_line1, record.tle_line2)
        else:
            fields = (record.mean_elements or {}).get("omm_fields")
            if not fields:
                raise ValueError("record has neither TLE lines nor OMM fields")
            self.sat, _ = satrec_from_omm(fields)
        self.object_id = record.object_id
        self.frame = Frame.TEME
        self.epoch = record.epoch
        self.record = record

    def coverage(self) -> tuple[Time | None, Time | None]:
        return None, None  # analytic; validity degrades with age (flagged by caller)

    def propagate(self, start: Time, offsets_s: np.ndarray) -> PropagationResult:
        jd, fr = utc_jd_pair(start, offsets_s)
        e, r, v = self.sat.sgp4_array(jd, fr)
        valid = (e == 0) & np.all(np.isfinite(r), axis=1)
        warnings = []
        for code in sorted(set(int(c) for c in np.unique(e) if c != 0)):
            warnings.append(f"SGP4 error {code}: {SGP4_ERRORS.get(code, 'unknown')}")
        return PropagationResult(self.object_id, self.frame, r, v, valid, self.method, warnings, e)


class EphemerisInterpolator:
    method = "Cubic Hermite interpolation of supplied ephemeris (positions + velocities)"

    def __init__(self, record: OrbitalRecord):
        if record.kind is not RecordKind.EPHEMERIS or record.ephem_epochs is None:
            raise ValueError("ephemeris record required")
        self.object_id = record.object_id
        self.frame = record.frame
        self.epoch = record.epoch
        self.record = record
        self.t0 = record.ephem_epochs[0]
        t = record.ephem_epochs.utc
        self.ts = ((t.jd1 - self.t0.utc.jd1) + (t.jd2 - self.t0.utc.jd2)) * 86400.0
        self.states = np.asarray(record.ephem_states, dtype=float)
        gaps = set(record.extra.get("gaps_after_index", []))
        self.gap_after = np.array([i in gaps for i in range(len(self.ts) - 1)], dtype=bool)

    def coverage(self) -> tuple[Time | None, Time | None]:
        e = self.record.ephem_epochs
        return e[0], e[-1]

    def propagate(self, start: Time, offsets_s: np.ndarray) -> PropagationResult:
        q = offsets_from(self.t0, start) + np.asarray(offsets_s, dtype=float)
        n = len(q)
        r = np.full((n, 3), np.nan)
        v = np.full((n, 3), np.nan)
        idx = np.searchsorted(self.ts, q, side="right") - 1
        exact_end = np.isclose(q, self.ts[-1], atol=1e-6)
        idx = np.where(exact_end, len(self.ts) - 2, idx)
        inside = (idx >= 0) & (idx < len(self.ts) - 1)
        ok = inside.copy()
        ok[inside] &= ~self.gap_after[idx[inside]]
        k = idx[ok]
        t0, t1 = self.ts[k], self.ts[k + 1]
        h = t1 - t0
        s = (q[ok] - t0) / h
        p0, p1 = self.states[k, :3], self.states[k + 1, :3]
        m0, m1 = self.states[k, 3:] * h[:, None], self.states[k + 1, 3:] * h[:, None]
        s = s[:, None]
        h00 = 2 * s**3 - 3 * s**2 + 1
        h10 = s**3 - 2 * s**2 + s
        h01 = -2 * s**3 + 3 * s**2
        h11 = s**3 - s**2
        r[ok] = h00 * p0 + h10 * m0 + h01 * p1 + h11 * m1
        d00 = 6 * s**2 - 6 * s
        d10 = 3 * s**2 - 4 * s + 1
        d01 = -6 * s**2 + 6 * s
        d11 = 3 * s**2 - 2 * s
        v[ok] = (d00 * p0 + d10 * m0 + d01 * p1 + d11 * m1) / h[:, None]
        warnings = []
        if np.any(~inside):
            warnings.append(f"{int(np.sum(~inside))} requested epochs outside ephemeris coverage (not extrapolated)")
        if np.any(inside & ~ok):
            warnings.append("requested epochs fall inside an ephemeris gap (not interpolated)")
        return PropagationResult(self.object_id, self.frame, r, v, ok, self.method, warnings)


def j2_accel(r: np.ndarray) -> np.ndarray:
    x, y, z = r
    rn = math.sqrt(x * x + y * y + z * z)
    a = -MU_EARTH_KM3_S2 * r / rn**3
    k = 1.5 * J2_EARTH * MU_EARTH_KM3_S2 * R_EARTH_KM**2 / rn**5
    zz = 5 * z * z / (rn * rn)
    a = a + k * np.array([x * (zz - 1), y * (zz - 1), z * (zz - 3)])
    return a


class J2Propagator:
    """Two-body + J2 (zonal, about the frame's z-axis). DOP853, rtol 1e-11, atol 1e-9 km."""

    method = "Numerical two-body + J2 (DOP853, rtol 1e-11, atol 1e-9 km)"

    def __init__(self, object_id: str, epoch: Time, r_km: np.ndarray, v_km_s: np.ndarray, frame: Frame):
        self.object_id = object_id
        self.epoch = epoch
        self.r0 = np.asarray(r_km, dtype=float)
        self.v0 = np.asarray(v_km_s, dtype=float)
        self.frame = frame
        self._fwd = None  # (span_s, dense solution) for t >= 0
        self._bwd = None  # for t <= 0

    def coverage(self) -> tuple[Time | None, Time | None]:
        return None, None

    def _ensure(self, lo: float, hi: float) -> None:
        """Integrate once (forward and/or backward from epoch) with dense output
        covering [lo, hi] seconds from epoch; later queries reuse the
        DOP853 continuous extension (7th-order interpolant, same tolerances)."""
        y0 = np.concatenate([self.r0, self.v0])

        def f(_t, y):
            return np.concatenate([y[3:], j2_accel(y[:3])])

        for sign, bound in ((1, hi), (-1, lo)):
            have = self._fwd if sign == 1 else self._bwd
            need = bound * sign
            if need <= 0 or (have is not None and have[0] >= need):
                continue
            span = max(need * 1.25, 600.0)  # integrate a little beyond to avoid frequent re-integration
            sol = solve_ivp(f, (0.0, sign * span), y0, method="DOP853", rtol=1e-11, atol=1e-9, dense_output=True)
            if not sol.success:
                raise RuntimeError(f"J2 integration failed: {sol.message}")
            if sign == 1:
                self._fwd = (span, sol.sol)
            else:
                self._bwd = (span, sol.sol)

    def propagate(self, start: Time, offsets_s: np.ndarray) -> PropagationResult:
        q = offsets_from(self.epoch, start) + np.asarray(offsets_s, dtype=float)
        n = len(q)
        r = np.full((n, 3), np.nan)
        v = np.full((n, 3), np.nan)
        if n:
            self._ensure(float(q.min()), float(q.max()))
        for mask, dense in ((q > 0, self._fwd), (q < 0, self._bwd)):
            if np.any(mask):
                y = dense[1](q[mask])
                r[mask] = y[:3].T
                v[mask] = y[3:].T
        zero = q == 0
        r[zero] = self.r0
        v[zero] = self.v0
        valid = np.all(np.isfinite(r), axis=1)
        return PropagationResult(self.object_id, self.frame, r, v, valid, self.method)

    def with_impulse(self, t_offset_s: float, dv_inertial_km_s: np.ndarray) -> J2Propagator:
        """New propagator whose state includes an impulsive Δv applied at epoch + t_offset_s."""
        res = self.propagate(self.epoch, np.array([t_offset_s]))
        from astropy.time import TimeDelta

        new_epoch = self.epoch + TimeDelta(t_offset_s, format="sec")
        return J2Propagator(self.object_id, new_epoch, res.r_km[0], res.v_km_s[0] + dv_inertial_km_s, self.frame)


def select_records(records: list[OrbitalRecord]) -> tuple[dict[str, OrbitalRecord], list[str]]:
    """Choose one propagatable record per object.

    GP: most recent epoch. Ephemeris: most recent segment start. Duplicates and
    conflicting records are excluded. Single STATE records are not
    propagatable and are reported.
    """
    chosen: dict[str, OrbitalRecord] = {}
    notes: list[str] = []
    for r in records:
        if r.extra.get("duplicate_of") or r.extra.get("conflict_with"):
            continue
        if r.kind is RecordKind.STATE:
            continue
        prev = chosen.get(r.object_id)
        if prev is None:
            chosen[r.object_id] = r
            continue
        if prev.kind is not r.kind:
            # Prefer operator ephemeris over GP elements when both exist: it is
            # the higher-fidelity source. Record the choice.
            if r.kind is RecordKind.EPHEMERIS:
                chosen[r.object_id] = r
            notes.append(f"{r.object_id}: ephemeris preferred over GP elements")
            continue
        if r.epoch > prev.epoch:
            chosen[r.object_id] = r
    states_only = sorted({r.object_id for r in records if r.kind is RecordKind.STATE} - set(chosen))
    if states_only:
        notes.append(f"{len(states_only)} objects have only single-epoch states and cannot be propagated: {', '.join(states_only[:10])}")
    return chosen, notes


def make_propagator(record: OrbitalRecord) -> Propagator:
    if record.kind is RecordKind.GP_ELEMENTS:
        return SGP4Propagator(record)
    if record.kind is RecordKind.EPHEMERIS:
        return EphemerisInterpolator(record)
    raise ValueError(f"record kind {record.kind} is not propagatable")
