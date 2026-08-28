"""Split a list across model calls without shortening anything in it.

A prompt payload that does not fit has two honest responses: send less of it,
or send it in more calls. Sending less requires a claim about what was removed
and how much it mattered, and that claim is made by code that cannot see the
answer. Sending more calls requires no such claim -- every item arrives whole,
in some call, and each call is told which slice of the whole it is looking at.

This module is the second response. It is a pure leaf: it imports nothing from
the package, decides nothing about policy, and knows nothing about what the
items are. Callers decide the budget and what to do with the windows.

The invariant, which every consumer may rely on: the concatenation of the
windows is the input list, in order, with nothing removed and nothing altered.
An item larger than the budget on its own gets a window to itself rather than
being cut, because a clipped record is worse evidence than an oversized one --
a model can see that a record is large, but cannot see that one was truncated.
"""

from __future__ import annotations

import json
from typing import Any, Iterable, Sequence


def measured_size(item: Any) -> int:
    """Serialized size of one item, in the units budgets are denominated in."""

    return len(json.dumps(item, default=str))


def window_items(
    items: Sequence[Any] | Iterable[Any],
    *,
    budget: int,
) -> list[list[Any]]:
    """Group ``items`` into windows that each fit ``budget`` where possible.

    Grouping is by measured serialized size rather than by a count, so a list
    of unusually large items produces more windows instead of producing
    oversized calls. A count-based grouping composed with a size-based budget
    is how a losslessly-windowed payload ends up clipped one layer up: the
    group is chosen without reference to the quantity the budget constrains.

    Returns ``[]`` for no items -- never ``[[]]`` -- so ``window_count`` is
    zero when there is nothing to send rather than one empty call.
    """

    budget = max(1, int(budget or 1))
    windows: list[list[Any]] = []
    current: list[Any] = []
    size = 0

    for item in items or []:
        length = measured_size(item)
        if current and size + length > budget:
            windows.append(current)
            current, size = [], 0
        current.append(item)
        size += length

    if current:
        windows.append(current)
    return windows


def window_text(text: str, *, budget: int) -> list[str]:
    """Split ``text`` into contiguous windows whose concatenation is ``text``.

    The list counterpart is ``window_items``; this is the same invariant for a
    payload that is one long string rather than a sequence of records, and it
    lives here so there is one implementation of that invariant rather than one
    per caller.

    The split prefers a line boundary inside the budget and falls back to the
    budget itself, so text with no newlines still windows rather than being
    cut. Returns ``[]`` for empty text -- never ``[""]`` -- so a window count of
    zero means there was nothing to send.
    """

    budget = max(1, int(budget or 1))
    if not text:
        return []

    windows: list[str] = []
    start = 0
    length = len(text)
    while start < length:
        end = min(length, start + budget)
        if end < length:
            boundary = text.rfind("\n", start + 1, end)
            if boundary > start:
                end = boundary + 1
        windows.append(text[start:end])
        start = end
    return windows


def window_stamps(index: int, count: int) -> dict[str, int]:
    """The disclosure a windowed call carries.

    Honest by construction rather than by assertion: it states which slice this
    is and how many there are, both of which are facts about the split. It
    makes no claim about what was removed, because nothing was.
    """

    return {"window_index": index, "window_count": count}
