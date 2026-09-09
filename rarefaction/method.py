"""Paired incidence estimation and numerical control.

One :class:`IncidenceEstimator` owns one frozen
``(scope_path, epoch, channel)`` declaration. An eligible acquisition unit
contributes one immutable set of opaque stable identity strings. Repeated
identities inside the unit disappear before any count is changed; recurrence
across eligible units changes incidence frequencies without increasing
observed richness.

The estimator-controller component owns a failure-aware joint preferential
discovery model, its matching numerical controller, and the injected boundary
through which a future numerical threshold policy can update thresholds. It
owns no Episode loop, scope tree, I/O, or model call.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field
from numbers import Real
from statistics import NormalDist
from typing import Callable, Iterable, Mapping, Optional, Sequence

__all__ = [
    "STATUS_NORMAL",
    "STATUS_INSUFFICIENT",
    "STATUS_UNIDENTIFIABLE",
    "UNCERTAINTY_UNAVAILABLE",
    "UNCERTAINTY_EXACT",
    "UNCERTAINTY_CHEBYSHEV",
    "UNCERTAINTY_LAPLACE",
    "NUMERIC_BAND_VERSION",
    "INCIDENCE_ESTIMATOR_VERSION",
    "RAREFACTION_FORMULA_VERSION",
    "REACHABLE_TOTAL_FORMULA_VERSION",
    "VOLUME_CREDIT_VERSION",
    "CHANNEL_SCHEMA_VERSION",
    "ChannelSchema",
    "NumericBand",
    "UnitYield",
    "IncidenceEstimate",
    "IncidenceEstimator",
    "CONTROLLER_VERSION",
    "ControllerConfig",
    "ControllerVerdict",
    "VolumeCredit",
    "IncidenceReport",
    "ControlStep",
    "ThresholdAdapter",
    "EstimatorController",
    "OBSERVATION_OBSERVED",
    "OBSERVATION_FAILED",
    "OBSERVATION_EXCLUDED",
]


# Numeric status and uncertainty vocabularies are declared once. A consumer
# branches on these codes, never on text.
STATUS_NORMAL = 0
STATUS_INSUFFICIENT = -1
STATUS_UNIDENTIFIABLE = -2

UNCERTAINTY_UNAVAILABLE = -1
UNCERTAINTY_EXACT = 0
UNCERTAINTY_CHEBYSHEV = 1
UNCERTAINTY_LAPLACE = 2

NUMERIC_BAND_VERSION = "numeric_band_v2"
INCIDENCE_ESTIMATOR_VERSION = "preferential_incidence_estimator_v2"
RAREFACTION_FORMULA_VERSION = "joint_preferential_discovery_v1"
REACHABLE_TOTAL_FORMULA_VERSION = "integrated_future_discovery_v1"
CHANNEL_SCHEMA_VERSION = "channel_schema_v2"

DEFAULT_WINDOW_SIZE = 8
DEFAULT_SUBSAMPLE_SIZE = 4
DEFAULT_ALPHA = 0.05
DEFAULT_EPOCH = "epoch-0"
DEFAULT_CHANNEL = "overall"

OBSERVATION_OBSERVED = 0
OBSERVATION_FAILED = 1
OBSERVATION_EXCLUDED = 2
_OBSERVATION_STATUSES = {
    OBSERVATION_OBSERVED,
    OBSERVATION_FAILED,
    OBSERVATION_EXCLUDED,
}

_QUADRATURE_LATENT = (
    -6.3639478888298395, -5.190093591304782, -4.1962077112690155,
    -3.289082424398767, -2.432436827009758, -1.6067100690287297,
    -0.7991290683245481, 0.0, 0.7991290683245481, 1.6067100690287297,
    2.432436827009758, 3.289082424398767, 4.1962077112690155,
    5.190093591304782, 6.3639478888298395,
)
_LOG_QUADRATURE_WEIGHTS = (
    -20.87529295151139, -14.330441330013045, -9.782660903562084,
    -6.458364196415659, -4.053253993024127, -2.414435562921691,
    -1.4590272451296604, -1.144888133870829, -1.4590272451296604,
    -2.414435562921691, -4.053253993024127, -6.458364196415659,
    -9.782660903562084, -14.330441330013045, -20.87529295151139,
)


def _logsumexp(values: Sequence[float]) -> float:
    peak = max(values)
    return peak + math.log(sum(math.exp(value - peak) for value in values))


def _softplus(value: float) -> float:
    if value > 0.0:
        return value + math.log1p(math.exp(-value))
    return math.log1p(math.exp(value))


def _finite_number(name: str, value: Real) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError(f"{name} must be a real number, got {type(value).__name__}")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite, got {value!r}")
    return number


@dataclass(frozen=True)
class ChannelSchema:
    """Frozen declaration of one scope's generic incidence channels.

    A single-channel schema sends the unit's declared credit tuple directly to
    that channel. A partition schema declares base channels plus one union
    channel. ``union_members`` names which base channels form that union;
    ``controller_channels`` names the independently estimated axes supplied to
    the numerical controller's vector. The two roles are deliberately
    separate: an application can require a completed-row axis without pooling
    row identities into its ordinary-column richness estimate.

    The kernel validates every base membership and derives the union; the
    application's pooled credit tuple is only a check on that derivation.
    """

    base_channels: tuple[str, ...]
    union_channel: Optional[str] = None
    overlap_allowed: bool = False
    union_members: Optional[tuple[str, ...]] = None
    controller_channels: Optional[tuple[str, ...]] = None
    version: str = field(default=CHANNEL_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.base_channels, tuple) or not self.base_channels:
            raise ValueError("base_channels must be a non-empty tuple")
        for channel in self.base_channels:
            if not isinstance(channel, str) or not channel.strip():
                raise ValueError("every channel name must be a non-empty string")
        if len(set(self.base_channels)) != len(self.base_channels):
            raise ValueError("base channel names must be unique")
        if self.union_channel is None:
            if len(self.base_channels) != 1:
                raise ValueError(
                    "a schema with several base channels must declare one "
                    "kernel-derived union_channel"
                )
        else:
            if not isinstance(self.union_channel, str) or not self.union_channel.strip():
                raise ValueError("union_channel must be a non-empty string")
            if self.union_channel in self.base_channels:
                raise ValueError("union_channel must be distinct from every base channel")
        union_members = (
            self.base_channels
            if self.union_members is None
            else tuple(str(channel) for channel in self.union_members)
        )
        if self.union_channel is None and union_members != self.base_channels:
            raise ValueError("a single-channel schema cannot narrow union_members")
        if not union_members or len(set(union_members)) != len(union_members):
            raise ValueError("union_members must be a non-empty unique tuple")
        if not set(union_members) <= set(self.base_channels):
            raise ValueError("union_members must be declared base channels")
        controller_channels = (
            self.channels
            if self.controller_channels is None
            else tuple(str(channel) for channel in self.controller_channels)
        )
        if not controller_channels or len(set(controller_channels)) != len(controller_channels):
            raise ValueError("controller_channels must be a non-empty unique tuple")
        if not set(controller_channels) <= set(self.channels):
            raise ValueError("controller_channels must be declared schema channels")
        object.__setattr__(self, "union_members", union_members)
        object.__setattr__(self, "controller_channels", controller_channels)
        if not isinstance(self.overlap_allowed, bool):
            raise TypeError("overlap_allowed must be a bool")
        if not isinstance(self.version, str) or not self.version.strip():
            raise ValueError("channel schema version must be a non-empty string")

    @classmethod
    def single(cls, channel: str = DEFAULT_CHANNEL) -> "ChannelSchema":
        return cls(base_channels=(channel,))

    @classmethod
    def partition(
        cls,
        base_channels: Iterable[str],
        *,
        union_channel: str = DEFAULT_CHANNEL,
        overlap_allowed: bool = False,
        union_members: Optional[Iterable[str]] = None,
        controller_channels: Optional[Iterable[str]] = None,
    ) -> "ChannelSchema":
        return cls(
            base_channels=tuple(base_channels),
            union_channel=union_channel,
            overlap_allowed=overlap_allowed,
            union_members=(
                tuple(union_members) if union_members is not None else None
            ),
            controller_channels=(
                tuple(controller_channels)
                if controller_channels is not None
                else None
            ),
        )

    @property
    def primary_channel(self) -> str:
        return self.union_channel or self.base_channels[0]

    @property
    def channels(self) -> tuple[str, ...]:
        if self.union_channel is None:
            return self.base_channels
        return self.base_channels + (self.union_channel,)

    @staticmethod
    def _distinct(values: Iterable[str]) -> tuple[str, ...]:
        return tuple(dict.fromkeys(str(value) for value in values))

    def project(
        self,
        credits: Iterable[str],
        memberships: Mapping[str, Iterable[str]],
        *,
        active: bool,
    ) -> dict[str, tuple[str, ...]]:
        """Validate one unit and return distinct membership for every channel."""

        credit_tuple = self._distinct(credits)
        groups = {
            str(channel): self._distinct(values)
            for channel, values in memberships.items()
        }
        if not active:
            if credit_tuple or groups:
                raise ValueError(
                    "a crediting-disabled unit must carry no credits or channel memberships"
                )
            return {channel: () for channel in self.channels}

        if self.union_channel is None:
            if groups:
                raise ValueError(
                    f"single-channel schema {self.primary_channel!r} accepts no "
                    f"membership groups; received {sorted(groups)}"
                )
            return {self.primary_channel: credit_tuple}

        expected = set(self.base_channels)
        actual = set(groups)
        if actual != expected:
            raise ValueError(
                "channel memberships do not match the frozen schema: "
                f"undeclared {sorted(actual - expected)}, "
                f"missing {sorted(expected - actual)}"
            )

        owner: dict[str, str] = {}
        for channel in self.base_channels:
            for identity in groups[channel]:
                previous = owner.get(identity)
                if (
                    previous is not None
                    and previous != channel
                    and not self.overlap_allowed
                ):
                    raise ValueError(
                        f"identity {identity!r} belongs to overlapping channels "
                        f"{previous!r} and {channel!r}, but overlap_allowed=False"
                    )
                owner.setdefault(identity, channel)

        derived: list[str] = []
        derived_seen: set[str] = set()
        for channel in self.union_members or ():
            for identity in groups[channel]:
                if identity not in derived_seen:
                    derived_seen.add(identity)
                    derived.append(identity)

        supplied = set(credit_tuple)
        calculated = set(derived)
        if supplied != calculated:
            raise ValueError(
                "pooled credits do not equal the kernel-derived union: "
                f"not in memberships {sorted(supplied - calculated)}, "
                f"not in pooled credits {sorted(calculated - supplied)}"
            )

        projected = {channel: groups[channel] for channel in self.base_channels}
        projected[self.union_channel] = tuple(derived)
        return projected

    def as_record(self) -> dict:
        return {
            "version": self.version,
            "base_channels": list(self.base_channels),
            "union_channel": self.union_channel or "",
            "overlap_allowed": self.overlap_allowed,
            "union_members": list(self.union_members or ()),
            "controller_channels": list(self.controller_channels or ()),
        }


@dataclass(frozen=True)
class NumericBand:
    """One finite numeric estimate and its numeric uncertainty contract."""

    value: float
    lower: float
    upper: float
    status_code: int
    uncertainty_code: int
    alpha: float

    def __post_init__(self) -> None:
        value = _finite_number("NumericBand.value", self.value)
        lower = _finite_number("NumericBand.lower", self.lower)
        upper = _finite_number("NumericBand.upper", self.upper)
        alpha = _finite_number("NumericBand.alpha", self.alpha)
        object.__setattr__(self, "value", value)
        object.__setattr__(self, "lower", lower)
        object.__setattr__(self, "upper", upper)
        object.__setattr__(self, "alpha", alpha)

        if self.status_code not in {
            STATUS_NORMAL,
            STATUS_INSUFFICIENT,
            STATUS_UNIDENTIFIABLE,
        }:
            raise ValueError(f"unknown status_code {self.status_code!r}")
        if self.status_code != STATUS_NORMAL:
            coded = float(self.status_code)
            if (value, lower, upper) != (coded, coded, coded):
                raise ValueError(
                    "a coded band has value=lower=upper=status_code"
                )
            if self.uncertainty_code != UNCERTAINTY_UNAVAILABLE or alpha != -1.0:
                raise ValueError(
                    "a coded band has uncertainty_code=alpha=-1"
                )
            return

        if self.uncertainty_code not in {
            UNCERTAINTY_EXACT,
            UNCERTAINTY_CHEBYSHEV,
            UNCERTAINTY_LAPLACE,
        }:
            raise ValueError(
                f"normal band has unknown uncertainty_code {self.uncertainty_code!r}"
            )
        if value < 0.0 or lower < 0.0 or upper < 0.0:
            raise ValueError("a normal numeric band is non-negative")
        if not lower <= value <= upper:
            raise ValueError(
                f"numeric band must satisfy lower <= value <= upper, got "
                f"{lower}, {value}, {upper}"
            )
        if self.uncertainty_code == UNCERTAINTY_EXACT and alpha != 0.0:
            raise ValueError("an exact band has alpha=0")
        if self.uncertainty_code == UNCERTAINTY_CHEBYSHEV and not 0.0 < alpha < 1.0:
            raise ValueError("a Chebyshev band has 0 < alpha < 1")
        if self.uncertainty_code == UNCERTAINTY_LAPLACE and not 0.0 < alpha < 1.0:
            raise ValueError("a Laplace band has 0 < alpha < 1")

    @classmethod
    def exact(cls, value: Real) -> "NumericBand":
        point = _finite_number("exact value", value)
        return cls(
            value=point,
            lower=point,
            upper=point,
            status_code=STATUS_NORMAL,
            uncertainty_code=UNCERTAINTY_EXACT,
            alpha=0.0,
        )

    @classmethod
    def coded(cls, status_code: int) -> "NumericBand":
        if status_code not in {STATUS_INSUFFICIENT, STATUS_UNIDENTIFIABLE}:
            raise ValueError(
                "coded bands use STATUS_INSUFFICIENT or STATUS_UNIDENTIFIABLE"
            )
        coded = float(status_code)
        return cls(
            value=coded,
            lower=coded,
            upper=coded,
            status_code=status_code,
            uncertainty_code=UNCERTAINTY_UNAVAILABLE,
            alpha=-1.0,
        )

    @classmethod
    def chebyshev(
        cls,
        value: Real,
        variance: Real,
        alpha: Real,
        *,
        lower_floor: Real = 0.0,
    ) -> "NumericBand":
        point = _finite_number("Chebyshev value", value)
        variance_value = _finite_number("Chebyshev variance", variance)
        alpha_value = _finite_number("Chebyshev alpha", alpha)
        floor = _finite_number("Chebyshev lower_floor", lower_floor)
        if variance_value < 0.0:
            raise ArithmeticError(
                f"Chebyshev variance must be non-negative, got {variance_value}"
            )
        if not 0.0 < alpha_value < 1.0:
            raise ValueError(f"alpha must satisfy 0 < alpha < 1, got {alpha!r}")
        if floor < 0.0:
            raise ValueError(f"lower_floor must be non-negative, got {floor}")
        radius = math.sqrt(variance_value / alpha_value)
        return cls(
            value=point,
            lower=max(floor, point - radius),
            upper=point + radius,
            status_code=STATUS_NORMAL,
            uncertainty_code=UNCERTAINTY_CHEBYSHEV,
            alpha=alpha_value,
        )

    @classmethod
    def laplace(
        cls,
        value: Real,
        variance: Real,
        alpha: Real,
        *,
        lower_floor: Real = 0.0,
    ) -> "NumericBand":
        """Normal/Laplace approximation around a fitted joint model."""

        point = _finite_number("Laplace value", value)
        variance_value = _finite_number("Laplace variance", variance)
        alpha_value = _finite_number("Laplace alpha", alpha)
        floor = _finite_number("Laplace lower_floor", lower_floor)
        if variance_value < 0.0:
            raise ArithmeticError(
                f"Laplace variance must be non-negative, got {variance_value}"
            )
        if not 0.0 < alpha_value < 1.0:
            raise ValueError(f"alpha must satisfy 0 < alpha < 1, got {alpha!r}")
        if floor < 0.0:
            raise ValueError(f"lower_floor must be non-negative, got {floor}")
        radius = NormalDist().inv_cdf(1.0 - alpha_value / 2.0) * math.sqrt(
            variance_value
        )
        return cls(
            value=point,
            lower=max(floor, point - radius),
            upper=point + radius,
            status_code=STATUS_NORMAL,
            uncertainty_code=UNCERTAINTY_LAPLACE,
            alpha=alpha_value,
        )

    def as_record(self) -> dict:
        return {
            "value": self.value,
            "lower": self.lower,
            "upper": self.upper,
            "status_code": self.status_code,
            "uncertainty_code": self.uncertainty_code,
            "alpha": self.alpha,
        }


@dataclass(frozen=True)
class UnitYield:
    """One unit's immutable incidence contribution at observation time.

    ``sample_identities`` is empty when ``eligible`` is false. The unit's
    accepted credits remain on the Episode-owned ``UnitRecord`` for audit, but an
    inactive or bound-cut unit cannot enter incidence state.
    """

    unit_index: int
    unit_label: str
    sample_identities: frozenset[str]
    new_identities: tuple[str, ...]
    repeat_identities: tuple[str, ...]
    credits_observed: int
    cumulative_distinct: int
    eligible: bool
    observation_status: int = OBSERVATION_OBSERVED
    crediting_disabled: bool = False
    counts_toward_verdict: bool = True

    @property
    def productive(self) -> bool:
        return bool(self.new_identities)

    def as_record(self) -> dict:
        return {
            "unit_index": self.unit_index,
            "unit_label": self.unit_label,
            "eligible": self.eligible,
            "observation_status": self.observation_status,
            "incidence_sample": sorted(self.sample_identities),
            "new": len(self.new_identities),
            "repeats": len(self.repeat_identities),
            "credits_observed": self.credits_observed,
            "cumulative_distinct": self.cumulative_distinct,
            "crediting_disabled": self.crediting_disabled,
            "counts_toward_verdict": self.counts_toward_verdict,
        }


@dataclass(frozen=True)
class IncidenceEstimate:
    """Estimator-neutral numeric report for one scope, epoch, and channel."""

    scope_path: tuple[tuple[str, str], ...]
    epoch: str
    channel: str
    incidence_samples: int
    observed_results: NumericBand
    expected_results: NumericBand
    remaining_results: NumericBand
    control_statistics: Mapping[str, NumericBand] = field(default_factory=dict)
    diagnostics: Mapping[str, Real] = field(default_factory=dict)
    formula_versions: Mapping[str, str] = field(default_factory=dict)
    method_version: str = INCIDENCE_ESTIMATOR_VERSION
    band_version: str = NUMERIC_BAND_VERSION
    channel_schema_version: str = CHANNEL_SCHEMA_VERSION

    def __post_init__(self) -> None:
        statistics = dict(self.control_statistics)
        if any(not isinstance(value, NumericBand) for value in statistics.values()):
            raise TypeError("control_statistics values must be NumericBand values")
        diagnostics = {
            str(name): _finite_number(f"diagnostic {name!r}", value)
            for name, value in self.diagnostics.items()
        }
        versions = {str(name): str(value) for name, value in self.formula_versions.items()}
        if any(not name or not value for name, value in versions.items()):
            raise ValueError("formula_versions names and values must be non-empty")
        object.__setattr__(self, "control_statistics", statistics)
        object.__setattr__(self, "diagnostics", diagnostics)
        object.__setattr__(self, "formula_versions", versions)

    def as_record(self) -> dict:
        return {
            "scope_path": [list(segment) for segment in self.scope_path],
            "epoch": self.epoch,
            "channel": self.channel,
            "method_version": self.method_version,
            "band_version": self.band_version,
            "channel_schema_version": self.channel_schema_version,
            "formula_versions": dict(self.formula_versions),
            "incidence_samples": self.incidence_samples,
            "observed_results": self.observed_results.as_record(),
            "expected_results": self.expected_results.as_record(),
            "remaining_results": self.remaining_results.as_record(),
            "control_statistics": {
                name: value.as_record()
                for name, value in self.control_statistics.items()
            },
            "diagnostics": dict(self.diagnostics),
            "status_codes": {
                "normal": STATUS_NORMAL,
                "insufficient": STATUS_INSUFFICIENT,
                "unidentifiable": STATUS_UNIDENTIFIABLE,
            },
            "uncertainty_codes": {
                "unavailable": UNCERTAINTY_UNAVAILABLE,
                "exact": UNCERTAINTY_EXACT,
                "chebyshev": UNCERTAINTY_CHEBYSHEV,
                "laplace": UNCERTAINTY_LAPLACE,
            },
        }


class IncidenceEstimator:
    """Accumulate eligible incidence samples and emit an estimate record."""

    @staticmethod
    def validate_parameters(window_size: int, subsample_size: int, alpha: Real) -> None:
        if isinstance(window_size, bool) or not isinstance(window_size, int):
            raise TypeError("window_size (W) must be an integer")
        if isinstance(subsample_size, bool) or not isinstance(subsample_size, int):
            raise TypeError("subsample_size (m) must be an integer")
        if window_size < 2:
            raise ValueError(f"window_size (W) must be >= 2, got {window_size}")
        if not 1 <= subsample_size < window_size:
            raise ValueError(
                "subsample_size (m) must satisfy 1 <= m < W, got "
                f"m={subsample_size}, W={window_size}"
            )
        alpha_value = _finite_number("alpha", alpha)
        if not 0.0 < alpha_value < 1.0:
            raise ValueError(f"alpha must satisfy 0 < alpha < 1, got {alpha!r}")

    def __init__(
        self,
        window_size: int = DEFAULT_WINDOW_SIZE,
        subsample_size: int = DEFAULT_SUBSAMPLE_SIZE,
        alpha: Real = DEFAULT_ALPHA,
        *,
        scope_path: tuple[tuple[str, str], ...] = (("scope", "default"),),
        epoch: str = DEFAULT_EPOCH,
        channel: str = DEFAULT_CHANNEL,
    ) -> None:
        self.validate_parameters(window_size, subsample_size, alpha)
        normalized_path = self._normalize_path(scope_path)
        if not isinstance(epoch, str) or not epoch.strip():
            raise ValueError("epoch must be a non-empty stable identifier")
        if not isinstance(channel, str) or not channel.strip():
            raise ValueError("channel must be a non-empty stable identifier")

        self.window_size = window_size
        self.subsample_size = subsample_size
        self.alpha = float(alpha)
        self.scope_path = normalized_path
        self.epoch = epoch
        self.channel = channel

        self._samples: list[frozenset[str]] = []
        self._incidence: Counter[str] = Counter()
        self._first_seen_order: list[str] = []
        self._unit_labels: list[str] = []
        self._unit_statuses: list[int] = []
        self._new_counts: list[Optional[int]] = []
        self._fit_parameters = [math.log(0.25), math.log(0.05), 0.0, 0.0]
        self._fit_inverse_hessian = [
            [1.0 if row == column else 0.0 for column in range(4)]
            for row in range(4)
        ]
        self._coupling_was_identifiable = False
        self._fit_cache: Optional[tuple[int, IncidenceEstimate]] = None

    @staticmethod
    def _normalize_path(
        scope_path: tuple[tuple[str, str], ...],
    ) -> tuple[tuple[str, str], ...]:
        if not isinstance(scope_path, tuple) or not scope_path:
            raise ValueError(
                "scope_path must be a non-empty tuple of (grain name, key) pairs"
            )
        normalized: list[tuple[str, str]] = []
        for segment in scope_path:
            if not isinstance(segment, tuple) or len(segment) != 2:
                raise ValueError(
                    f"scope path segment {segment!r} is not a two-item tuple"
                )
            grain, key = str(segment[0]), str(segment[1])
            if not grain or not key:
                raise ValueError("scope path grain names and keys must be non-empty")
            normalized.append((grain, key))
        return tuple(normalized)

    @property
    def units(self) -> int:
        """Eligible incidence sample count in the current epoch."""

        return len(self._samples)

    @property
    def distinct(self) -> int:
        return len(self._incidence)

    def observe(
        self,
        unit_label: str,
        credits: Iterable[str],
        *,
        observation_status: int = OBSERVATION_OBSERVED,
    ) -> UnitYield:
        """Record one unit, constructing at most one incidence sample.

        An observed unit enters the current estimator arithmetic. A failed
        unit is retained in failure diagnostics, and an excluded unit is
        retained only for audit. Neither changes the current implementation's
        ``T``, ``D``, ``Q1``, ``Q2``, rolling window, or controller streak.
        """

        if observation_status not in _OBSERVATION_STATUSES:
            raise ValueError(f"unknown observation_status {observation_status!r}")

        distinct_input: list[str] = []
        within_unit: set[str] = set()
        for raw in credits:
            identity = str(raw)
            if identity in within_unit:
                continue
            within_unit.add(identity)
            distinct_input.append(identity)

        eligible = observation_status == OBSERVATION_OBSERVED
        new: list[str] = []
        repeats: list[str] = []
        sample = frozenset(distinct_input) if eligible else frozenset()
        if eligible:
            for identity in distinct_input:
                if self._incidence[identity] == 0:
                    self._first_seen_order.append(identity)
                    new.append(identity)
                else:
                    repeats.append(identity)
                self._incidence[identity] += 1
            self._samples.append(sample)

        unit_index = len(self._unit_labels)
        self._unit_labels.append(str(unit_label))
        self._unit_statuses.append(observation_status)
        self._new_counts.append(len(new) if eligible else None)
        self._fit_cache = None
        return UnitYield(
            unit_index=unit_index,
            unit_label=str(unit_label),
            sample_identities=sample,
            new_identities=tuple(new),
            repeat_identities=tuple(repeats),
            credits_observed=len(distinct_input),
            cumulative_distinct=self.distinct,
            eligible=eligible,
            observation_status=observation_status,
            crediting_disabled=observation_status == OBSERVATION_FAILED,
            counts_toward_verdict=observation_status == OBSERVATION_OBSERVED,
        )

    def unit_labels(self) -> tuple[str, ...]:
        return tuple(self._unit_labels)

    def unit_activity(self) -> tuple[bool, ...]:
        return tuple(
            status == OBSERVATION_OBSERVED for status in self._unit_statuses
        )

    def unit_eligibility(self) -> tuple[bool, ...]:
        return tuple(
            status == OBSERVATION_OBSERVED for status in self._unit_statuses
        )

    def unit_statuses(self) -> tuple[int, ...]:
        return tuple(self._unit_statuses)

    def incidence_samples(self) -> tuple[frozenset[str], ...]:
        """Eligible immutable samples in observation order."""

        return tuple(self._samples)

    def identity_incidence(self) -> dict[str, int]:
        """All-epoch sample frequency per identity."""

        return dict(self._incidence)

    def _attempt_data(self) -> tuple[tuple[int, ...], tuple[float, ...]]:
        statuses: list[int] = []
        discoveries: list[float] = []
        for status, count in zip(self._unit_statuses, self._new_counts):
            if status == OBSERVATION_EXCLUDED:
                continue
            statuses.append(status)
            discoveries.append(float(count or 0) if status == OBSERVATION_OBSERVED else 0.0)
        return tuple(statuses), tuple(discoveries)

    @staticmethod
    def _observation_loss(
        parameters: Sequence[float],
        rank: int,
        status: int,
        discovery: int,
    ) -> float:
        beta, log_delta, observation_intercept, coupling = parameters
        delta = math.exp(float(log_delta))
        potentials = tuple(
            beta - delta * (rank - 1) + latent
            for latent in _QUADRATURE_LATENT
        )
        if status == OBSERVATION_OBSERVED:
            terms = tuple(
                weight
                - _softplus(-(observation_intercept + coupling * potential))
                + discovery * potential
                - math.exp(max(-50.0, min(50.0, potential)))
                - math.lgamma(discovery + 1.0)
                for weight, potential in zip(
                    _LOG_QUADRATURE_WEIGHTS, potentials
                )
            )
        else:
            terms = tuple(
                weight
                - _softplus(observation_intercept + coupling * potential)
                for weight, potential in zip(
                    _LOG_QUADRATURE_WEIGHTS, potentials
                )
            )
        return -_logsumexp(terms)

    @staticmethod
    def _prior_loss(parameters: Sequence[float]) -> float:
        return 0.5 * (
            parameters[0] * parameters[0] / 36.0
            + (parameters[1] - math.log(0.05)) ** 2 / 4.0
            + parameters[2] * parameters[2] / 36.0
            + parameters[3] * parameters[3] / 9.0
        )

    @classmethod
    def _history_loss(
        cls,
        parameters: Sequence[float],
        statuses: Sequence[int],
        discoveries: Sequence[float],
    ) -> float:
        return cls._prior_loss(parameters) + sum(
            cls._observation_loss(parameters, rank, status, int(discovery))
            for rank, (status, discovery) in enumerate(
                zip(statuses, discoveries), start=1
            )
        )

    @staticmethod
    def _project_parameters(
        parameters: Sequence[float], *, coupling_identifiable: bool
    ) -> list[float]:
        lower_bounds = (-20.0, -12.0, -20.0, -10.0)
        upper_bounds = (20.0, 3.0, 20.0, 10.0)
        projected = [
            max(lower_bounds[index], min(upper_bounds[index], float(value)))
            for index, value in enumerate(parameters)
        ]
        if not coupling_identifiable:
            projected[3] = 0.0
        return projected

    @classmethod
    def _history_gradient(
        cls,
        parameters: Sequence[float],
        statuses: Sequence[int],
        discoveries: Sequence[float],
        *,
        coupling_identifiable: bool,
    ) -> list[float]:
        gradient: list[float] = []
        for index in range(4):
            if index == 3 and not coupling_identifiable:
                gradient.append(0.0)
                continue
            width = 1e-4 * (1.0 + abs(float(parameters[index])))
            upper = list(parameters)
            lower = list(parameters)
            upper[index] += width
            lower[index] -= width
            upper = cls._project_parameters(
                upper, coupling_identifiable=coupling_identifiable
            )
            lower = cls._project_parameters(
                lower, coupling_identifiable=coupling_identifiable
            )
            denominator = upper[index] - lower[index]
            if denominator == 0.0:
                gradient.append(0.0)
                continue
            gradient.append(
                (
                    cls._history_loss(upper, statuses, discoveries)
                    - cls._history_loss(lower, statuses, discoveries)
                )
                / denominator
            )
        return gradient

    @staticmethod
    def _dot(left: Sequence[float], right: Sequence[float]) -> float:
        return sum(a * b for a, b in zip(left, right))

    @staticmethod
    def _matrix_vector(
        matrix: Sequence[Sequence[float]], vector: Sequence[float]
    ) -> list[float]:
        return [sum(a * b for a, b in zip(row, vector)) for row in matrix]

    @classmethod
    def _bfgs_update(
        cls,
        inverse_hessian: Sequence[Sequence[float]],
        displacement: Sequence[float],
        gradient_change: Sequence[float],
    ) -> list[list[float]]:
        curvature = cls._dot(displacement, gradient_change)
        if not math.isfinite(curvature) or curvature <= 1e-10:
            return [
                [1.0 if row == column else 0.0 for column in range(4)]
                for row in range(4)
            ]
        inverse_curvature = 1.0 / curvature
        h_times_y = cls._matrix_vector(inverse_hessian, gradient_change)
        y_h_y = cls._dot(gradient_change, h_times_y)
        scale = (1.0 + y_h_y * inverse_curvature) * inverse_curvature
        return [
            [
                inverse_hessian[row][column]
                + scale * displacement[row] * displacement[column]
                - inverse_curvature
                * (
                    displacement[row] * h_times_y[column]
                    + h_times_y[row] * displacement[column]
                )
                for column in range(4)
            ]
            for row in range(4)
        ]

    def _fit_full_history(
        self,
        statuses: Sequence[int],
        discoveries: Sequence[float],
        *,
        coupling_identifiable: bool,
    ) -> tuple[list[float], tuple[tuple[float, ...], ...], float]:
        """Warm-started full-history MAP fit using standard-library BFGS."""

        parameters = self._project_parameters(
            self._fit_parameters,
            coupling_identifiable=coupling_identifiable,
        )
        if coupling_identifiable != self._coupling_was_identifiable:
            inverse_hessian = [
                [1.0 if row == column else 0.0 for column in range(4)]
                for row in range(4)
            ]
        else:
            inverse_hessian = [row.copy() for row in self._fit_inverse_hessian]
        objective = self._history_loss(parameters, statuses, discoveries)
        gradient = self._history_gradient(
            parameters,
            statuses,
            discoveries,
            coupling_identifiable=coupling_identifiable,
        )
        for _iteration in range(100):
            active_gradient = gradient if coupling_identifiable else gradient[:3]
            if max(abs(value) for value in active_gradient) <= 1e-6:
                break
            direction = [
                -value
                for value in self._matrix_vector(inverse_hessian, gradient)
            ]
            if not coupling_identifiable:
                direction[3] = 0.0
            directional_derivative = self._dot(gradient, direction)
            if directional_derivative >= 0.0 or not math.isfinite(
                directional_derivative
            ):
                direction = [-value for value in gradient]
                directional_derivative = -self._dot(gradient, gradient)
                inverse_hessian = [
                    [1.0 if row == column else 0.0 for column in range(4)]
                    for row in range(4)
                ]
            step = 1.0
            candidate = parameters
            candidate_objective = objective
            while step >= 2.0 ** -20:
                trial = self._project_parameters(
                    [
                        value + step * direction[index]
                        for index, value in enumerate(parameters)
                    ],
                    coupling_identifiable=coupling_identifiable,
                )
                trial_objective = self._history_loss(
                    trial, statuses, discoveries
                )
                if trial_objective <= objective + 1e-4 * step * directional_derivative:
                    candidate = trial
                    candidate_objective = trial_objective
                    break
                step *= 0.5
            if candidate == parameters:
                break
            candidate_gradient = self._history_gradient(
                candidate,
                statuses,
                discoveries,
                coupling_identifiable=coupling_identifiable,
            )
            displacement = [
                candidate[index] - parameters[index] for index in range(4)
            ]
            gradient_change = [
                candidate_gradient[index] - gradient[index] for index in range(4)
            ]
            inverse_hessian = self._bfgs_update(
                inverse_hessian, displacement, gradient_change
            )
            parameters = candidate
            objective = candidate_objective
            gradient = candidate_gradient
        if not coupling_identifiable:
            for index in range(4):
                inverse_hessian[3][index] = 0.0
                inverse_hessian[index][3] = 0.0
        self._fit_parameters = parameters.copy()
        self._fit_inverse_hessian = [row.copy() for row in inverse_hessian]
        self._coupling_was_identifiable = coupling_identifiable
        return (
            parameters,
            tuple(tuple(value for value in row) for row in inverse_hessian),
            objective,
        )

    @staticmethod
    def _metric_discovery(parameters: Sequence[float], rank: float) -> float:
        beta, log_delta, observation_intercept, coupling = parameters
        delta = math.exp(float(log_delta))
        return sum(
            math.exp(weight)
            * (
                1.0
                / (
                    1.0
                    + math.exp(
                        max(
                            -50.0,
                            min(
                                50.0,
                                -(
                                    observation_intercept
                                    + coupling
                                    * (beta - delta * (rank - 1.0) + latent)
                                ),
                            ),
                        )
                    )
                )
            )
            * math.exp(
                max(
                    -50.0,
                    min(50.0, beta - delta * (rank - 1.0) + latent),
                )
            )
            for weight, latent in zip(
                _LOG_QUADRATURE_WEIGHTS, _QUADRATURE_LATENT
            )
        )

    @classmethod
    def _metric_remaining(
        cls, parameters: Sequence[float], next_rank: int
    ) -> Optional[float]:
        first = cls._metric_discovery(parameters, next_rank)
        if first == 0.0:
            return 0.0
        second = cls._metric_discovery(parameters, next_rank + 1)
        ratio = second / first
        if not math.isfinite(ratio) or ratio >= 1.0:
            return None
        return max(0.0, first / max(1e-12, 1.0 - ratio))

    @staticmethod
    def _metric_variance(
        parameters: Sequence[float],
        covariance: Sequence[Sequence[float]],
        metric: Callable[[Sequence[float]], float],
    ) -> float:
        gradient = [0.0 for _ in parameters]
        for index in range(len(parameters)):
            step = 1e-4 * (1.0 + abs(float(parameters[index])))
            upper = parameters.copy()
            lower = parameters.copy()
            upper[index] += step
            lower[index] -= step
            gradient[index] = (metric(upper) - metric(lower)) / (2.0 * step)
        variance = sum(
            gradient[row] * covariance[row][column] * gradient[column]
            for row in range(len(gradient))
            for column in range(len(gradient))
        )
        return max(0.0, variance)

    @staticmethod
    def _optional_metric_variance(
        parameters: Sequence[float],
        covariance: Sequence[Sequence[float]],
        metric: Callable[[Sequence[float]], Optional[float]],
    ) -> Optional[float]:
        gradient = [0.0 for _ in parameters]
        for index in range(len(parameters)):
            step = 1e-4 * (1.0 + abs(float(parameters[index])))
            upper = parameters.copy()
            lower = parameters.copy()
            upper[index] += step
            lower[index] -= step
            upper_value = metric(upper)
            lower_value = metric(lower)
            if upper_value is None or lower_value is None:
                return None
            gradient[index] = (upper_value - lower_value) / (2.0 * step)
        variance = sum(
            gradient[row] * covariance[row][column] * gradient[column]
            for row in range(len(gradient))
            for column in range(len(gradient))
        )
        return max(0.0, variance)

    def _fit(
        self,
    ) -> Optional[tuple[list[float], tuple[tuple[float, ...], ...], float]]:
        statuses, discoveries = self._attempt_data()
        evaluated = sum(status == OBSERVATION_OBSERVED for status in statuses)
        if len(statuses) < self.window_size or evaluated < self.subsample_size:
            return None
        coupling_identifiable = (
            evaluated > 0
            and any(status == OBSERVATION_FAILED for status in statuses)
        )
        parameters, covariance, objective = self._fit_full_history(
            statuses,
            discoveries,
            coupling_identifiable=coupling_identifiable,
        )
        if not all(
            math.isfinite(value)
            for row in covariance
            for value in row
        ):
            return ()
        return parameters, covariance, objective

    def snapshot(self) -> IncidenceEstimate:
        cache_key = len(self._unit_statuses)
        if self._fit_cache is not None and self._fit_cache[0] == cache_key:
            return self._fit_cache[1]
        statuses, _discoveries = self._attempt_data()
        attempted = len(statuses)
        observed_units = sum(status == OBSERVATION_OBSERVED for status in statuses)
        failed_units = sum(status == OBSERVATION_FAILED for status in statuses)
        fit = self._fit()
        if fit is None:
            expected = NumericBand.coded(STATUS_INSUFFICIENT)
            remaining = NumericBand.coded(STATUS_INSUFFICIENT)
            next_discovery = NumericBand.coded(STATUS_INSUFFICIENT)
            fit_diagnostics: dict[str, Real] = {}
        elif not fit:
            expected = NumericBand.coded(STATUS_UNIDENTIFIABLE)
            remaining = NumericBand.coded(STATUS_UNIDENTIFIABLE)
            next_discovery = NumericBand.coded(STATUS_UNIDENTIFIABLE)
            fit_diagnostics = {}
        else:
            parameters, covariance, objective = fit
            next_rank = attempted + 1
            next_point = self._metric_discovery(parameters, next_rank)
            next_variance = self._metric_variance(
                parameters,
                covariance,
                lambda values: self._metric_discovery(values, next_rank),
            )
            next_discovery = NumericBand.laplace(
                next_point, next_variance, self.alpha
            )
            remaining_point = self._metric_remaining(parameters, next_rank)
            if remaining_point is None:
                remaining = NumericBand.coded(STATUS_UNIDENTIFIABLE)
                expected = NumericBand.coded(STATUS_UNIDENTIFIABLE)
            else:
                remaining_variance = self._optional_metric_variance(
                    parameters,
                    covariance,
                    lambda values: self._metric_remaining(values, next_rank),
                )
                if remaining_variance is None:
                    remaining = NumericBand.coded(STATUS_UNIDENTIFIABLE)
                    expected = NumericBand.coded(STATUS_UNIDENTIFIABLE)
                else:
                    remaining = NumericBand.laplace(
                        remaining_point, remaining_variance, self.alpha
                    )
                    expected = NumericBand.laplace(
                        self.distinct + remaining_point,
                        remaining_variance,
                        self.alpha,
                        lower_floor=self.distinct,
                    )
            fit_diagnostics = {
                "yield_intercept": float(parameters[0]),
                "rank_decay": math.exp(float(parameters[1])),
                "observation_intercept": float(parameters[2]),
                "failure_yield_coupling": float(parameters[3]),
                "failure_yield_coupling_identifiable": float(
                    observed_units > 0 and failed_units > 0
                ),
                "fit_objective": objective,
            }
        estimate = IncidenceEstimate(
            scope_path=self.scope_path,
            epoch=self.epoch,
            channel=self.channel,
            incidence_samples=self.units,
            observed_results=NumericBand.exact(self.distinct),
            expected_results=expected,
            remaining_results=remaining,
            control_statistics={"expected_next_discoveries": next_discovery},
            diagnostics={
                "minimum_attempts": self.window_size,
                "minimum_evaluated": self.subsample_size,
                "alpha": self.alpha,
                "attempted_units": attempted,
                "observed_units": observed_units,
                "failed_units": failed_units,
                "excluded_units": sum(
                    status == OBSERVATION_EXCLUDED
                    for status in self._unit_statuses
                ),
                **fit_diagnostics,
            },
            formula_versions={
                "preferential_discovery": RAREFACTION_FORMULA_VERSION,
                "reachable_total": REACHABLE_TOTAL_FORMULA_VERSION,
            },
        )
        self._fit_cache = (cache_key, estimate)
        return estimate


# ---------------------------------------------------------------------------
# The matching numerical controller
# ---------------------------------------------------------------------------

CONTROLLER_VERSION = "preferential_discovery_controller_v5"
VOLUME_CREDIT_VERSION = "relaxed_geometric_hypervolume_v3"
VOLUME_RELAXATION_FACTOR = 2.0
_REQUIRED_ROLES = (
    "expected_results",
    "expected_next_discoveries",
)


def _volume_relaxation(axis_count: int) -> float:
    """Return the fixed half-share relaxation for this column vector."""

    if not isinstance(axis_count, int) or isinstance(axis_count, bool) or axis_count < 1:
        raise ValueError("axis_count must be a positive integer")
    return 1.0 / (VOLUME_RELAXATION_FACTOR * axis_count)


def _relaxed_geometric_volume(progress: Sequence[Real]) -> float:
    """Balance column progress without making one empty column a zero cliff.

    For ``C`` column axes, epsilon is ``1 / (2C)`` and the volume is
    ``geomean(epsilon + progress) - epsilon``. It is zero when every axis is
    empty, one when every axis is complete, and gives larger marginal value
    to progress on lagging axes.
    """

    values = tuple(
        _finite_number(f"progress[{index}]", value)
        for index, value in enumerate(progress)
    )
    epsilon = _volume_relaxation(len(values))
    if any(value < 0.0 or value > 1.0 for value in values):
        raise ValueError("every progress coordinate must be in [0, 1]")
    shifted_log_mean = sum(math.log(epsilon + value) for value in values) / len(values)
    volume = math.exp(shifted_log_mean) - epsilon
    return min(1.0, max(0.0, volume))


def _channel_thresholds(
    name: str,
    values: Mapping[str, Real],
    channels: tuple[str, ...],
) -> dict[str, float]:
    out = {str(channel): float(value) for channel, value in values.items()}
    if set(out) != set(channels):
        raise ValueError(f"{name} must name every required channel exactly once")
    if any(not math.isfinite(value) or value < 0.0 for value in out.values()):
        raise ValueError(f"{name} thresholds must be finite and non-negative")
    return out


@dataclass(frozen=True)
class ControllerConfig:
    """One frozen epoch-scope controller declaration.

    ``gamma`` is the maximum accepted upper bound on expected marginal
    hypervolume credit in the next attempted unit. ``rho`` labels a
    hypervolume stop as converged when every fitted per-column remaining-result
    upper bound is also no larger; it does not gate the stop itself.
    """

    required_channels: tuple[str, ...]
    gamma: Real
    rho: Mapping[str, Real]
    streak_length: int
    version: str = CONTROLLER_VERSION
    required_roles: tuple[str, ...] = field(default=_REQUIRED_ROLES, init=False)

    def __post_init__(self) -> None:
        channels = tuple(str(channel) for channel in self.required_channels)
        if not channels or any(not channel for channel in channels):
            raise ValueError("required_channels must be a non-empty tuple of names")
        if len(set(channels)) != len(channels):
            raise ValueError("required_channels must be unique")
        if (
            not isinstance(self.streak_length, int)
            or isinstance(self.streak_length, bool)
            or self.streak_length < 1
        ):
            raise ValueError("streak_length K must be a positive integer")
        if not isinstance(self.version, str) or not self.version.strip():
            raise ValueError("controller version must be a non-empty string")
        object.__setattr__(self, "required_channels", channels)
        gamma = _finite_number("gamma", self.gamma)
        if gamma < 0.0:
            raise ValueError("gamma must be finite and non-negative")
        object.__setattr__(self, "gamma", gamma)
        object.__setattr__(
            self,
            "rho",
            _channel_thresholds("rho", self.rho, channels),
        )

    @classmethod
    def uniform(
        cls,
        channels: tuple[str, ...],
        *,
        gamma: Real = 0.0,
        rho: Real = 0.0,
        streak_length: int = 1,
    ) -> "ControllerConfig":
        return cls(
            required_channels=tuple(channels),
            gamma=gamma,
            rho={channel: rho for channel in channels},
            streak_length=streak_length,
        )

    def as_record(self) -> dict:
        return {
            "version": self.version,
            "required_roles": list(self.required_roles),
            "required_channels": list(self.required_channels),
            "gamma": self.gamma,
            "rho": dict(self.rho),
            "streak_length": self.streak_length,
        }

    def bind_channels(self, channels: tuple[str, ...]) -> "ControllerConfig":
        channels = tuple(channels)
        if channels == self.required_channels:
            return self
        if self.required_channels != ("overall",):
            raise ValueError("a multi-channel controller may not be rebound")
        return ControllerConfig.uniform(
            channels,
            gamma=self.gamma,
            rho=self.rho["overall"],
            streak_length=self.streak_length,
        )

    def with_thresholds(
        self,
        thresholds: Mapping[str, object],
    ) -> "ControllerConfig":
        if set(thresholds) != {"gamma", "rho"}:
            raise ValueError("threshold adapter must return exactly gamma and rho")
        rho = thresholds["rho"]
        if not isinstance(rho, Mapping):
            raise TypeError("threshold adapter rho must be a channel mapping")
        return ControllerConfig(
            required_channels=self.required_channels,
            gamma=thresholds["gamma"],  # type: ignore[arg-type]
            rho=rho,
            streak_length=self.streak_length,
            version=self.version,
        )

    def threshold_state(self) -> dict[str, object]:
        return {"gamma": self.gamma, "rho": dict(self.rho)}


@dataclass(frozen=True)
class VolumeCredit:
    """The method's sole scalar credit on normalized column axes.

    ``score`` is the realized marginal relaxed geometric volume of the
    completed unit on the frozen pre-unit scale. ``expected_next_score`` is
    the estimated marginal volume of the next attempted unit on the current
    scale and is the numerical controller's sole stop statistic. Per-column
    identities and estimates remain the vector inputs; they are not parallel
    credits.
    """

    score: NumericBand
    expected_next_score: NumericBand
    before_volume: float
    after_volume: float
    channels: Mapping[str, Mapping[str, float]] = field(default_factory=dict)
    version: str = VOLUME_CREDIT_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.score, NumericBand):
            raise TypeError("VolumeCredit.score must be a NumericBand")
        if not isinstance(self.expected_next_score, NumericBand):
            raise TypeError(
                "VolumeCredit.expected_next_score must be a NumericBand"
            )
        before = _finite_number("VolumeCredit.before_volume", self.before_volume)
        after = _finite_number("VolumeCredit.after_volume", self.after_volume)
        if self.score.status_code == STATUS_NORMAL:
            if not 0.0 <= before <= 1.0 or not 0.0 <= after <= 1.0:
                raise ValueError("normal hypervolume values must be in [0, 1]")
            if after < before:
                raise ValueError("marginal hypervolume cannot decrease")
        else:
            coded = float(self.score.status_code)
            if before != coded or after != coded:
                raise ValueError(
                    "unavailable hypervolume uses its numeric status code"
                )
        normalized: dict[str, dict[str, float]] = {}
        for channel, values in self.channels.items():
            normalized[str(channel)] = {
                str(name): _finite_number(
                    f"VolumeCredit.channels[{channel!r}][{name!r}]", value
                )
                for name, value in values.items()
            }
        object.__setattr__(self, "before_volume", before)
        object.__setattr__(self, "after_volume", after)
        object.__setattr__(self, "channels", normalized)

    @classmethod
    def coded(cls, status_code: int) -> "VolumeCredit":
        band = NumericBand.coded(status_code)
        coded = float(status_code)
        return cls(
            score=band,
            expected_next_score=band,
            before_volume=coded,
            after_volume=coded,
        )

    @classmethod
    def exact(
        cls,
        *,
        before_volume: Real,
        after_volume: Real,
        expected_next_score: NumericBand,
        channels: Mapping[str, Mapping[str, float]],
    ) -> "VolumeCredit":
        before = _finite_number("before_volume", before_volume)
        after = _finite_number("after_volume", after_volume)
        return cls(
            score=NumericBand.exact(max(0.0, after - before)),
            expected_next_score=expected_next_score,
            before_volume=before,
            after_volume=after,
            channels=channels,
        )

    def as_record(self) -> dict:
        return {
            "version": self.version,
            "score": self.score.as_record(),
            "expected_next_score": self.expected_next_score.as_record(),
            "before_volume": self.before_volume,
            "after_volume": self.after_volume,
            "channels": {
                channel: dict(values) for channel, values in self.channels.items()
            },
        }


@dataclass(frozen=True)
class ControllerVerdict:
    """Recomputable arithmetic result after one counted observation."""

    stop: bool
    outcome: str
    flat_streak: int
    done_streak: int
    config: ControllerConfig
    expected_next_hypervolume_credit: NumericBand
    channels: Mapping[str, Mapping[str, object]]

    def as_record(self) -> dict:
        return {
            "stop": self.stop,
            "outcome": self.outcome,
            "flat_streak": self.flat_streak,
            "done_streak": self.done_streak,
            "controller": self.config.as_record(),
            "expected_next_hypervolume_credit": (
                self.expected_next_hypervolume_credit.as_record()
            ),
            "channels": {name: dict(value) for name, value in self.channels.items()},
        }


class NumericalController:
    """Stateful streak owner used only by its paired estimator component."""

    def __init__(self, config: ControllerConfig) -> None:
        self.config = config
        self._flat_streak = 0
        self._done_streak = 0
        self._last = self._record(
            {},
            expected_next_hypervolume_credit=NumericBand.coded(
                STATUS_INSUFFICIENT
            ),
            stop=False,
            outcome="awaiting_eligible_observation",
        )

    def _record(
        self,
        channels: Mapping[str, Mapping[str, object]],
        *,
        expected_next_hypervolume_credit: NumericBand,
        stop: bool,
        outcome: str,
    ) -> ControllerVerdict:
        return ControllerVerdict(
            stop,
            outcome,
            self._flat_streak,
            self._done_streak,
            self.config,
            expected_next_hypervolume_credit,
            channels,
        )

    def verdict(self) -> ControllerVerdict:
        return self._last

    def apply_thresholds(self, config: ControllerConfig) -> None:
        """Change validated thresholds without resetting controller history."""

        if config.required_channels != self.config.required_channels:
            raise ValueError("threshold adaptation cannot change required channels")
        if config.streak_length != self.config.streak_length:
            raise ValueError("threshold adaptation cannot change streak length")
        self.config = config

    def defer(self, outcome: str) -> ControllerVerdict:
        """Record a non-decision without changing either streak."""

        self._last = self._record(
            {},
            expected_next_hypervolume_credit=NumericBand.coded(
                STATUS_INSUFFICIENT
            ),
            stop=False,
            outcome=outcome,
        )
        return self._last

    def assign_volume_credit(
        self,
        before: Mapping[str, IncidenceEstimate],
        after: Mapping[str, IncidenceEstimate],
        *,
        observation_status: int,
    ) -> VolumeCredit:
        """Reduce the column vector to the method's sole scalar credit."""

        if observation_status == OBSERVATION_EXCLUDED:
            return VolumeCredit.coded(STATUS_INSUFFICIENT)
        required = set(self.config.required_channels)
        if set(before) != required or set(after) != required:
            raise ValueError(
                "volume credit requires every controller channel exactly once"
            )
        expected_next_score, channel_records = self.expected_next_volume_credit(
            after
        )
        before_progress: list[float] = []
        after_progress: list[float] = []
        for channel in self.config.required_channels:
            before_estimate = before[channel]
            after_estimate = after[channel]
            normalization = before_estimate.expected_results
            if normalization.status_code != STATUS_NORMAL:
                status = (
                    STATUS_UNIDENTIFIABLE
                    if normalization.status_code == STATUS_UNIDENTIFIABLE
                    else STATUS_INSUFFICIENT
                )
                coded = float(status)
                return VolumeCredit(
                    score=NumericBand.coded(status),
                    expected_next_score=expected_next_score,
                    before_volume=coded,
                    after_volume=coded,
                    channels=channel_records,
                )
            expected_total = normalization.value
            observed_before = before_estimate.observed_results.value
            observed_after = after_estimate.observed_results.value
            if observed_after < observed_before:
                coded = float(STATUS_UNIDENTIFIABLE)
                return VolumeCredit(
                    score=NumericBand.coded(STATUS_UNIDENTIFIABLE),
                    expected_next_score=expected_next_score,
                    before_volume=coded,
                    after_volume=coded,
                    channels=channel_records,
                )
            if expected_total == 0.0:
                if observed_before != 0.0 or observed_after != 0.0:
                    coded = float(STATUS_UNIDENTIFIABLE)
                    return VolumeCredit(
                        score=NumericBand.coded(STATUS_UNIDENTIFIABLE),
                        expected_next_score=expected_next_score,
                        before_volume=coded,
                        after_volume=coded,
                        channels=channel_records,
                    )
                progress_before = 1.0
                progress_after = 1.0
            else:
                if observed_before > expected_total:
                    coded = float(STATUS_UNIDENTIFIABLE)
                    return VolumeCredit(
                        score=NumericBand.coded(STATUS_UNIDENTIFIABLE),
                        expected_next_score=expected_next_score,
                        before_volume=coded,
                        after_volume=coded,
                        channels=channel_records,
                    )
                progress_before = observed_before / expected_total
                progress_after = min(1.0, observed_after / expected_total)
            before_progress.append(progress_before)
            after_progress.append(progress_after)
            channel_records.setdefault(channel, {}).update({
                "normalization_expected_results": expected_total,
                "normalization_lower": normalization.lower,
                "normalization_upper": normalization.upper,
                "observed_before": observed_before,
                "observed_after": observed_after,
                "progress_before": progress_before,
                "progress_after": progress_after,
            })
        before_volume = _relaxed_geometric_volume(before_progress)
        after_volume = _relaxed_geometric_volume(after_progress)
        return VolumeCredit.exact(
            before_volume=before_volume,
            after_volume=after_volume,
            expected_next_score=expected_next_score,
            channels=channel_records,
        )

    def expected_next_volume_credit(
        self,
        estimates: Mapping[str, IncidenceEstimate],
    ) -> tuple[NumericBand, dict[str, dict[str, float]]]:
        """Project estimator bands to next-unit marginal hypervolume.

        Interval arithmetic preserves every column and produces a conservative
        outer band. No per-column statistic can independently trigger a stop.
        """

        required = set(self.config.required_channels)
        if set(estimates) != required:
            raise ValueError(
                "hypervolume prediction requires every controller channel "
                "exactly once"
            )
        bands: list[NumericBand] = []
        for channel in self.config.required_channels:
            estimate = estimates[channel]
            bands.extend(
                (
                    estimate.expected_results,
                    estimate.control_statistics["expected_next_discoveries"],
                )
            )
        unavailable = [band.status_code for band in bands if band.status_code]
        if unavailable:
            status = (
                STATUS_UNIDENTIFIABLE
                if STATUS_UNIDENTIFIABLE in unavailable
                else STATUS_INSUFFICIENT
            )
            return NumericBand.coded(status), {}

        current_point: list[float] = []
        current_lower: list[float] = []
        current_upper: list[float] = []
        projected_point: list[float] = []
        increment_lower: list[float] = []
        increment_upper: list[float] = []
        channel_records: dict[str, dict[str, float]] = {}
        axis_count = len(self.config.required_channels)
        relaxation_epsilon = _volume_relaxation(axis_count)
        for channel in self.config.required_channels:
            estimate = estimates[channel]
            total = estimate.expected_results
            next_discoveries = estimate.control_statistics[
                "expected_next_discoveries"
            ]
            observed = estimate.observed_results.value
            if total.value < observed or total.upper < observed:
                return NumericBand.coded(STATUS_UNIDENTIFIABLE), {}
            if total.value == 0.0:
                if observed != 0.0 or next_discoveries.upper > 0.0:
                    return NumericBand.coded(STATUS_UNIDENTIFIABLE), {}
                p_now = p_now_lower = p_now_upper = 1.0
                p_next = p_next_lower = p_next_upper = 1.0
                p_increment_lower = p_increment_upper = 0.0
            else:
                p_now = min(1.0, observed / total.value)
                p_next = min(
                    1.0,
                    (observed + next_discoveries.value) / total.value,
                )
                if total.upper == 0.0:
                    return NumericBand.coded(STATUS_UNIDENTIFIABLE), {}
                p_now_lower = min(1.0, observed / total.upper)
                p_next_lower = min(
                    1.0,
                    (observed + next_discoveries.lower) / total.upper,
                )
                if total.lower == 0.0:
                    p_now_upper = 1.0
                    p_next_upper = 1.0
                else:
                    p_now_upper = min(1.0, observed / total.lower)
                    p_next_upper = min(
                        1.0,
                        (observed + next_discoveries.upper) / total.lower,
                    )

                def axis_increment(total_value: float, discovery: float) -> float:
                    if total_value <= 0.0:
                        return 0.0
                    current = min(1.0, observed / total_value)
                    projected = min(
                        1.0,
                        (observed + discovery) / total_value,
                    )
                    return max(0.0, projected - current)

                total_lower = max(observed, total.lower)
                total_upper = max(total_lower, total.upper)
                lower_candidates = (total_lower, total_upper)
                upper_candidates = [total_lower, total_upper]
                peak = observed + next_discoveries.upper
                if total_lower <= peak <= total_upper:
                    upper_candidates.append(peak)
                p_increment_lower = min(
                    axis_increment(candidate, next_discoveries.lower)
                    for candidate in lower_candidates
                )
                p_increment_upper = max(
                    axis_increment(candidate, next_discoveries.upper)
                    for candidate in upper_candidates
                )
            current_point.append(p_now)
            current_lower.append(p_now_lower)
            current_upper.append(p_now_upper)
            projected_point.append(p_next)
            increment_lower.append(p_increment_lower)
            increment_upper.append(p_increment_upper)
            channel_records[channel] = {
                "current_expected_results": total.value,
                "current_expected_results_lower": total.lower,
                "current_expected_results_upper": total.upper,
                "current_observed_results": observed,
                "expected_next_discoveries": next_discoveries.value,
                "expected_next_discoveries_lower": next_discoveries.lower,
                "expected_next_discoveries_upper": next_discoveries.upper,
                "current_progress": p_now,
                "current_progress_lower": p_now_lower,
                "current_progress_upper": p_now_upper,
                "projected_progress": p_next,
                "projected_progress_lower": p_next_lower,
                "projected_progress_upper": p_next_upper,
                "progress_increment": max(0.0, p_next - p_now),
                "progress_increment_lower": p_increment_lower,
                "progress_increment_upper": p_increment_upper,
                "volume_axis_count": float(axis_count),
                "volume_relaxation_factor": VOLUME_RELAXATION_FACTOR,
                "volume_relaxation_epsilon": relaxation_epsilon,
            }

        point = max(
            0.0,
            _relaxed_geometric_volume(projected_point)
            - _relaxed_geometric_volume(current_point),
        )
        lower = max(
            0.0,
            _relaxed_geometric_volume(
                tuple(
                    min(1.0, current_lower[index] + increment_lower[index])
                    for index in range(len(current_lower))
                )
            )
            - _relaxed_geometric_volume(current_lower),
        )
        upper = min(
            1.0,
            max(
                0.0,
                _relaxed_geometric_volume(
                    tuple(
                        min(1.0, current_upper[index] + increment_upper[index])
                        for index in range(len(current_upper))
                    )
                )
                - _relaxed_geometric_volume(current_upper),
            ),
        )
        lower = min(lower, point)
        upper = max(upper, point)
        if all(band.uncertainty_code == UNCERTAINTY_EXACT for band in bands):
            return NumericBand.exact(point), channel_records
        alpha = max(band.alpha for band in bands if band.alpha > 0.0)
        uncertainty_code = max(band.uncertainty_code for band in bands)
        return (
            NumericBand(
                value=point,
                lower=lower,
                upper=upper,
                status_code=STATUS_NORMAL,
                uncertainty_code=uncertainty_code,
                alpha=alpha,
            ),
            channel_records,
        )

    def observe(
        self,
        estimates: Mapping[str, IncidenceEstimate],
        *,
        method_credit: VolumeCredit,
        is_root: bool,
    ) -> ControllerVerdict:
        if set(estimates) != set(self.config.required_channels):
            raise ValueError(
                "controller estimates must contain every required channel exactly once"
            )
        rows: dict[str, dict[str, object]] = {}
        all_done = True
        for channel in self.config.required_channels:
            estimate = estimates[channel]
            next_discovery = estimate.control_statistics[
                "expected_next_discoveries"
            ]
            remaining = estimate.remaining_results
            done = (
                remaining.status_code == STATUS_NORMAL
                and remaining.upper <= self.config.rho[channel]
            )
            all_done = all_done and done
            rows[channel] = {
                "expected_next_discoveries": next_discovery.as_record(),
                "done": done,
                "remaining_status_code": remaining.status_code,
                "remaining_upper": remaining.upper,
                "rho": self.config.rho[channel],
                "hypervolume_axis": dict(
                    method_credit.channels.get(channel, {})
                ),
            }
        expected_next_credit = method_credit.expected_next_score
        flat = (
            expected_next_credit.status_code == STATUS_NORMAL
            and expected_next_credit.upper <= self.config.gamma
        )
        if expected_next_credit.status_code != STATUS_NORMAL or not flat:
            self._flat_streak = 0
            self._done_streak = 0
            outcome = (
                "insufficient"
                if expected_next_credit.status_code != STATUS_NORMAL
                else "continuing"
            )
            self._last = self._record(
                rows,
                expected_next_hypervolume_credit=expected_next_credit,
                stop=False,
                outcome=outcome,
            )
            return self._last
        self._flat_streak += 1
        if all_done:
            self._done_streak += 1
        else:
            self._done_streak = 0
        if self._flat_streak >= self.config.streak_length:
            if all_done:
                outcome = "whole_convergence" if is_root else "local_convergence"
            else:
                outcome = "root_incomplete" if is_root else "local_saturation"
            self._last = self._record(
                rows,
                expected_next_hypervolume_credit=expected_next_credit,
                stop=True,
                outcome=outcome,
            )
            return self._last
        self._last = self._record(
            rows,
            expected_next_hypervolume_credit=expected_next_credit,
            stop=False,
            outcome="flat_progressing",
        )
        return self._last


