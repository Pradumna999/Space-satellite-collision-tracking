# Data formats

## Standard editions — UNVERIFIED

The CCSDS editions below are the ones the parsers were written against, recorded from the implementer's knowledge. The CCSDS publications site could not be read from this build environment, so the **current editions and any technical corrigenda have not been verified**. Check <https://ccsds.org/publications/bluebooks/> before relying on conformance.

| Message | Standard assumed | Supported encodings |
|---|---|---|
| OMM, OEM | CCSDS 502.0-B-3 *Orbit Data Messages* | OMM: KVN, XML, JSON/CSV (CelesTrak field names). OEM: KVN |
| CDM | CCSDS 508.0-B-1 *Conjunction Data Message* | KVN |

Not supported: OPM, OEM XML, CDM XML, the NDM container beyond OMM extraction, SGP4-XP elements.

## Formats

**TLE** — 2- or 3-line sets (optional `0 NAME` lines), Alpha-5 catalogue numbers. Checks: 69-character lines, line numbers, modulo-10 checksums (never repaired), matching catalogue numbers, numeric fields, SGP4 initialisation, 0 ≤ e < 1, 0–180° inclination, mean motion > 0 (warn > 17 rev/day), low perigee, deep-space flag (period ≥ 225 min).

**OMM** — required: EPOCH, MEAN_MOTION, ECCENTRICITY, INCLINATION, RA_OF_ASC_NODE, ARG_OF_PERICENTER, MEAN_ANOMALY, NORAD_CAT_ID, BSTAR. Must be MEAN_ELEMENT_THEORY SGP4, REF_FRAME TEME, TIME_SYSTEM UTC, CENTER_NAME EARTH. XML is parsed with `defusedxml` (entity expansion and external entities rejected).

**OEM (KVN)** — multiple META/DATA segments; 7 or 10 data columns (accelerations ignored); COVARIANCE blocks (21 lower-triangular values, `COV_REF_FRAME` RTN/RSW/RIC/UVW mapped to RTN). Checks: required metadata, EARTH centre, supported frame/time system, ≥ 2 states, strictly increasing epochs, gaps > 3× median step (interpolation refused across them), data outside START/STOP, sub-surface or implausible radii, covariance validity.

**CDM (KVN)** — header, relative data and OBJECT1/OBJECT2 sections. States in km and km/s; 6×6 RTN covariance `CR_R … CNDOT_NDOT` in m-based units converted ×1e-6 to km-based units (recorded as a transformation). Originator MISS_DISTANCE and COLLISION_PROBABILITY are kept **for comparison only**. HBR is not part of CDM 508.0-B-1; the analyst supplies it. `AREA_PC` is stored but not converted automatically.

**astral-states/1 CSV** — header row; required `object_id, epoch, time_system, frame, x_km, y_km, z_km, vx_km_s, vy_km_s, vz_km_s`; optional `object_name, hard_body_radius_m`. Units are fixed. Files that look like metres are flagged and **not rescaled**.

**astral-states/1 JSON** — `{"schema": "astral-states/1", "objects": [{object_id, epoch, time_system, frame, position_km[3], velocity_km_s[3], hard_body_radius_m?, covariance?: {frame: "RTN"|inertial, units: "km", matrix: 6×6}}]}`.

Frames accepted: TEME, GCRF/GCRS/ICRF (treated as geocentric GCRF axes), EME2000/J2000, ITRF/ITRF-xx. Time systems: UTC, TAI, TT, GPS, TDB.

## Dataset-level checks

Exact duplicates (`DUPLICATE_RECORD`; first kept), conflicting records at the same epoch (`CONFLICTING_RECORD`; error), multiple element sets per object (latest used), stale data, future epochs, epoch spread > 30 days, leap-second and EOP table validity.

## Exports

* **OEM** (KVN 2.0) of a propagated nominal trajectory, frame as propagated (TEME for SGP4), no covariance; re-parsed and validated before download.
* **CDM** (KVN) for encounters with both covariances only (508.0-B-1 requires them). Mapping losses: no HBR field; ASTRAL omits fields it does not compute (screening volume, data quality, ephemeris names).
* **CSV/JSON/PDF reports** — see `services/reports.py`; the JSON schema is `astral-report/1`.

Example files (generated samples): `examples/`.
