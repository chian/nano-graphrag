"""Incidence estimation for the generic acquisition method.

This package owns the estimator mathematics and its typed numeric output. It
does not own the Episode loop, nesting, runtime identity, scope lifecycle,
controller, memory, persistence, or any acquisition surface.
"""

from .accumulator import (
    CHANNEL_SCHEMA_VERSION,
    INCIDENCE_ESTIMATOR_VERSION,
    NUMERIC_BAND_VERSION,
    RAREFACTION_FORMULA_VERSION,
    REACHABLE_TOTAL_FORMULA_VERSION,
    STATUS_INSUFFICIENT,
    STATUS_NORMAL,
    STATUS_UNIDENTIFIABLE,
    UNCERTAINTY_CHEBYSHEV,
    UNCERTAINTY_EXACT,
    UNCERTAINTY_UNAVAILABLE,
    ChannelSchema,
    IncidenceEstimate,
    IncidenceEstimator,
    NumericBand,
    UnitYield,
)

__all__ = [
    "STATUS_NORMAL",
    "STATUS_INSUFFICIENT",
    "STATUS_UNIDENTIFIABLE",
    "UNCERTAINTY_UNAVAILABLE",
    "UNCERTAINTY_EXACT",
    "UNCERTAINTY_CHEBYSHEV",
    "NUMERIC_BAND_VERSION",
    "INCIDENCE_ESTIMATOR_VERSION",
    "RAREFACTION_FORMULA_VERSION",
    "REACHABLE_TOTAL_FORMULA_VERSION",
    "CHANNEL_SCHEMA_VERSION",
    "ChannelSchema",
    "NumericBand",
    "UnitYield",
    "IncidenceEstimate",
    "IncidenceEstimator",
]
