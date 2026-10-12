"""Feature schema. Only quantities known at screening time are used; Pc and
covariance-derived values are deliberately excluded because (a) the label is
derived from Pc in the synthetic set (label leakage) and (b) the model's
purpose is to rank encounters when covariance is unavailable."""

from __future__ import annotations

import math

import numpy as np

FEATURES = [
    "log10_miss_km",
    "rel_speed_km_s",
    "approach_angle_deg",
    "radial_fraction",
    "altitude_km",
    "max_data_age_days",
    "hours_to_tca",
]
SCHEMA_VERSION = "features/1"


def from_encounter(geom: dict, altitude_km: float, max_age_days: float, hours_to_tca: float) -> list[float]:
    miss = max(float(geom["miss_km"]), 1e-6)
    rtn = geom.get("rel_pos_rtn_km") or [0.0, 0.0, 0.0]
    radial_frac = abs(rtn[0]) / miss if miss > 0 else 0.0
    return [
        math.log10(miss),
        float(geom["rel_speed_km_s"]),
        float(geom["approach_angle_deg"]),
        float(min(radial_frac, 1.0)),
        float(altitude_km),
        float(max_age_days),
        float(hours_to_tca),
    ]


def matrix(rows: list[list[float]]) -> np.ndarray:
    x = np.asarray(rows, dtype=float)
    if x.ndim != 2 or x.shape[1] != len(FEATURES):
        raise ValueError(f"expected {len(FEATURES)} features ({SCHEMA_VERSION})")
    return x
