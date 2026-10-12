"""Physical constants used by ASTRAL. Units: km, s, kg unless stated.

Values and their sources are listed so a reviewer can check them; do not change
a value without updating SCIENTIFIC_METHODS.md.
"""

# WGS-84 / EGM-96 values (NIMA TR8350.2, 3rd ed.). SGP4 itself uses WGS-72
# internally (see sgp4 library); these are used only by ASTRAL's own
# numerical propagator for scenario comparisons.
MU_EARTH_KM3_S2 = 398600.4418
R_EARTH_KM = 6378.137
J2_EARTH = 1.08262668e-3

# Earth rotation rate, IERS conventions (rad/s).
OMEGA_EARTH_RAD_S = 7.292115e-5

SECONDS_PER_DAY = 86400.0
