"""Conjunction screening.

Algorithm (documented in SCIENTIFIC_METHODS.md §4)
--------------------------------------------------
1. Propagate every eligible object on a uniform grid of step Δt covering the
   window (end point included). Objects are expressed in TEME if every
   source is TEME, otherwise all are converted to GCRF.
2. Radial-band filter: an object's band is [min|r|, max|r|] over the grid,
   widened by max|v|·Δt/2. Two objects whose bands are further apart than the
   threshold D cannot approach within D, since |r1-r2| >= ||r1|-|r2||.
3. Proximity flagging at each step. A k-d tree first returns pairs within
   the loose radius D + v_rel,max·Δt/2 + ½a_max(Δt/2)². Each candidate is
   then tested with a tight, still conservative bound: around grid instant
   t_k the relative position is Δr(t_k+τ) = Δr_k + Δv_k τ + e(τ) with
   |e(τ)| <= ½ a_max τ², where a_max bounds the relative acceleration (sum of
   both objects' gravitational accelerations at the lowest sampled radius,
   +1% for J2). If the true minimum d* <= D occurs at t*, the nearest grid
   instant has |t* - t_k| <= Δt/2, so the linear-motion minimum over
   |τ| <= Δt/2 satisfies  d_lin <= D + ½ a_max (Δt/2)².  Pairs meeting this
   are flagged; no minimum below D is missed while the propagator is valid at
   t_k.
4. Refinement: for each flagged (pair, t_k), roots of the range-rate
   function f(t) = Δr·Δv on [t_{k-1}, t_{k+1}] are found with Brent's method
   (xtol 1e-6 s) after sub-sampling for sign changes. Minima are kept when
   d(TCA) <= D. A minimum on the analysis-window edge is reported with
   status WINDOW_BOUNDARY.
5. Step-size guard: Δt must be <= P_min/20 (P_min = shortest orbital period
   among screened objects) so that each refinement bracket contains at most
   one close approach per pair.

Propagator failures (SGP4 error codes, ephemeris gaps/coverage) are reported
as coverage warnings: screening cannot see an object where it has no valid
state, and the result says so.
"""

from __future__ import annotations

import math
import time
import tracemalloc
from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np
from astropy.time import Time, TimeDelta
from scipy.optimize import brentq
from scipy.spatial import cKDTree

from .. import ALGORITHM_VERSIONS
from .constants import MU_EARTH_KM3_S2
from .encounter import geometry
from .frames import Frame, convert
from .propagation import Propagator
from .timeutil import iso_utc, window_contains_leap_second


class ScreeningConfigError(ValueError):
    pass


class Cancelled(Exception):
    pass


@dataclass
class ScreeningConfig:
    start: Time
    duration_s: float
    step_s: float = 30.0
    threshold_km: float = 5.0
    primary_ids: list[str] | None = None  # screen only pairs involving these objects
    max_objects: int = 5000
    max_flag_events: int = 200_000

    def validate(self) -> None:
        if not (0 < self.duration_s <= 14 * 86400):
            raise ScreeningConfigError("duration must be in (0, 14 days]")
        if not (0.5 <= self.step_s <= 600):
            raise ScreeningConfigError("step must be within [0.5, 600] s")
        if not (0 < self.threshold_km <= 200):
            raise ScreeningConfigError("threshold must be within (0, 200] km")
        end = self.start + TimeDelta(self.duration_s, format="sec")
        if window_contains_leap_second(self.start, end):
            raise ScreeningConfigError("analysis window contains a leap second; split the window")


@dataclass
class EncounterResult:
    primary: str
    secondary: str
    tca: Time
    geometry: dict
    refinement_status: str
    flags: list[str]
    primary_state: np.ndarray
    secondary_state: np.ndarray
    frame: str

    def to_dict(self) -> dict:
        return {
            "primary": self.primary,
            "secondary": self.secondary,
            "tca_utc": iso_utc(self.tca),
            "geometry": self.geometry,
            "refinement_status": self.refinement_status,
            "flags": self.flags,
            "primary_state": self.primary_state.tolist(),
            "secondary_state": self.secondary_state.tolist(),
            "frame": self.frame,
        }


