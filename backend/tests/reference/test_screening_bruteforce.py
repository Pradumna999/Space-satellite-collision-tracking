"""Screening completeness and refinement accuracy against brute force.

The independent reference is a dense 1-second sampling of every pair over
the window followed by local parabolic refinement — a different method from
the k-d tree / Brent pipeline under test. Every brute-force minimum below the
threshold (with a margin) must be found by the screener, and refined TCA and
miss distance must agree.
"""

import numpy as np
from astropy.time import Time

from astral.core.parsers import ingest
from astral.core.propagation import make_propagator, select_records
from astral.core.screening import ScreeningConfig, screen
from astral.core.synthetic import demo_catalogue

EPOCH = Time("2026-10-10T00:00:00", scale="utc")


def _props(n_bg=6, seed=3):
    txt = demo_catalogue(EPOCH, n_background=n_bg, n_engineered=3, seed=seed)
    res = ingest(txt, reference_time=EPOCH)
    chosen, _ = select_records(res.records)
    return {k: make_propagator(v) for k, v in chosen.items()}


def _brute(props, duration, threshold):
    ids = sorted(props)
    t = np.arange(0, duration + 1, 1.0)
    st = {i: props[i].propagate(EPOCH, t) for i in ids}
    found = []
    for a in range(len(ids)):
        for b in range(a + 1, len(ids)):
            dr_all = st[ids[b]].r_km - st[ids[a]].r_km
            dv_all = st[ids[b]].v_km_s - st[ids[a]].v_km_s
            d = np.linalg.norm(dr_all, axis=1)
            for k in range(1, len(t) - 1):
                if d[k] <= d[k - 1] and d[k] < d[k + 1]:
                    dr, dv = dr_all[k], dv_all[k]
                    ts = -np.dot(dr, dv) / np.dot(dv, dv)
                    dm = float(np.linalg.norm(dr + dv * ts))
                    if dm < threshold:
                        found.append((ids[a], ids[b], t[k] + ts, dm))
    return found


def test_screening_finds_every_bruteforce_minimum():
    props = _props()
    duration, threshold = 1.5 * 86400, 10.0
    res = screen(props, ScreeningConfig(start=EPOCH, duration_s=duration, step_s=60.0, threshold_km=threshold))
    brute = _brute(props, duration, threshold * 0.999)
    assert brute, "test data should contain close approaches"
    got = [((e.primary, e.secondary), (e.tca - EPOCH).sec, e.geometry["miss_km"]) for e in res.encounters]
    for a, b, tb, db in brute:
        match = [g for g in got if g[0] == (a, b) and abs(g[1] - tb) < 2.0]
        assert match, f"missed {a}-{b} at t={tb:.1f}s d={db:.3f} km"
        assert abs(match[0][1] - tb) < 0.01, "TCA disagreement > 10 ms"
        assert abs(match[0][2] - db) < 0.01, "miss distance disagreement > 10 m"


def test_refined_tca_is_stationary():
    props = _props()
    res = screen(props, ScreeningConfig(start=EPOCH, duration_s=86400, step_s=30.0, threshold_km=10.0))
    for e in res.encounters:
        if e.refinement_status == "CONVERGED":
            # range-rate at refined TCA ~ 0 (Brent xtol 1e-6 s x relative accel)
            assert abs(e.geometry["range_rate_km_s"]) < 1e-4
