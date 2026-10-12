"""Hypothetical impulsive-manoeuvre analysis (simulation only).

This module never produces commands and never labels an option as safe or
recommended.

Model (differential)
--------------------
* Baseline: both objects follow their **source propagators** (SGP4 or the
  supplied ephemeris), i.e. exactly the trajectories used by screening, so
  the "no manoeuvre" miss distance equals the screening result.
* Manoeuvre effect: the primary's state at the burn epoch is integrated
  twice with the two-body + J2 model (DOP853) — with and without the
  impulsive Δv. The *difference* δr(t), δv(t) between those two runs is
  added to the source trajectory after the burn. Model errors common to both
  runs cancel; what remains is second order in the model error and in Δv.
* J2 is about the GCRF z-axis (pole-direction error ≈ 0.4°), Δv is given in
  the primary's RTN frame at the burn, uncertainty is not propagated.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from astropy.time import Time, TimeDelta
from scipy.optimize import minimize_scalar

from .. import ALGORITHM_VERSIONS
from .constants import MU_EARTH_KM3_S2
from .encounter import geometry
from .frames import Frame, convert, rtn_basis
from .propagation import J2Propagator, PropagationResult, Propagator
from .screening import ScreeningConfig, screen
from .timeutil import iso_utc, offsets_from

G0 = 9.80665e-3  # km/s^2
MODEL = "Source propagator (SGP4/ephemeris) + Δv effect from a differential two-body + J2 integration (DOP853)"


@dataclass
class ManeuverSpec:
    burn_time: Time
    dv_rtn_m_s: tuple[float, float, float]
    search_half_window_s: float = 1800.0
    spacecraft_mass_kg: float | None = None
    isp_s: float | None = None


@dataclass
class ArmResult:
    tca: Time | None
    miss_km: float | None
    rel_speed_km_s: float | None
    geometry: dict | None

    def to_dict(self) -> dict:
        return {
            "tca_utc": iso_utc(self.tca) if self.tca is not None else None,
            "miss_km": self.miss_km,
            "rel_speed_km_s": self.rel_speed_km_s,
            "geometry": self.geometry,
        }


@dataclass
class ManeuverResult:
    baseline: ArmResult
    alternative: ArmResult
    dv_magnitude_m_s: float
    propellant_kg: float | None
    displacement_at_tca_km: float | None
    other_encounters: list[dict]
    warnings: list[str] = field(default_factory=list)
    model: str = MODEL
    algorithm: str = ALGORITHM_VERSIONS["maneuver_sim"]

    def to_dict(self) -> dict:
        return {
            "label": "SIMULATION ONLY — decision support requiring independent expert review",
            "baseline": self.baseline.to_dict(),
            "alternative": self.alternative.to_dict(),
            "miss_change_km": (self.alternative.miss_km - self.baseline.miss_km)
            if self.alternative.miss_km is not None and self.baseline.miss_km is not None else None,
            "dv_magnitude_m_s": self.dv_magnitude_m_s,
            "propellant_kg": self.propellant_kg,
            "displacement_at_tca_km": self.displacement_at_tca_km,
            "other_encounters": self.other_encounters,
            "warnings": self.warnings,
            "model": self.model,
            "algorithm": self.algorithm,
        }


class GcrfView:
    """Wraps a propagator so that it always returns GCRF states."""

    def __init__(self, p: Propagator):
        self.p = p
        self.object_id = p.object_id
        self.frame = Frame.GCRF
        self.epoch = p.epoch
        self.method = p.method

    def coverage(self):
        return self.p.coverage()

    def propagate(self, start: Time, offsets_s: np.ndarray) -> PropagationResult:
        offsets_s = np.asarray(offsets_s, dtype=float)
        res = self.p.propagate(start, offsets_s)
        r, v = res.r_km.copy(), res.v_km_s.copy()
        if res.frame is not Frame.GCRF and res.valid.any():
            idx = np.where(res.valid)[0]
            r[idx], v[idx] = convert(r[idx], v[idx], res.frame, Frame.GCRF, start + TimeDelta(offsets_s[idx], format="sec"))
        return PropagationResult(self.object_id, Frame.GCRF, r, v, res.valid, self.method, res.warnings)


class ManoeuvredPropagator(GcrfView):
    """Source trajectory plus the differential effect of an impulsive Δv."""

    def __init__(self, p: Propagator, burn: Time, dv_rtn_km_s: np.ndarray):
        super().__init__(p)
        r1, v1 = _state_gcrf(p, burn)
        self.burn = burn
        self.base = J2Propagator(p.object_id, burn, r1, v1, Frame.GCRF)
        self.alt = J2Propagator(p.object_id, burn, r1, v1 + rtn_basis(r1, v1).T @ np.asarray(dv_rtn_km_s, float), Frame.GCRF)
        self.method = f"{p.method} + differential two-body/J2 Δv effect"

    def displacement(self, start: Time, offsets_s: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        q = offsets_from(self.burn, start) + np.asarray(offsets_s, dtype=float)
        dr = np.zeros((len(q), 3))
        dvv = np.zeros((len(q), 3))
        after = q > 0
        if after.any():
            sub = np.asarray(offsets_s, dtype=float)[after]
            a, b = self.alt.propagate(start, sub), self.base.propagate(start, sub)
            dr[after] = a.r_km - b.r_km
            dvv[after] = a.v_km_s - b.v_km_s
        return dr, dvv

    def propagate(self, start: Time, offsets_s: np.ndarray) -> PropagationResult:
        res = super().propagate(start, offsets_s)
        dr, dvv = self.displacement(start, offsets_s)
        return PropagationResult(self.object_id, Frame.GCRF, res.r_km + dr, res.v_km_s + dvv, res.valid, self.method, res.warnings)


def _state_gcrf(p: Propagator, t: Time) -> tuple[np.ndarray, np.ndarray]:
    res = p.propagate(t, np.array([0.0]))
    if not res.valid[0]:
        raise ValueError(f"{p.object_id}: no valid state at {iso_utc(t)}")
    r, v = convert(res.r_km, res.v_km_s, res.frame, Frame.GCRF, t)
    return r[0], v[0]


def _closest(pa, pb, centre: Time, half: float) -> ArmResult:
    """Closest approach of two GCRF-returning propagators within ±half of centre."""
    grid = np.linspace(-half, half, int(2 * half / 10) + 1)
    ra = pa.propagate(centre, grid)
    rb = pb.propagate(centre, grid)
    ok = ra.valid & rb.valid
    if not ok.any():
        return ArmResult(None, None, None, None)
    d = np.where(ok, np.linalg.norm(rb.r_km - ra.r_km, axis=1), np.inf)
    j = int(np.argmin(d))
    lo, hi = grid[max(j - 1, 0)], grid[min(j + 1, len(grid) - 1)]

    def dist(t: float) -> float:
        a = pa.propagate(centre, np.array([t]))
        b = pb.propagate(centre, np.array([t]))
        return float(np.linalg.norm(b.r_km[0] - a.r_km[0]))

    opt = minimize_scalar(dist, bounds=(lo, hi), method="bounded", options={"xatol": 1e-4})
    t = float(opt.x)
    a = pa.propagate(centre, np.array([t]))
    b = pb.propagate(centre, np.array([t]))
    g = geometry(a.r_km[0], a.v_km_s[0], b.r_km[0], b.v_km_s[0])
    return ArmResult(centre + TimeDelta(t, format="sec"), g.miss_km, g.rel_speed_km_s, g.to_dict())


def simulate(
    primary: Propagator,
    secondary: Propagator,
    tca: Time,
    spec: ManeuverSpec,
    others: dict[str, Propagator] | None = None,
    screen_threshold_km: float = 5.0,
) -> ManeuverResult:
    lead = (tca - spec.burn_time).sec
    if lead <= 0:
        raise ValueError("burn must occur before TCA")
    if lead > 7 * 86400:
        raise ValueError("burn more than 7 days before TCA is outside the supported simulation span")
    warnings = []
    sa, sb = GcrfView(primary), GcrfView(secondary)
    dv_rtn = np.asarray(spec.dv_rtn_m_s, float) / 1000.0
    alt = ManoeuvredPropagator(primary, spec.burn_time, dv_rtn)
    baseline = _closest(sa, sb, tca, spec.search_half_window_s)
    alternative = _closest(alt, sb, baseline.tca or tca, spec.search_half_window_s)
    disp = None
    if baseline.tca is not None:
        disp = float(np.linalg.norm(alt.displacement(baseline.tca, np.array([0.0]))[0][0]))

    dv_mag = float(np.linalg.norm(dv_rtn) * 1000.0)
    prop = None
    if spec.spacecraft_mass_kg and spec.isp_s:
        prop = float(spec.spacecraft_mass_kg * (1 - math.exp(-np.linalg.norm(dv_rtn) / (spec.isp_s * G0))))
    else:
        warnings.append("propellant not estimated: spacecraft mass and Isp not supplied")

    other_enc: list[dict] = []
    if others:
        props = {k: v for k, v in others.items() if k != primary.object_id}
        props[primary.object_id] = alt
        cfg = ScreeningConfig(start=spec.burn_time, duration_s=lead + spec.search_half_window_s, step_s=10.0,
                              threshold_km=screen_threshold_km, primary_ids=[primary.object_id])
        try:
            res = screen(props, cfg)
            for e in res.encounters:
                if secondary.object_id in (e.primary, e.secondary):
                    continue  # the encounter under study is reported in the arms above
                other_enc.append(e.to_dict())
            if res.warnings:
                warnings.extend(f"secondary screening: {w}" for w in res.warnings[:5])
        except Exception as exc:  # report, never hide, a failed side-screen
            warnings.append(f"post-manoeuvre screening against other objects failed: {exc}")
    else:
        warnings.append("other objects not screened against the alternative trajectory; broader consequences unassessed")
    warnings.append("uncertainty not propagated: miss-distance changes are nominal only")
    return ManeuverResult(baseline, alternative, dv_mag, prop, disp, other_enc, warnings)


# ---------------------------------------------------------------- option sweep

DIRECTIONS = {
    # label: unit vector in the primary's RTN frame at the burn
    "speed_up": (0.0, 1.0, 0.0),
    "slow_down": (0.0, -1.0, 0.0),
    "raise": (1.0, 0.0, 0.0),
    "lower": (-1.0, 0.0, 0.0),
    "sideways": (0.0, 0.0, 1.0),
}
DIRECTION_TEXT = {
    "speed_up": "Speed up (along-track +)",
    "slow_down": "Slow down (along-track −)",
    "raise": "Push outward (radial +)",
    "lower": "Push inward (radial −)",
    "sideways": "Sideways (cross-track)",
}


def orbital_period_s(p: Propagator, t: Time) -> float:
    r, v = _state_gcrf(p, t)
    energy = float(np.dot(v, v)) / 2 - MU_EARTH_KM3_S2 / float(np.linalg.norm(r))
    if energy >= 0:
        raise ValueError("primary is not on a bound orbit")
    return 2 * math.pi * math.sqrt((-MU_EARTH_KM3_S2 / (2 * energy)) ** 3 / MU_EARTH_KM3_S2)


def maneuver_options(
    primary: Propagator,
    secondary: Propagator,
    tca: Time,
    lead_orbits: tuple[float, ...] = (0.5, 1.0, 2.0),
    magnitudes_m_s: tuple[float, ...] = (0.05, 0.1, 0.2, 0.5),
    directions: tuple[str, ...] = tuple(DIRECTIONS),
    search_half_window_s: float = 600.0,
    now: Time | None = None,
) -> dict:
    """Predicted miss distance for a grid of hypothetical impulsive burns.

    The baseline is the source-propagator encounter (equal to screening).
    Other objects are not checked here; any option of interest should be run
    through `simulate(..., others=...)`.
    """
    sa, sb = GcrfView(primary), GcrfView(secondary)
    baseline = _closest(sa, sb, tca, search_half_window_s)
    if baseline.miss_km is None:
        raise ValueError("no valid states around TCA")
    period = orbital_period_s(primary, baseline.tca)
    leads, options = [], []
    for lo in lead_orbits:
        lead_s = lo * period
        burn = baseline.tca - TimeDelta(lead_s, format="sec")
        too_late = bool(burn < (now or Time.now()))
        leads.append({"lead_orbits": lo, "lead_minutes": lead_s / 60.0, "burn_utc": iso_utc(burn), "too_late": too_late})
        for d in directions:
            u = np.asarray(DIRECTIONS[d])
            for mag in magnitudes_m_s:
                alt = ManoeuvredPropagator(primary, burn, u * mag / 1000.0)
                arm = _closest(alt, sb, baseline.tca, search_half_window_s)
                if arm.miss_km is None:
                    continue
                options.append({
                    "lead_orbits": lo, "lead_minutes": lead_s / 60.0, "burn_utc": iso_utc(burn), "direction": d,
                    "direction_text": DIRECTION_TEXT[d], "dv_m_s": mag, "dv_rtn_m_s": (u * mag).tolist(),
                    "miss_km": arm.miss_km, "change_km": arm.miss_km - baseline.miss_km,
                    "km_per_m_s": (arm.miss_km - baseline.miss_km) / mag,
                    "tca_shift_s": (arm.tca - baseline.tca).sec if arm.tca is not None else None,
                    "too_late": too_late,
                })
    return {
        "label": "SIMULATION ONLY — predicted effect of hypothetical manoeuvres; not a recommendation",
        "baseline_miss_km": baseline.miss_km,
        "baseline_tca_utc": iso_utc(baseline.tca),
        "orbital_period_min": period / 60.0,
        "leads": leads,
        "options": options,
        "model": MODEL,
        "algorithm": ALGORITHM_VERSIONS["maneuver_sim"] + "+options/1",
        "caveats": [
            "Nominal trajectories only: uncertainty is not propagated.",
            "Other objects are not checked for these options; run a full simulation of any option before relying on it.",
            "Predictions combine the screening trajectories with a simplified (two-body + J2) estimate of the burn's effect.",
        ],
    }