@dataclass
class ScreeningResult:
    encounters: list[EncounterResult]
    frame: str
    stats: dict
    warnings: list[str] = field(default_factory=list)
    algorithm: str = ALGORITHM_VERSIONS["screening"]


class _Source:
    def __init__(self, prop: Propagator, frame: Frame):
        self.p = prop
        self.frame = frame
        self.evals = 0

    def states(self, start: Time, offsets: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[str]]:
        res = self.p.propagate(start, offsets)
        self.evals += len(offsets)
        r, v, ok = res.r_km, res.v_km_s, res.valid
        if res.frame is not self.frame and np.any(ok):
            idx = np.where(ok)[0]
            times = start + TimeDelta(np.asarray(offsets)[idx], format="sec")
            rc, vc = convert(r[idx], v[idx], res.frame, self.frame, times)
            r = r.copy()
            v = v.copy()
            r[idx], v[idx] = rc, vc
        return r, v, ok, res.warnings


def screen(
    propagators: dict[str, Propagator],
    cfg: ScreeningConfig,
    progress: Callable[[float, str], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> ScreeningResult:
    cfg.validate()
    t_wall = time.perf_counter()
    tracemalloc.start()
    progress = progress or (lambda f, m: None)
    cancelled = cancelled or (lambda: False)
    ids = sorted(propagators)
    if len(ids) < 2:
        raise ScreeningConfigError("at least two propagatable objects are required")
    if len(ids) > cfg.max_objects:
        raise ScreeningConfigError(f"{len(ids)} objects exceeds the configured limit {cfg.max_objects}")
    frames = {propagators[i].frame for i in ids}
    common = Frame.TEME if frames == {Frame.TEME} else Frame.GCRF
    src = {i: _Source(propagators[i], common) for i in ids}
    warnings: list[str] = []

    n_steps = int(math.ceil(cfg.duration_s / cfg.step_s))
    offsets = np.minimum(np.arange(n_steps + 1) * cfg.step_s, cfg.duration_s)
    offsets = np.unique(offsets)
    M, N = len(offsets), len(ids)
    R = np.full((N, M, 3), np.nan)
    V = np.full((N, M, 3), np.nan)
    OK = np.zeros((N, M), dtype=bool)
    progress(0.02, "propagating")
    for k, oid in enumerate(ids):
        if cancelled():
            raise Cancelled()
        r, v, ok, w = src[oid].states(cfg.start, offsets)
        R[k], V[k], OK[k] = r, v, ok
        for msg in w:
            warnings.append(f"{oid}: {msg}")
        if not np.all(ok):
            warnings.append(f"{oid}: no valid state at {int(np.sum(~ok))} of {M} grid instants; encounters there cannot be detected")
        if k % 50 == 0:
            progress(0.02 + 0.38 * (k + 1) / N, f"propagated {k + 1}/{N}")

    radius = np.linalg.norm(R, axis=2)
    speed = np.linalg.norm(V, axis=2)
    valid_any = OK.any(axis=1)
    rmin = np.where(valid_any, np.nanmin(np.where(OK, radius, np.inf), axis=1), np.inf)
    rmax = np.where(valid_any, np.nanmax(np.where(OK, radius, -np.inf), axis=1), -np.inf)
    vmax_obj = np.where(valid_any, np.nanmax(np.where(OK, speed, 0.0), axis=1), 0.0)
    half = cfg.step_s / 2.0
    band_lo = rmin - vmax_obj * half
    band_hi = rmax + vmax_obj * half

    # Step-size guard (two-body period from vis-viva energy at each object's first valid sample).
    periods = []
    for k in range(N):
        j = np.argmax(OK[k]) if OK[k].any() else None
        if j is None:
            continue
        rr, vv = np.linalg.norm(R[k, j]), np.linalg.norm(V[k, j])
        energy = vv * vv / 2 - MU_EARTH_KM3_S2 / rr
        if energy < 0:
            a = -MU_EARTH_KM3_S2 / (2 * energy)
            periods.append(2 * math.pi * math.sqrt(a**3 / MU_EARTH_KM3_S2))
    if periods and cfg.step_s > min(periods) / 20:
        raise ScreeningConfigError(f"step {cfg.step_s} s exceeds P_min/20 = {min(periods) / 20:.1f} s")

    r_floor = max(float(np.min(rmin[valid_any])), 6378.137 * 0.9) if valid_any.any() else 6378.137
    a_max = 2 * MU_EARTH_KM3_S2 / r_floor**2 * 1.01
    two_fastest = np.sort(vmax_obj)[-2:].sum()
    search_r = cfg.threshold_km + two_fastest * half + 0.5 * a_max * half * half

    prim_mask = np.ones(N, dtype=bool)
    if cfg.primary_ids:
        missing = set(cfg.primary_ids) - set(ids)
        if missing:
            warnings.append(f"primary objects not propagatable / not in dataset: {', '.join(sorted(missing))}")
        prim_mask = np.array([i in set(cfg.primary_ids) for i in ids])

    # Radial-band pair count (for the screening funnel), exact via sorted sweep.
    order = np.argsort(band_lo)
    lo_sorted = band_lo[order]
    pos = np.arange(N)
    reach = np.searchsorted(lo_sorted, band_hi[order] + cfg.threshold_km, side="right")
    radial_pairs_all = int(np.sum(np.maximum(reach - pos - 1, 0)))
    total_pairs = N * (N - 1) // 2
    if cfg.primary_ids:
        n_p = int(prim_mask.sum())
        total_pairs = n_p * (N - n_p) + n_p * (n_p - 1) // 2

    progress(0.4, "flagging close-approach candidates")
    flagged: dict[tuple[int, int], list[int]] = {}
    n_flag_events = 0
    pairs_radial_eliminated: set[tuple[int, int]] = set()
    for j in range(M):
        if cancelled():
            raise Cancelled()
        live = np.where(OK[:, j])[0]
        if len(live) < 2:
            continue
        tree = cKDTree(R[live, j])
        cand = tree.query_pairs(search_r, output_type="ndarray")
        if len(cand) == 0:
            continue
        a_idx, b_idx = live[cand[:, 0]], live[cand[:, 1]]
        lo, hi = np.minimum(a_idx, b_idx), np.maximum(a_idx, b_idx)
        if cfg.primary_ids:
            keep = prim_mask[lo] | prim_mask[hi]
            lo, hi = lo[keep], hi[keep]
        sep_ok = ~((band_lo[hi] > band_hi[lo] + cfg.threshold_km) | (band_lo[lo] > band_hi[hi] + cfg.threshold_km))
        for p in zip(lo[~sep_ok].tolist(), hi[~sep_ok].tolist()):
            pairs_radial_eliminated.add(p)
        lo, hi = lo[sep_ok], hi[sep_ok]
        drv = R[hi, j] - R[lo, j]
        dvv = V[hi, j] - V[lo, j]
        vv = np.einsum("ij,ij->i", dvv, dvv)
        tau = np.clip(-np.einsum("ij,ij->i", drv, dvv) / np.where(vv > 0, vv, 1.0), -half, half)
        d_lin = np.linalg.norm(drv + dvv * tau[:, None], axis=1)
        hit = d_lin <= cfg.threshold_km + 0.5 * a_max * half * half
        for a, b in zip(lo[hit].tolist(), hi[hit].tolist()):
            flagged.setdefault((a, b), []).append(j)
            n_flag_events += 1
        if n_flag_events > cfg.max_flag_events:
            raise ScreeningConfigError(f"more than {cfg.max_flag_events} candidate events; reduce step, window or threshold")
        if j % 100 == 0:
            progress(0.4 + 0.3 * j / M, f"flagging step {j}/{M}")

    progress(0.7, f"refining {len(flagged)} candidate pairs")
    encounters: list[EncounterResult] = []
    n_refined = 0
    n_roots = 0
    end_s = float(offsets[-1])
    for pi, ((a, b), steps) in enumerate(sorted(flagged.items())):
        if cancelled():
            raise Cancelled()
        sa, sb = src[ids[a]], src[ids[b]]
        tcas: list[tuple[float, str]] = []
        for j in sorted(set(steps)):
            lo_t = float(offsets[max(j - 1, 0)])
            hi_t = float(offsets[min(j + 1, M - 1)])
            sub = np.linspace(lo_t, hi_t, 9)
            ra, va, oka, _ = sa.states(cfg.start, sub)
            rb, vb, okb, _ = sb.states(cfg.start, sub)
            ok = oka & okb
            if ok.sum() < 2:
                continue
            f = np.einsum("ij,ij->i", rb - ra, vb - va)
            n_refined += 1
            for q in range(len(sub) - 1):
                if not (ok[q] and ok[q + 1]):
                    continue
                if f[q] < 0 <= f[q + 1]:
                    def rr(t: float) -> float:
                        r1, v1, _, _ = sa.states(cfg.start, np.array([t]))
                        r2, v2, _, _ = sb.states(cfg.start, np.array([t]))
                        return float(np.dot(r2[0] - r1[0], v2[0] - v1[0]))
                    try:
                        t_root = brentq(rr, float(sub[q]), float(sub[q + 1]), xtol=1e-6, maxiter=100)
                        tcas.append((t_root, "CONVERGED"))
                        n_roots += 1
                    except (ValueError, RuntimeError):
                        tcas.append((float(sub[q] if abs(f[q]) < abs(f[q + 1]) else sub[q + 1]), "REFINEMENT_FAILED"))
            # Minimum on the window edge (range still decreasing at end / increasing at start)
            if j == M - 1 and ok[-1] and f[-1] < 0:
                tcas.append((end_s, "WINDOW_BOUNDARY"))
            if j == 0 and ok[0] and f[0] > 0:
                tcas.append((0.0, "WINDOW_BOUNDARY"))
        tcas.sort()
        dedup: list[tuple[float, str]] = []
        for t, st in tcas:
            if dedup and abs(t - dedup[-1][0]) < 1.0:
                continue
            dedup.append((t, st))
        for t, st in dedup:
            r1, v1, ok1, _ = sa.states(cfg.start, np.array([t]))
            r2, v2, ok2, _ = sb.states(cfg.start, np.array([t]))
            if not (ok1[0] and ok2[0]):
                continue
            g = geometry(r1[0], v1[0], r2[0], v2[0])
            if g.miss_km > cfg.threshold_km:
                continue
            tca = cfg.start + TimeDelta(t, format="sec")
            flags = []
            if st != "CONVERGED":
                flags.append(st)
            encounters.append(
                EncounterResult(
                    ids[a], ids[b], tca, g.to_dict(), st, flags,
                    np.concatenate([r1[0], v1[0]]), np.concatenate([r2[0], v2[0]]), common.value,
                )
            )
        if pi % 20 == 0:
            progress(0.7 + 0.28 * (pi + 1) / max(len(flagged), 1), f"refined {pi + 1}/{len(flagged)} pairs")

    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    encounters.sort(key=lambda e: (e.tca.jd1 + e.tca.jd2, e.geometry["miss_km"]))
    stats = {
        "objects": N,
        "grid_steps": M,
        "step_s": cfg.step_s,
        "threshold_km": cfg.threshold_km,
        "search_radius_km": search_r,
        "relative_accel_bound_km_s2": a_max,
        "pairs_total": total_pairs,
        "pairs_radial_band_overlap": radial_pairs_all if not cfg.primary_ids else None,
        "pairs_eliminated_radial_in_proximity": len(pairs_radial_eliminated),
        "pairs_flagged": len(flagged),
        "flag_events": n_flag_events,
        "refinement_brackets": n_refined,
        "range_rate_roots": n_roots,
        "encounters": len(encounters),
        "propagation_evaluations": int(sum(s.evals for s in src.values())),
        "runtime_s": time.perf_counter() - t_wall,
        "peak_traced_memory_mb": peak / 1e6,
        "frame": common.value,
        "window_start_utc": iso_utc(cfg.start),
        "window_end_utc": iso_utc(cfg.start + TimeDelta(end_s, format="sec")),
    }
    progress(1.0, "screening complete")
    return ScreeningResult(encounters, common.value, stats, warnings)
