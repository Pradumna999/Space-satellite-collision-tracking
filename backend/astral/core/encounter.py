"""Encounter geometry at the time of closest approach (TCA)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .frames import rtn_basis


@dataclass
class EncounterGeometry:
    miss_km: float
    rel_speed_km_s: float
    rel_pos_km: np.ndarray  # secondary - primary, inertial
    rel_vel_km_s: np.ndarray
    rel_pos_rtn_km: np.ndarray  # in primary's RTN frame
    rel_vel_rtn_km_s: np.ndarray
    approach_angle_deg: float  # angle between the two velocity vectors
    encounter_plane_basis: np.ndarray  # rows x, y, z(=relative velocity direction)
    miss_in_plane_km: np.ndarray  # (x, y) in encounter plane
    range_rate_km_s: float  # residual d|r|/dt at the refined TCA (should be ~0)

    def to_dict(self) -> dict:
        return {
            "miss_km": self.miss_km,
            "rel_speed_km_s": self.rel_speed_km_s,
            "rel_pos_km": self.rel_pos_km.tolist(),
            "rel_vel_km_s": self.rel_vel_km_s.tolist(),
            "rel_pos_rtn_km": self.rel_pos_rtn_km.tolist(),
            "rel_vel_rtn_km_s": self.rel_vel_rtn_km_s.tolist(),
            "approach_angle_deg": self.approach_angle_deg,
            "encounter_plane_basis": self.encounter_plane_basis.tolist(),
            "miss_in_plane_km": self.miss_in_plane_km.tolist(),
            "range_rate_km_s": self.range_rate_km_s,
        }


def encounter_frame(dr: np.ndarray, dv: np.ndarray) -> np.ndarray:
    """Orthonormal basis (rows x, y, z) with z along relative velocity and x
    along the component of relative position perpendicular to z."""
    z = dv / np.linalg.norm(dv)
    perp = dr - np.dot(dr, z) * z
    pn = np.linalg.norm(perp)
    if pn < 1e-12:
        # Head-on with zero miss: choose any axis perpendicular to z.
        trial = np.array([1.0, 0.0, 0.0]) if abs(z[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
        perp = trial - np.dot(trial, z) * z
        pn = np.linalg.norm(perp)
    x = perp / pn
    y = np.cross(z, x)
    return np.vstack([x, y, z])


def geometry(r1: np.ndarray, v1: np.ndarray, r2: np.ndarray, v2: np.ndarray) -> EncounterGeometry:
    dr = np.asarray(r2, float) - np.asarray(r1, float)
    dv = np.asarray(v2, float) - np.asarray(v1, float)
    miss = float(np.linalg.norm(dr))
    speed = float(np.linalg.norm(dv))
    b = rtn_basis(r1, v1)
    c = float(np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2)))
    angle = float(np.degrees(np.arccos(np.clip(c, -1.0, 1.0))))
    if speed > 0:
        ef = encounter_frame(dr, dv)
        mp = ef[:2] @ dr
    else:
        ef = np.eye(3)
        mp = dr[:2]
    rr = float(np.dot(dr, dv) / miss) if miss > 0 else 0.0
    return EncounterGeometry(miss, speed, dr, dv, b @ dr, b @ dv, angle, ef, mp, rr)
