"""Normalised orbital records.

Every parser produces ``OrbitalRecord`` objects. A record is a faithful
representation of one object's orbital information from one source; no
scientifically meaningful field is altered during normalisation. Unit
conversions applied by a parser (e.g. CDM covariance m^2 -> km^2) are listed
in ``transformations`` so they remain traceable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import numpy as np
from astropy.time import Time

from .frames import Frame
from .timeutil import iso_full


class RecordKind(str, Enum):
    GP_ELEMENTS = "gp_elements"  # TLE or OMM mean elements -> SGP4
    STATE = "state"  # single Cartesian state (optionally with covariance)
    EPHEMERIS = "ephemeris"  # time-tagged Cartesian states (OEM, operator ephemeris)


@dataclass
class Covariance:
    """6x6 covariance in km, km/s units.

    ``frame`` is either an inertial ``Frame`` value or ``"RTN"`` (relative to
    the object's own state at ``epoch``).
    """

    matrix: np.ndarray
    frame: str
    epoch: Time
    source: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "matrix_km": self.matrix.tolist(),
            "frame": self.frame,
            "epoch": iso_full(self.epoch),
            "source": self.source,
        }

    @staticmethod
    def from_dict(d: dict[str, Any]) -> Covariance:
        return Covariance(np.asarray(d["matrix_km"], dtype=float), d["frame"], Time(d["epoch"], scale="utc", precision=9), d["source"])


@dataclass
class OrbitalRecord:
    object_id: str
    kind: RecordKind
    source_format: str
    epoch: Time
    frame: Frame
    time_system: str
    object_name: str | None = None
    # GP elements (TLE/OMM)
    tle_line1: str | None = None
    tle_line2: str | None = None
    mean_elements: dict[str, Any] | None = None
    # Single state
    position_km: np.ndarray | None = None
    velocity_km_s: np.ndarray | None = None
    covariance: Covariance | None = None
    # Ephemeris
    ephem_epochs: Time | None = None
    ephem_states: np.ndarray | None = None  # (N,6) km, km/s
    interpolation: str | None = None
    interpolation_degree: int | None = None
    # Physical
    hard_body_radius_m: float | None = None
    # Traceability
    source_ref: str | None = None  # e.g. "lines 3-5" or "OBJECT1"
    transformations: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    def key(self) -> tuple[str, str]:
        return (self.object_id, iso_full(self.epoch))

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "object_id": self.object_id,
            "object_name": self.object_name,
            "kind": self.kind.value,
            "source_format": self.source_format,
            "epoch": iso_full(self.epoch),
            "frame": self.frame.value,
            "time_system": self.time_system,
            "hard_body_radius_m": self.hard_body_radius_m,
            "source_ref": self.source_ref,
            "transformations": list(self.transformations),
            "extra": self.extra,
        }
        if self.kind is RecordKind.GP_ELEMENTS:
            d["tle_line1"] = self.tle_line1
            d["tle_line2"] = self.tle_line2
            d["mean_elements"] = self.mean_elements
        if self.position_km is not None:
            d["position_km"] = np.asarray(self.position_km).tolist()
            d["velocity_km_s"] = np.asarray(self.velocity_km_s).tolist()
        if self.covariance is not None:
            d["covariance"] = self.covariance.to_dict()
        if self.kind is RecordKind.EPHEMERIS and self.ephem_epochs is not None:
            d["ephem_epochs"] = list(iso_full(self.ephem_epochs))
            d["ephem_states"] = np.asarray(self.ephem_states).tolist()
            d["interpolation"] = self.interpolation
            d["interpolation_degree"] = self.interpolation_degree
        return d

    @staticmethod
    def from_dict(d: dict[str, Any]) -> OrbitalRecord:
        rec = OrbitalRecord(
            object_id=d["object_id"],
            object_name=d.get("object_name"),
            kind=RecordKind(d["kind"]),
            source_format=d["source_format"],
            epoch=Time(d["epoch"], scale="utc", precision=9),
            frame=Frame(d["frame"]),
            time_system=d["time_system"],
            hard_body_radius_m=d.get("hard_body_radius_m"),
            source_ref=d.get("source_ref"),
            transformations=list(d.get("transformations", [])),
            extra=dict(d.get("extra", {})),
            tle_line1=d.get("tle_line1"),
            tle_line2=d.get("tle_line2"),
            mean_elements=d.get("mean_elements"),
        )
        if "position_km" in d:
            rec.position_km = np.asarray(d["position_km"], dtype=float)
            rec.velocity_km_s = np.asarray(d["velocity_km_s"], dtype=float)
        if "covariance" in d and d["covariance"] is not None:
            rec.covariance = Covariance.from_dict(d["covariance"])
        if "ephem_epochs" in d:
            rec.ephem_epochs = Time(d["ephem_epochs"], scale="utc", precision=9)
            rec.ephem_states = np.asarray(d["ephem_states"], dtype=float)
            rec.interpolation = d.get("interpolation")
            rec.interpolation_degree = d.get("interpolation_degree")
        return rec
