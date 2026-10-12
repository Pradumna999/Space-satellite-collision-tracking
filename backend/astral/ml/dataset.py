"""Synthetic labelled encounter data (EXPERIMENTAL, SYNTHETIC).

Generation procedure (deterministic given the seed):
  * Event series: each synthetic event has 1-5 updates ("CDM-like" looks)
    at decreasing hours-to-TCA. Updates share a group id; splits are by group
    so no event appears in two splits (duplicate-event leakage control), and
    the test set is the chronologically latest 20% of groups (temporal
    split).
  * Geometry: miss log-uniform in [50 m, 50 km]; relative speed uniform
    [0.2, 15.5] km/s; approach angle derived from speed; radial fraction
    uniform; altitude uniform [300, 1500] km.
  * ASSUMED uncertainty-growth model (not fitted to any real data):
        σ_T = 0.05 + 0.35·age + 0.02·h  (km),   σ_R = σ_N = σ_T/6,
    for each object, age = data age (days), h = hours to TCA.
  * Label: 2D Pc (ASTRAL foster_2d, HBR 20 m) >= 1e-3 -> priority 1
    (prevalence ~4% under the assumed growth model: a rare-event setting.
    The threshold was chosen to produce that setting; it is NOT an
    operational decision threshold).

A model trained on this data learns the assumed growth model, not reality.
It cannot demonstrate real-world generalisation.
"""

from __future__ import annotations

import hashlib
import math

import numpy as np

from ..core.pc import PcStatus, foster_2d
from .features import FEATURES, from_encounter

HBR_KM = 0.020
PC_THRESHOLD = 1e-3


def generate(n_groups: int = 3000, seed: int = 20261011) -> dict:
    rng = np.random.default_rng(seed)
    rows, labels, groups, created, pcs, regimes = [], [], [], [], [], []
    for g in range(n_groups):
        miss = 10 ** rng.uniform(math.log10(0.05), math.log10(50))
        speed = rng.uniform(0.2, 15.5)
        alt = rng.uniform(300, 1500)
        radial = rng.uniform(0, 0.6)
        age = rng.uniform(0.05, 6.0)
        v_orb = 7.9 * math.sqrt(6378.0 / (6378.0 + alt))
        angle = math.degrees(2 * math.asin(min(speed / (2 * v_orb), 1.0)))
        n_upd = int(rng.integers(1, 6))
        hours = sorted(rng.uniform(1, 72, size=n_upd), reverse=True)
        for h in hours:
            # miss estimate converges as TCA approaches (assumed)
            m = miss * math.exp(rng.normal(0, 0.15 * h / 72))
            r = np.array([6378.0 + alt, 0.0, 0.0])
            v1 = np.array([0.0, v_orb, 0.0])
            th = math.radians(angle)
            v2 = np.array([0.0, v_orb * math.cos(th), v_orb * math.sin(th)])
            dv = v2 - v1
            z = dv / np.linalg.norm(dv)
            perp = np.array([1.0, 0.0, 0.0]) * radial + np.cross(z, [1.0, 0.0, 0.0]) * math.sqrt(1 - radial**2)
            perp = perp - np.dot(perp, z) * z
            perp /= np.linalg.norm(perp)
            r2 = r + perp * m
            s_t = 0.05 + 0.35 * age + 0.02 * h
            c = np.diag([(s_t / 6) ** 2, s_t**2, (s_t / 6) ** 2])
            res = foster_2d(r, v1, c, r2, v2, c, HBR_KM)
            pc = res.value if res.status is PcStatus.COMPUTED else 0.0
            geom = {"miss_km": m, "rel_speed_km_s": float(np.linalg.norm(dv)), "approach_angle_deg": angle,
                    "rel_pos_rtn_km": [radial * m, 0.0, 0.0]}
            rows.append(from_encounter(geom, alt, age, h))
            labels.append(int(pc >= PC_THRESHOLD))
            pcs.append(pc)
            groups.append(g)
            created.append(g * 1.0 + (72 - h) / 100.0)
            regimes.append("LEO<700" if alt < 700 else ("LEO700-1000" if alt < 1000 else "LEO>1000"))
    x = np.asarray(rows)
    y = np.asarray(labels)
    digest = hashlib.sha256(x.tobytes() + y.tobytes()).hexdigest()
    return {"X": x, "y": y, "groups": np.asarray(groups), "created": np.asarray(created), "pc": np.asarray(pcs),
            "regime": np.asarray(regimes), "features": FEATURES, "seed": seed, "sha256": digest, "origin": "simulated",
            "label_definition": f"2D Pc (HBR {HBR_KM * 1000:.0f} m, assumed covariance growth) >= {PC_THRESHOLD:g}"}


def split(data: dict, test_frac: float = 0.2, val_frac: float = 0.2) -> dict:
    """Temporal, group-disjoint split: test = latest groups; validation = the
    latest groups among the remainder."""
    groups = data["groups"]
    ug = np.unique(groups)
    order = ug[np.argsort([data["created"][groups == g].min() for g in ug])]
    n = len(order)
    n_test = int(n * test_frac)
    n_val = int((n - n_test) * val_frac)
    test_g = set(order[n - n_test:])
    val_g = set(order[n - n_test - n_val:n - n_test])
    idx = np.arange(len(groups))
    te = np.array([g in test_g for g in groups])
    va = np.array([g in val_g for g in groups])
    tr = ~(te | va)
    return {"train": idx[tr], "val": idx[va], "test": idx[te]}
