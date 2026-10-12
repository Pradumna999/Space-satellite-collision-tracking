"""Time-system handling.

Conventions
-----------
* Internally every analysis instant is a UTC Julian date carried as a pair
  ``(jd_day, jd_frac)`` so that float64 resolution stays near 1 microsecond.
* An analysis window is described by a start ``Time`` (UTC) and an array of
  offsets in seconds. Offsets are UTC-day arithmetic (86400 s per day); a
  window that contains a leap-second insertion is rejected rather than
  silently mis-timed (see ``window_contains_leap_second``).
* Conversions between UTC, TAI, TT and TDB use ERFA through astropy, with the
  leap-second table that ships with astropy (no network download at runtime).
  GPS time is handled as TAI - 19 s, which is exact by definition.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime

import numpy as np
from astropy.time import Time, TimeDelta
from astropy.utils import iers

# Never let astropy fetch IERS tables during an analysis: results must not
# depend on network availability at run time. Bundled tables are used and
# their expiry is checked explicitly below.
iers.conf.auto_download = False
iers.conf.auto_max_age = None

SUPPORTED_TIME_SYSTEMS = ("UTC", "TAI", "TT", "GPS", "TDB")
_GPS_MINUS_TAI_S = -19.0

_ISO = re.compile(r"^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2}(?:\.\d+)?)Z?$")
_DOY = re.compile(r"^(\d{4})-(\d{3})T(\d{2}):(\d{2}):(\d{2}(?:\.\d+)?)Z?$")


class TimeParseError(ValueError):
    pass


def parse_epoch(text: str, time_system: str = "UTC") -> Time:
    """Parse a CCSDS/ISO-8601 epoch string in the given time system.

    Accepts ``YYYY-MM-DDThh:mm:ss[.f]`` and the CCSDS day-of-year form
    ``YYYY-DDDThh:mm:ss[.f]``. Returns an astropy ``Time`` in UTC scale.
    """
    ts = time_system.strip().upper()
    if ts not in SUPPORTED_TIME_SYSTEMS:
        raise TimeParseError(f"unsupported time system {time_system!r}; supported: {SUPPORTED_TIME_SYSTEMS}")
    s = text.strip()
    m = _ISO.match(s)
    if m:
        y, mo, d, hh, mm, ss = m.groups()
        iso = f"{y}-{mo}-{d}T{hh}:{mm}:{ss}"
    else:
        m2 = _DOY.match(s)
        if not m2:
            raise TimeParseError(f"unrecognised epoch format: {text!r}")
        y, doy, hh, mm, ss = m2.groups()
        iso = f"{y}:{doy}:{hh}:{mm}:{ss}"
    try:
        if ts == "GPS":
            t = Time(iso, scale="tai") - TimeDelta(_GPS_MINUS_TAI_S, format="sec")
        else:
            t = Time(iso, scale=ts.lower())
        if m is None:
            t.format = "isot"
    except ValueError as exc:  # astropy raises ValueError for invalid calendar fields
        raise TimeParseError(f"invalid epoch {text!r}: {exc}") from exc
    return t.utc


def to_datetime_utc(t: Time) -> datetime:
    return t.utc.to_datetime(timezone=UTC)


def from_datetime(dt: datetime) -> Time:
    if dt.tzinfo is None:
        raise TimeParseError("naive datetime rejected; timestamps must carry an explicit UTC offset")
    return Time(dt.astimezone(UTC).replace(tzinfo=None), scale="utc")


def iso_full(t: Time):
    """Full-precision (nanosecond) ISO UTC representation used for persistence."""
    return Time(t.utc, precision=9).isot


def iso_utc(t: Time) -> str:
    """Unambiguous machine-readable UTC string, millisecond precision, 'Z' suffix."""
    return t.utc.isot[:23] + "Z"


@dataclass(frozen=True)
class TimeGrid:
    """A start instant plus offsets (seconds, UTC-day arithmetic)."""

    start: Time
    offsets_s: np.ndarray

    def jd_pair(self) -> tuple[np.ndarray, np.ndarray]:
        return utc_jd_pair(self.start, self.offsets_s)

    def at(self, i: int) -> Time:
        return self.start + TimeDelta(float(self.offsets_s[i]), format="sec")


def utc_jd_pair(start: Time, offsets_s: np.ndarray | float) -> tuple[np.ndarray, np.ndarray]:
    """UTC Julian date split into whole and fractional parts for SGP4."""
    off = np.atleast_1d(np.asarray(offsets_s, dtype=float))
    jd1 = float(start.utc.jd1)
    jd2 = float(start.utc.jd2) + off / 86400.0
    whole = np.floor(jd1 + jd2)
    frac = (jd1 - whole) + jd2
    return whole, frac


def offsets_from(start: Time, t: Time) -> float:
    """Seconds from ``start`` to ``t`` in UTC-day arithmetic."""
    a, b = start.utc, t.utc
    return float(((b.jd1 - a.jd1) + (b.jd2 - a.jd2)) * 86400.0)


def leap_second_table_expiry() -> Time:
    return Time(iers.LeapSeconds.auto_open().expires)


def window_contains_leap_second(start: Time, end: Time) -> bool:
    """True if TAI-UTC changes inside [start, end]."""
    def tai_minus_utc(t: Time) -> float:
        return float((t.tai.jd1 - t.utc.jd1 + t.tai.jd2 - t.utc.jd2) * 86400.0)

    return abs(tai_minus_utc(start) - tai_minus_utc(end)) > 0.5


def beyond_leap_second_validity(t: Time) -> bool:
    return bool(t.utc > leap_second_table_expiry())


def data_age_days(epoch: Time, at: Time) -> float:
    return float((at.utc.jd1 - epoch.utc.jd1) + (at.utc.jd2 - epoch.utc.jd2))
