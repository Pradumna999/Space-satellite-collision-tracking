import json
import math

import numpy as np
import pytest
from astropy.time import Time

from astral.core.findings import Severity
from astral.core.parsers import FormatError, detect_format, ingest
from astral.core.parsers.cdm import parse_cdm_kvn
from astral.core.parsers.oem import parse_oem_kvn
from astral.core.parsers.omm import parse_omm_json, parse_omm_xml
from astral.core.parsers.tle import checksum, parse_tle_text
from astral.core.propagation import SGP4Propagator
from astral.core.records import OrbitalRecord

ISS = (
    "ISS (ZARYA)\n"
    "1 25544U 98067A   08264.51782528 -.00002182  00000-0 -11606-4 0  2927\n"
    "2 25544  51.6416 247.4627 0006703 130.5360 325.0288 15.72125391563537\n"
)
REF = Time("2008-09-21T00:00:00", scale="utc")


def codes(findings):
    return {f.code for f in findings}


def test_tle_valid():
    recs, f = parse_tle_text(ISS)
    assert len(recs) == 1 and recs[0].object_id == "25544" and recs[0].object_name == "ISS (ZARYA)"
    assert not any(x.severity is Severity.ERROR for x in f)
    assert recs[0].frame.value == "TEME"


def test_tle_checksum_error_not_repaired():
    bad = ISS.replace("0  2927", "0  2928")
    recs, f = parse_tle_text(bad)
    assert not recs and "TLE_CHECKSUM" in codes(f)
    assert any(x.suggestion for x in f if x.code == "TLE_CHECKSUM")


def test_tle_length_and_catnum():
    recs, f = parse_tle_text("1 25544U\n2 25544\n")
    assert not recs and "TLE_LINE_LENGTH" in codes(f)
    l1 = ISS.splitlines()[1]
    l2 = ISS.splitlines()[2].replace("2 25544", "2 25545")
    l2 = l2[:68] + str(checksum(l2))
    recs, f = parse_tle_text(l1 + "\n" + l2)
    assert "TLE_CATNUM_MISMATCH" in codes(f)


def test_duplicate_and_conflict_detection():
    res = ingest(ISS + ISS, reference_time=REF)
    assert "DUPLICATE_RECORD" in codes(res.findings)
    lines = ISS.splitlines()
    l2 = lines[2][:18] + "5" + lines[2][19:]  # perturb a RAAN digit
    l2 = l2[:68] + str(checksum(l2))
    res = ingest(ISS + lines[0] + "\n" + lines[1] + "\n" + l2 + "\n", reference_time=REF)
    assert "CONFLICTING_RECORD" in codes(res.findings)


def test_stale_flag():
    res = ingest(ISS, reference_time=Time("2008-10-21T00:00:00", scale="utc"))
    assert "STALE_DATA" in codes(res.findings)


def _omm_from_tle():
    recs, _ = parse_tle_text(ISS)
    me = recs[0].mean_elements
    sat = SGP4Propagator(recs[0]).sat
    ep = Time(sat.jdsatepoch, sat.jdsatepochF, format="jd", scale="utc")
    ep.precision = 6
    return {
        "OBJECT_NAME": "ISS (ZARYA)", "OBJECT_ID": "1998-067A", "EPOCH": ep.isot, "MEAN_MOTION": me["mean_motion_rev_day"],
        "ECCENTRICITY": me["eccentricity"], "INCLINATION": me["inclination_deg"], "RA_OF_ASC_NODE": me["raan_deg"],
        "ARG_OF_PERICENTER": me["arg_perigee_deg"], "MEAN_ANOMALY": me["mean_anomaly_deg"], "EPHEMERIS_TYPE": 0,
        "CLASSIFICATION_TYPE": "U", "NORAD_CAT_ID": 25544, "ELEMENT_SET_NO": 292, "REV_AT_EPOCH": 56353, "BSTAR": me["bstar"],
        "MEAN_MOTION_DOT": sat.ndot * (1440.0 * 1440.0 / (2 * math.pi)), "MEAN_MOTION_DDOT": 0.0,
    }


def test_omm_json_equivalent_to_tle():
    recs, f = parse_omm_json([_omm_from_tle()])
    assert recs, f
    tle_recs, _ = parse_tle_text(ISS)
    t = np.linspace(0, 86400, 25)
    a = SGP4Propagator(recs[0]).propagate(REF, t)
    b = SGP4Propagator(tle_recs[0]).propagate(REF, t)
    # Epoch is serialised at microsecond precision: 7.7 km/s * 1 µs ≈ 8 mm.
    assert np.max(np.linalg.norm(a.r_km - b.r_km, axis=1)) < 0.05


def test_omm_rejects_non_sgp4_frame():
    d = _omm_from_tle() | {"REF_FRAME": "GCRF"}
    recs, f = parse_omm_json([d])
    assert not recs and "OMM_FRAME_TIME" in codes(f)


def test_omm_xml_and_xxe_rejected():
    d = _omm_from_tle()
    body = "".join(f"<{k}>{v}</{k}>" for k, v in d.items())
    xml = f'<?xml version="1.0"?><ndm><omm><body><segment><data>{body}</data></segment></body></omm></ndm>'
    recs, f = parse_omm_xml(xml)
    assert len(recs) == 1
    evil = '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;&a;&a;">]><ndm><omm>&b;</omm></ndm>'
    recs, f = parse_omm_xml(evil)
    assert not recs and "OMM_XML_PARSE" in codes(f)


