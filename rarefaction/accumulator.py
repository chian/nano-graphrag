"""Incidence estimation over immutable per-unit identity sets.

One :class:`IncidenceEstimator` owns one frozen
``(scope_path, epoch, channel)`` declaration. An eligible acquisition unit
contributes one immutable set of opaque stable identity strings. Repeated
identities inside the unit disappear before any count is changed; recurrence
across eligible units changes incidence frequencies without increasing
observed richness.

The estimator is pure arithmetic. It owns exact rolling incidence
rarefaction and its conditional pairwise variance, plus the current
bias-corrected incidence Chao2 reachable-total calculation. It does not own a
controller, a verdict, tail-yield telemetry, I/O, or a model call.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field
from fractions import Fraction
from numbers import Real
from typing import Iterable, Mapping, Optional

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


# Numeric status and uncertainty vocabularies are declared once. A consumer
# branches on these codes, never on text.
STATUS_NORMAL = 0
STATUS_INSUFFICIENT = -1
STATUS_UNIDENTIFIABLE = -2

UNCERTAINTY_UNAVAILABLE = -1
UNCERTAINTY_EXACT = 0
UNCERTAINTY_CHEBYSHEV = 1

NUMERIC_BAND_VERSION = "numeric_band_v1"
INCIDENCE_ESTIMATOR_VERSION = "incidence_estimator_v1"
RAREFACTION_FORMULA_VERSION = "rolling_exact_incidence_rarefaction_v1"
REACHABLE_TOTAL_FORMULA_VERSION = "bias_corrected_incidence_chao2_v1"
CHANNEL_SCHEMA_VERSION = "channel_schema_v2"

DEFAULT_WINDOW_SIZE = 8
DEFAULT_SUBSAMPLE_SIZE = 4
DEFAULT_ALPHA = 0.05
DEFAULT_EPOCH = "epoch-0"
DEFAULT_CHANNEL = "overall"


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
    ``controller_channels`` names the independently estimated channels the
    numerical controller must conjoin. The two roles are deliberately
    separate: an application can require a completed-row channel without
    pooling row identities into its ordinary-column richness estimate.

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
    """Role-based estimate for one frozen scope, epoch, and channel."""

    scope_path: tuple[tuple[str, str], ...]
    epoch: str
    channel: str
    window_size: int
    subsample_size: int
    alpha: float
    incidence_samples: int
    q1: int
    q2: int
    window_observed_results: int
    observed_results: NumericBand
    rarefied_results: NumericBand
    expected_results: NumericBand
    remaining_results: NumericBand
    method_version: str = INCIDENCE_ESTIMATOR_VERSION
    band_version: str = NUMERIC_BAND_VERSION
    channel_schema_version: str = CHANNEL_SCHEMA_VERSION
    rarefaction_formula_version: str = RAREFACTION_FORMULA_VERSION
    reachable_total_formula_version: str = REACHABLE_TOTAL_FORMULA_VERSION

    def as_record(self) -> dict:
        return {
            "scope_path": [list(segment) for segment in self.scope_path],
            "epoch": self.epoch,
            "channel": self.channel,
            "method_version": self.method_version,
            "band_version": self.band_version,
            "channel_schema_version": self.channel_schema_version,
            "rarefaction_formula_version": self.rarefaction_formula_version,
            "reachable_total_formula_version": self.reachable_total_formula_version,
            "window_size": self.window_size,
            "subsample_size": self.subsample_size,
            "alpha": self.alpha,
            "incidence_samples": self.incidence_samples,
            "q1": self.q1,
            "q2": self.q2,
            "window_observed_results": self.window_observed_results,
            "observed_results": self.observed_results.as_record(),
            "rarefied_results": self.rarefied_results.as_record(),
            "expected_results": self.expected_results.as_record(),
            "remaining_results": self.remaining_results.as_record(),
            "status_codes": {
                "normal": STATUS_NORMAL,
                "insufficient": STATUS_INSUFFICIENT,
                "unidentifiable": STATUS_UNIDENTIFIABLE,
            },
            "uncertainty_codes": {
                "unavailable": UNCERTAINTY_UNAVAILABLE,
                "exact": UNCERTAINTY_EXACT,
                "chebyshev": UNCERTAINTY_CHEBYSHEV,
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
        self._unit_activity: list[bool] = []
        self._unit_eligibility: list[bool] = []

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
        crediting_active: bool = True,
        counts_toward_verdict: Optional[bool] = None,
    ) -> UnitYield:
        """Record one unit, constructing at most one incidence sample.

        Eligibility is the existing kernel boundary: the crediter was active
        and the unit counts toward the current scope's verdict. Disabled and
        invalidating-cut units retain their surrounding records but do not
        change ``T``, ``D``, ``Q1``, ``Q2``, or the rolling window.
        """

        active = bool(crediting_active)
        counted = active if counts_toward_verdict is None else bool(counts_toward_verdict)
        if counted and not active:
            raise ValueError(
                "counts_toward_verdict=True with crediting_active=False is a "
                "contradiction: an unjudged unit is not an incidence sample"
            )

        distinct_input: list[str] = []
        within_unit: set[str] = set()
        for raw in credits:
            identity = str(raw)
            if identity in within_unit:
                continue
            within_unit.add(identity)
            distinct_input.append(identity)

        eligible = active and counted
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
        self._unit_activity.append(active)
        self._unit_eligibility.append(eligible)
        return UnitYield(
            unit_index=unit_index,
            unit_label=str(unit_label),
            sample_identities=sample,
            new_identities=tuple(new),
            repeat_identities=tuple(repeats),
            credits_observed=len(distinct_input),
            cumulative_distinct=self.distinct,
            eligible=eligible,
            crediting_disabled=not active,
            counts_toward_verdict=counted,
        )

    def unit_labels(self) -> tuple[str, ...]:
        return tuple(self._unit_labels)

    def unit_activity(self) -> tuple[bool, ...]:
        return tuple(self._unit_activity)

    def unit_eligibility(self) -> tuple[bool, ...]:
        return tuple(self._unit_eligibility)

    def incidence_samples(self) -> tuple[frozenset[str], ...]:
        """Eligible immutable samples in observation order."""

        return tuple(self._samples)

    def identity_incidence(self) -> dict[str, int]:
        """All-epoch sample frequency per identity."""

        return dict(self._incidence)

    @staticmethod
    def _not_selected_probability(
        population: int,
        absent_from: int,
        sample_size: int,
    ) -> Fraction:
        if absent_from < sample_size:
            return Fraction(0, 1)
        return Fraction(
            math.comb(absent_from, sample_size),
            math.comb(population, sample_size),
        )

    def _rarefaction(self) -> tuple[int, NumericBand]:
        window = self._samples[-self.window_size :]
        window_observed = len(set().union(*window)) if window else 0
        if self.units < self.window_size:
            return window_observed, NumericBand.coded(STATUS_INSUFFICIENT)

        all_identities = set().union(*window) if window else set()
        memberships = {
            identity: frozenset(
                index for index, sample in enumerate(window) if identity in sample
            )
            for identity in all_identities
        }
        if window_observed == 0:
            return 0, NumericBand.exact(0)

        omitted = {
            identity: self._not_selected_probability(
                self.window_size,
                self.window_size - len(indices),
                self.subsample_size,
            )
            for identity, indices in memberships.items()
        }
        point = sum(
            (Fraction(1, 1) - value for value in omitted.values()),
            Fraction(),
        )

        identities = tuple(sorted(memberships))
        variance = sum(
            (value * (Fraction(1, 1) - value) for value in omitted.values()),
            Fraction(),
        )
        for left_index, left in enumerate(identities):
            for right in identities[left_index + 1 :]:
                union_size = len(memberships[left] | memberships[right])
                joint_omitted = self._not_selected_probability(
                    self.window_size,
                    self.window_size - union_size,
                    self.subsample_size,
                )
                variance += 2 * (joint_omitted - omitted[left] * omitted[right])
        if variance < 0:
            raise ArithmeticError(
                "exact conditional rarefaction variance is negative: "
                f"{variance.numerator}/{variance.denominator}"
            )
        if variance == 0:
            band = NumericBand.exact(point)
        else:
            band = NumericBand.chebyshev(point, variance, self.alpha)
        return window_observed, band

    def _reachable_total(self) -> tuple[int, int, NumericBand, NumericBand]:
        q1 = sum(1 for count in self._incidence.values() if count == 1)
        q2 = sum(1 for count in self._incidence.values() if count == 2)
        if self.units < 2:
            coded = NumericBand.coded(STATUS_INSUFFICIENT)
            return q1, q2, coded, coded
        if self.distinct == 0:
            coded = NumericBand.coded(STATUS_UNIDENTIFIABLE)
            return q1, q2, coded, coded

        t = self.units
        d = self.distinct
        a = Fraction(t - 1, t)
        unseen = a * Fraction(q1 * (q1 - 1), 2 * (q2 + 1))
        expected = Fraction(d, 1) + unseen
        variance = (
            unseen
            + a * a * Fraction(q1 * (2 * q1 - 1) ** 2, 4 * (q2 + 1) ** 2)
            + a
            * a
            * Fraction(q1 * q1 * q2 * (q1 - 1) ** 2, 4 * (q2 + 1) ** 4)
        )
        if variance < 0:
            raise ArithmeticError(
                "exact Chao2 variance input is negative: "
                f"{variance.numerator}/{variance.denominator}"
            )
        expected_band = NumericBand.chebyshev(
            expected,
            variance,
            self.alpha,
            lower_floor=d,
        )
        remaining_band = NumericBand(
            value=max(0.0, expected_band.value - d),
            lower=max(0.0, expected_band.lower - d),
            upper=max(0.0, expected_band.upper - d),
            status_code=STATUS_NORMAL,
            uncertainty_code=expected_band.uncertainty_code,
            alpha=expected_band.alpha,
        )
        return q1, q2, expected_band, remaining_band

    def snapshot(self) -> IncidenceEstimate:
        window_observed, rarefied = self._rarefaction()
        q1, q2, expected, remaining = self._reachable_total()
        return IncidenceEstimate(
            scope_path=self.scope_path,
            epoch=self.epoch,
            channel=self.channel,
            window_size=self.window_size,
            subsample_size=self.subsample_size,
            alpha=self.alpha,
            incidence_samples=self.units,
            q1=q1,
            q2=q2,
            window_observed_results=window_observed,
            observed_results=NumericBand.exact(self.distinct),
            rarefied_results=rarefied,
            expected_results=expected,
            remaining_results=remaining,
        )
