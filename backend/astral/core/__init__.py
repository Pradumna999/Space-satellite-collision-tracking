"""Scientific core. Importable and usable without the web application.

Nothing in this package may import from ``astral.api``, ``astral.db`` or
``astral.services``; the dependency direction is strictly web -> core.
"""

from astropy.utils import iers as _iers

# Results must not depend on network access: never fetch IERS tables at run
# time. The bundled tables' validity is checked explicitly (frames.eop_covered,
# timeutil.leap_second_table_expiry).
_iers.conf.auto_download = False
_iers.conf.auto_max_age = None
_iers.conf.iers_degraded_accuracy = "ignore"