@dataclass(frozen=True)
class IncidenceReport:
    """Immutable estimates emitted by one paired numerical transition."""

    primary_channel: str
    estimates: Mapping[str, IncidenceEstimate]
    channel_schema: ChannelSchema
    expected_next_hypervolume_credit: NumericBand

    @property
    def primary(self) -> IncidenceEstimate:
        return self.estimates[self.primary_channel]

    def as_record(self) -> dict:
        return {
            "primary_channel": self.primary_channel,
            "estimates": {
                name: estimate.as_record()
                for name, estimate in self.estimates.items()
            },
            "channel_schema": self.channel_schema.as_record(),
            "expected_next_hypervolume_credit": (
                self.expected_next_hypervolume_credit.as_record()
            ),
        }


ThresholdAdapter = Callable[
    [IncidenceReport, Mapping[str, object]],
    Mapping[str, object],
]


def _keep_current_thresholds(
    _report: IncidenceReport,
    current: Mapping[str, object],
) -> Mapping[str, object]:
    return current


@dataclass(frozen=True)
class ControlStep:
    """One internally consistent estimator-controller transition."""

    unit_yield: UnitYield
    report: IncidenceReport
    verdict: ControllerVerdict
    volume_credit: VolumeCredit


class EstimatorController:
    """One scope's paired estimators, threshold adapter, and controller."""

    @staticmethod
    def validate_parameters(
        window_size: int,
        subsample_size: int,
        alpha: Real,
    ) -> None:
        IncidenceEstimator.validate_parameters(window_size, subsample_size, alpha)

    def __init__(
        self,
        *,
        scope_path: tuple[tuple[str, str], ...],
        epoch: str,
        channel_schema: ChannelSchema,
        control: ControllerConfig,
        window_size: int = DEFAULT_WINDOW_SIZE,
        subsample_size: int = DEFAULT_SUBSAMPLE_SIZE,
        alpha: Real = DEFAULT_ALPHA,
        threshold_adapter: Optional[ThresholdAdapter] = None,
    ) -> None:
        if not isinstance(channel_schema, ChannelSchema):
            raise TypeError("channel_schema must be a ChannelSchema")
        bound_control = control.bind_channels(
            tuple(channel_schema.controller_channels or ())
        )
        self.scope_path = IncidenceEstimator._normalize_path(scope_path)
        self.epoch = str(epoch)
        self.channel_schema = channel_schema
        self._window_size = window_size
        self._subsample_size = subsample_size
        self._alpha = float(alpha)
        self._threshold_adapter = threshold_adapter or _keep_current_thresholds
        self._estimators = {
            channel: IncidenceEstimator(
                window_size=window_size,
                subsample_size=subsample_size,
                alpha=alpha,
                scope_path=self.scope_path,
                epoch=self.epoch,
                channel=channel,
            )
            for channel in channel_schema.channels
        }
        self._controller = NumericalController(bound_control)

    @property
    def config(self) -> ControllerConfig:
        return self._controller.config

    def report(self) -> IncidenceReport:
        estimates = {
            channel: estimator.snapshot()
            for channel, estimator in self._estimators.items()
        }
        expected_next_credit, _channels = (
            self._controller.expected_next_volume_credit(
                {
                    channel: estimates[channel]
                    for channel in self._controller.config.required_channels
                }
            )
        )
        return IncidenceReport(
            primary_channel=self.channel_schema.primary_channel,
            estimates=estimates,
            channel_schema=self.channel_schema,
            expected_next_hypervolume_credit=expected_next_credit,
        )

    def verdict(self) -> ControllerVerdict:
        return self._controller.verdict()

    def advance(
        self,
        unit_label: str,
        credits: Iterable[str],
        *,
        observation_status: int,
        facets: Optional[Mapping[str, Iterable[str]]] = None,
        is_root: bool = False,
    ) -> ControlStep:
        if observation_status not in _OBSERVATION_STATUSES:
            raise ValueError(f"unknown observation_status {observation_status!r}")
        before_report = self.report()
        credit_tuple = tuple(str(raw) for raw in credits)
        groups = {
            str(name): tuple(str(raw) for raw in members)
            for name, members in (facets or {}).items()
        }
        memberships = self.channel_schema.project(
            credit_tuple,
            groups,
            active=observation_status == OBSERVATION_OBSERVED,
        )
        yields = {
            channel: self._estimators[channel].observe(
                unit_label,
                memberships[channel],
                observation_status=observation_status,
            )
            for channel in self.channel_schema.channels
        }
        report = self.report()
        required_channels = self._controller.config.required_channels
        volume_credit = self._controller.assign_volume_credit(
            {
                channel: before_report.estimates[channel]
                for channel in required_channels
            },
            {channel: report.estimates[channel] for channel in required_channels},
            observation_status=observation_status,
        )
        if observation_status != OBSERVATION_EXCLUDED:
            threshold_state = self._threshold_adapter(
                report,
                self._controller.config.threshold_state(),
            )
            self._controller.apply_thresholds(
                self._controller.config.with_thresholds(threshold_state)
            )
            estimates = {
                channel: report.estimates[channel]
                for channel in self._controller.config.required_channels
            }
            verdict = self._controller.observe(
                estimates,
                method_credit=volume_credit,
                is_root=is_root,
            )
        else:
            verdict = self._controller.verdict()
        return ControlStep(
            unit_yield=yields[self.channel_schema.primary_channel],
            report=report,
            verdict=verdict,
            volume_credit=volume_credit,
        )

    def transitioned(self, epoch: str) -> "EstimatorController":
        if not isinstance(epoch, str) or not epoch.strip() or epoch == self.epoch:
            raise ValueError("a new epoch must be a distinct non-empty stable id")
        return EstimatorController(
            scope_path=self.scope_path,
            epoch=epoch,
            channel_schema=self.channel_schema,
            control=self._controller.config,
            window_size=self._window_size,
            subsample_size=self._subsample_size,
            alpha=self._alpha,
            threshold_adapter=self._threshold_adapter,
        )
