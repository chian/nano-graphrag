"""Token-set overlap **counting**.  Counts, never verdicts, never thresholds.

This module is a pure set primitive over caller-supplied token tuples.  It does
not know what a query is, does not normalize anything, does not decide what
"near-duplicate" means, and holds no threshold constant.

That division is deliberate and it is the whole reason the search side works.
The planner is currently told "do not repeat a previous query" while being shown
a truncated sample, and across the recorded corpus **21,848 of 23,240 query
instances re-issue a query already run somewhere** (2,774 distinct queries).
Fixing that needs the caller to see *measured* overlap against the *complete*
prior set and rule on it with its own policy.  A boolean handed down from the
store would bake this package's guess about similarity into the caller's
decision, and nobody could see the guess afterwards.

So: overlap counts go out, and ``question_pipeline`` rules on them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

__all__ = ["OverlapCounts", "count_overlap", "count_overlaps"]


@dataclass(frozen=True)
class OverlapCounts:
    """The measured relationship between two token sets.

    Every field is a count or a set.  There is no score, no ratio blessed as
    "the" similarity, and no verdict.  A caller wanting Jaccard, containment,
    or anything else has the numerators and denominators to compute it and owns
    the choice.

    This type is the **measurement**, and it is the store's.  A caller's verdict
    type must hold an ``OverlapCounts`` **by reference** and must not restate
    ``shared``/``left_only``/``right_only``/``left_size``/``right_size`` as
    fields of its own.  Restating them duplicates one identity across two types,
    and it lets a verdict-named object be constructed carrying only counts --
    that is, with no threshold ever applied -- which makes "this is a duplicate"
    indistinguishable from "nobody has judged yet".

    Reads surface this under the ``overlap`` key of each record, via
    :meth:`to_record`.
    """

    shared: int
    left_only: int
    right_only: int
    left_size: int
    right_size: int
    shared_tokens: tuple[str, ...]

    def to_record(self) -> Mapping[str, Any]:
        return {
            "shared": self.shared,
            "left_only": self.left_only,
            "right_only": self.right_only,
            "left_size": self.left_size,
            "right_size": self.right_size,
            "shared_tokens": list(self.shared_tokens),
        }


def count_overlap(left: Iterable[str], right: Iterable[str]) -> OverlapCounts:
    """Count how two token collections relate.  Set semantics; order-free."""

    left_set = frozenset(left)
    right_set = frozenset(right)
    shared = left_set & right_set
    return OverlapCounts(
        shared=len(shared),
        left_only=len(left_set - right_set),
        right_only=len(right_set - left_set),
        left_size=len(left_set),
        right_size=len(right_set),
        shared_tokens=tuple(sorted(shared)),
    )


def count_overlaps(
    left: Iterable[str], rights: Mapping[str, Iterable[str]]
) -> tuple[tuple[str, OverlapCounts], ...]:
    """Count ``left`` against every entry of ``rights``.

    Returns **every** pair, in sorted key order.  Nothing is filtered by a
    threshold, nothing is ranked by shared count, and nothing is truncated:
    ordering by overlap would be a ranking, and ranking is selection wearing a
    sort.
    """

    left_set = frozenset(left)
    return tuple(
        (key, count_overlap(left_set, rights[key])) for key in sorted(rights)
    )