OEM = """CCSDS_OEM_VERS = 2.0
CREATION_DATE = 2026-01-01T00:00:00
ORIGINATOR = TEST
META_START
OBJECT_NAME = TESTSAT
OBJECT_ID = 2026-001A
CENTER_NAME = EARTH
REF_FRAME = EME2000
TIME_SYSTEM = UTC
START_TIME = 2026-01-01T00:00:00
STOP_TIME = 2026-01-01T00:20:00
META_STOP
2026-01-01T00:00:00 7000 0 0 0 7.5 0
2026-01-01T00:01:00 6998 450 0 -0.48 7.48 0
2026-01-01T00:02:00 6992 899 0 -0.96 7.43 0
2026-01-01T00:20:00 5000 4900 0 -5.2 5.3 0
COVARIANCE_START
EPOCH = 2026-01-01T00:00:00
COV_REF_FRAME = RTN
1e-4
0 1e-3
0 0 1e-4
0 0 0 1e-8
0 0 0 0 1e-8
0 0 0 0 0 1e-8
COVARIANCE_STOP
"""


def test_oem_parse_gap_and_covariance():
    recs, f = parse_oem_kvn(OEM)
    assert len(recs) == 1
    r = recs[0]
    assert r.ephem_states.shape == (4, 6)
    assert "OEM_GAP" in codes(f)
    assert r.covariance is not None and r.covariance.frame == "RTN"


def test_oem_non_monotonic_rejected():
    bad = OEM.replace("2026-01-01T00:02:00 6992", "2026-01-01T00:00:30 6992")
    recs, f = parse_oem_kvn(bad)
    assert not recs and "OEM_NON_MONOTONIC" in codes(f)


CDM = """CCSDS_CDM_VERS = 1.0
CREATION_DATE = 2026-01-01T00:00:00
ORIGINATOR = TEST
MESSAGE_FOR = X
MESSAGE_ID = T1
TCA = 2026-01-02T00:00:00.000
MISS_DISTANCE = 100 [m]
OBJECT = OBJECT1
OBJECT_DESIGNATOR = 11111
REF_FRAME = GCRF
X = 7000 [km]
Y = 0 [km]
Z = 0 [km]
X_DOT = 0 [km/s]
Y_DOT = 7.5 [km/s]
Z_DOT = 0 [km/s]
{cov}
OBJECT = OBJECT2
OBJECT_DESIGNATOR = 22222
REF_FRAME = GCRF
X = 7000.1 [km]
Y = 0 [km]
Z = 0 [km]
X_DOT = 0 [km/s]
Y_DOT = 0 [km/s]
Z_DOT = 7.5 [km/s]
"""


def _cov_lines(diag_m2=(100.0, 400.0, 25.0)):
    from astral.core.parsers.cdm import COV_KEYS

    vals = {k: 0.0 for k in COV_KEYS}
    vals["CR_R"], vals["CT_T"], vals["CN_N"] = diag_m2
    vals["CRDOT_RDOT"] = vals["CTDOT_TDOT"] = vals["CNDOT_NDOT"] = 1e-4
    return "\n".join(f"{k} = {v}" for k, v in vals.items())


def test_cdm_units_and_missing_covariance():
    recs, f = parse_cdm_kvn(CDM.format(cov=_cov_lines()))
    assert len(recs) == 2
    c = recs[0].covariance.matrix
    assert c[0, 0] == pytest.approx(100e-6) and c[1, 1] == pytest.approx(400e-6)
    assert recs[1].covariance is None
    assert "CDM_COV_INCOMPLETE" in codes(f)
    assert recs[0].extra["cdm"]["originator_miss_distance_m"] == 100.0


def test_states_csv_schema_and_units():
    csv = "object_id,epoch,time_system,frame,x_km,y_km,z_km,vx_km_s,vy_km_s,vz_km_s\nA,2026-01-01T00:00:00,UTC,GCRF,7000000,0,0,0,7.5,0\n"
    res = ingest(csv, reference_time=Time("2026-01-01T00:00:00", scale="utc"))
    assert res.format == "STATES_CSV"
    assert "STATE_RADIUS_UNITS" in codes(res.findings)
    bad = "object_id,epoch\nA,2026-01-01T00:00:00\n"
    with pytest.raises(FormatError):
        detect_format(bad)


def test_states_json_requires_time_system():
    doc = {"schema": "astral-states/1", "objects": [{"object_id": "A", "epoch": "2026-01-01T00:00:00", "frame": "GCRF",
                                                     "position_km": [7000, 0, 0], "velocity_km_s": [0, 7.5, 0]}]}
    res = ingest(json.dumps(doc), reference_time=Time("2026-01-01T00:00:00", scale="utc"))
    assert not res.records and "STATE_TIME_SYSTEM" in codes(res.findings)


def test_record_round_trip():
    res = ingest(OEM, reference_time=Time("2026-01-01T00:00:00", scale="utc"))
    d = res.records[0].to_dict()
    r2 = OrbitalRecord.from_dict(json.loads(json.dumps(d)))
    assert np.allclose(r2.ephem_states, res.records[0].ephem_states)
    assert abs((r2.epoch - res.records[0].epoch).sec) < 1e-6


def test_unknown_format():
    with pytest.raises(FormatError):
        detect_format("hello world")
