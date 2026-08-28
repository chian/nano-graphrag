"""rarefaction -- the incidence estimator, controller, and Episode kernel.

Chartered in ``docs/ACQUISITION_LOOP.md`` (phases 4A and 4E-a). This package
is the bottom layer of the repository: anything may import it; it imports
nothing outside the standard library. It performs no I/O, holds no provider
access, and never consults a model. Every number it emits is arithmetic over
observed credits.

The incidence target modules:

- :mod:`rarefaction.accumulator` -- immutable eligible incidence samples,
  exact rolling rarefaction with pairwise uncertainty, and bias-corrected
  incidence Chao2 in a role-based numeric estimate, under a frozen generic
  channel declaration.
- :mod:`rarefaction.controller` -- versioned numerical role-based verdicts.
- :mod:`rarefaction.scopes` -- frozen per-channel estimator/controller
  registries for path scopes.
- :mod:`rarefaction.episode` -- the composable form: ``Grain``, ``Leaf``,
  ``Episode`` (a unit of its parent), ``Context``.

Semantics the kernel enforces, cited from the charter:

- **Measured, never asked.** No model emits a count, an estimate, or a
  verdict.
- **Repeats are incidence, not replication.** Repeats inside one eligible unit
  disappear; recurrence across units changes Q1/Q2 without increasing D.
- **No silent failures.** A disabled crediter announces itself on every
  record it touches; verdicts carry the numbers that produced them; a safety
  bound reports ``bound_hit``, distinct from a yield stop; a source's own
  early end is named.
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
from .controller import CONTROLLER_VERSION, ControllerConfig, ControllerVerdict, NumericalController
from .scopes import Path, Scope, ScopedYield
from .episode import (
    COUNTING_ENDS,
    END_BOUND_HIT,
    END_EXHAUSTED,
    END_INCOMPLETE,
    END_REASON_UNIT_BOUND,
    END_SOURCE_FAILED,
    END_YIELD_STOP,
    ENDS,
    SOURCE_END_KINDS,
    Contribution,
    CreditResult,
    EpisodeRecord,
    SourceEnd,
    UnitRecord,
    Acquirable,
    Context,
    Episode,
    EpochMutation,
    EpisodeView,
    Grain,
    Leaf,
    UnitSource,
    leaves,
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
    "CONTROLLER_VERSION",
    "ControllerConfig",
    "ControllerVerdict",
    "NumericalController",
    "Path",
    "Scope",
    "ScopedYield",
    "COUNTING_ENDS",
    "END_BOUND_HIT",
    "END_EXHAUSTED",
    "END_INCOMPLETE",
    "END_REASON_UNIT_BOUND",
    "END_SOURCE_FAILED",
    "END_YIELD_STOP",
    "ENDS",
    "SOURCE_END_KINDS",
    "Contribution",
    "CreditResult",
    "EpisodeRecord",
    "SourceEnd",
    "UnitRecord",
    "Acquirable",
    "Context",
    "Episode",
    "EpochMutation",
    "EpisodeView",
    "Grain",
    "Leaf",
    "UnitSource",
    "leaves",
]
