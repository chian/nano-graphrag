"""The generic, nestable acquisition method and its bindable components.

``Episode`` owns the method loop and tree. Surfaces compose sources, leaves,
acceptance projections, numerical control, and post-verdict hooks around it.
Rarefaction is one estimator component consumed by the method runtime.
"""

from .controller import (
    CONTROLLER_VERSION,
    ControllerConfig,
    ControllerVerdict,
    NumericalController,
)
from .runtime import Path, Scope, ScopedYield
from .identities import (
    IDENTITY_VERSION,
    EpisodeRef,
    StructuralPath,
    UnitRef,
    normalize_structural_path,
)
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
    Acquirable,
    Context,
    Contribution,
    CreditResult,
    Episode,
    EpisodeRecord,
    EpisodeView,
    EpochMutation,
    Grain,
    Leaf,
    SourceEnd,
    UnitRecord,
    UnitSource,
    leaves,
)

__all__ = [
    "CONTROLLER_VERSION",
    "ControllerConfig",
    "ControllerVerdict",
    "NumericalController",
    "Path",
    "Scope",
    "ScopedYield",
    "IDENTITY_VERSION",
    "EpisodeRef",
    "StructuralPath",
    "UnitRef",
    "normalize_structural_path",
    "COUNTING_ENDS",
    "END_BOUND_HIT",
    "END_EXHAUSTED",
    "END_INCOMPLETE",
    "END_REASON_UNIT_BOUND",
    "END_SOURCE_FAILED",
    "END_YIELD_STOP",
    "ENDS",
    "SOURCE_END_KINDS",
    "Acquirable",
    "Context",
    "Contribution",
    "CreditResult",
    "Episode",
    "EpisodeRecord",
    "EpisodeView",
    "EpochMutation",
    "Grain",
    "Leaf",
    "SourceEnd",
    "UnitRecord",
    "UnitSource",
    "leaves",
]
