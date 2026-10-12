"""SGP4 reference test against Vallado et al. (2006) verification output.

Source: D. Vallado, P. Crawford, R. Hujsak, T.S. Kelso, "Revisiting Spacetrack
Report #3", AIAA 2006-6753. Files SGP4-VER.TLE (inputs) and tcppver.out
(reference output of the authors' C++ implementation), as redistributed with
the python ``sgp4`` package (MIT licence).

What this checks: ASTRAL's TLE parser -> SGP4Propagator -> UTC time handling
path reproduces the published reference states. It does not prove SGP4
itself is accurate against the real objects; it proves ASTRAL invokes it
correctly.

Tolerance: 1e-6 km (1 mm) in position, 1e-9 km/s in velocity. The reference
is printed to 1e-8 km / 1e-9 km/s; residual differences come only from
floating-point operation ordering and from re-deriving the propagation
instant via ASTRAL's (jd_day, jd_frac) path rather than minutes-since-epoch.
"""

from pathlib import Path

import numpy as np
import pytest  # noqa: F401
from astropy.time import Time

from astral.core.parsers.tle import parse_tle_text
from astral.core.propagation import SGP4Propagator

HERE = Path(__file__).parent


def _cases():
    tle_lines = [ln.rstrip("\n") for ln in (HERE / "SGP4-VER.TLE").read_text().splitlines() if ln and not ln.startswith("#")]
    tles = {}
    for i in range(0, len(tle_lines) - 1):
        if tle_lines[i].startswith("1 ") and tle_lines[i + 1].startswith("2 "):
            tles[tle_lines[i][2:7].strip()] = (tle_lines[i][:69], tle_lines[i + 1][:69])
    ref: dict[str, list[list[float]]] = {}
    cur = None
    for ln in (HERE / "tcppver.out").read_text().splitlines():
        parts = ln.split()
        if len(parts) == 2 and parts[1] == "xx":
            cur = parts[0]
            ref[cur] = []
        elif cur and len(parts) >= 7:
            ref[cur].append([float(x) for x in parts[:7]])
    return [(k, tles[k], ref[k]) for k in ref if k in tles]


CASES = _cases()


def test_reference_files_loaded():
    assert len(CASES) >= 25


@pytest.mark.parametrize("satnum,lines,rows", CASES, ids=[c[0] for c in CASES])
def test_sgp4_matches_vallado(satnum, lines, rows):
    recs, findings = parse_tle_text("\n".join(lines))
    if satnum in ("33333", "33334", "33335"):
        # Vallado's deliberately malformed error-case sets: ASTRAL must refuse them.
        assert not recs and "TLE_CHECKSUM" in {f.code for f in findings}
        return
    assert recs, f"{satnum}: unexpectedly rejected ({[f.code for f in findings]})"
    prop = SGP4Propagator(recs[0])
    sat = prop.sat
    start = Time(sat.jdsatepoch, sat.jdsatepochF, format="jd", scale="utc")
    rows = np.asarray(rows)
    res = prop.propagate(start, rows[:, 0] * 60.0)
    ok = res.valid
    assert ok.any()
    dr = np.abs(res.r_km[ok] - rows[ok, 1:4]).max()
    dv = np.abs(res.v_km_s[ok] - rows[ok, 4:7]).max()
    assert dr < 1e-6, f"{satnum}: max position difference {dr} km"
    assert dv < 1e-9, f"{satnum}: max velocity difference {dv} km/s"
