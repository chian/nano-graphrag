"""The engine's one sampler.

There were two. `LLMSearchRefinementAgent.sample_rows` built a head/body/tail
stratified sample, and on every reachable call path it returned a plain prefix
instead: `run_search_refinement` filled a list to `sample_limit` and then asked
for `k=sample_limit` rows from it, so `len(items) <= limit` was always true and
the stratifier never executed. It was a tuning surface that could not be fired
— worse than an uncited constant, because it advertised control nothing had.

`_deterministic_random_tail` in `process_runtime` was the one that worked:
seeded from content so a rerun on the same data draws the same rows, shuffling
the full index range so the draw is not biased toward whatever order the
producer happened to emit, and returning everything when asked for more than
exists rather than pretending to sample. That implementation is this one, moved
here so both call paths share it.

Sampling is positional truncation whenever the caller treats the result as the
whole population, so callers must say what they are doing: a sample is
defensible as a *probe* whose output is labelled a probe, and indefensible as a
quiet cut that a consumer reads as everything.
"""

from __future__ import annotations

import hashlib
import random
from typing import Any, Iterable, List, Sequence, TypeVar

T = TypeVar("T")


def deterministic_sample(items: Sequence[T], *, seed_text: str, k: int) -> List[T]:
    """`k` items drawn without bias from position, reproducibly.

    The seed is derived from `seed_text` plus the population size, so the same
    question over the same data draws the same rows on every rerun — a sample
    that moves between runs makes two runs incomparable, and comparing runs is
    the entire point of the experiment harness this feeds.

    Returns everything when `k` covers the population. The draw is over the full
    index range rather than over a head/tail split, because a head/tail split is
    still a positional choice: it just hides the position dependence behind an
    arithmetic that looks deliberate.
    """
    population = list(items or [])
    if k >= len(population):
        return population
    if k <= 0:
        return []
    seed_material = f"{seed_text}|{len(population)}"
    seed = int(hashlib.sha1(seed_material.encode("utf-8")).hexdigest()[:8], 16)
    rng = random.Random(seed)
    indices = list(range(len(population)))
    rng.shuffle(indices)
    # Sorted so the sample preserves the population's relative order. Which rows
    # are drawn is the random part; presenting them shuffled would additionally
    # scramble an ordering the caller may have established on purpose.
    return [population[index] for index in sorted(indices[:k])]


def take_all(items: Iterable[Any]) -> List[Any]:
    """Materialize an iterable with no bound. Named so the absence is explicit."""
    return list(items or [])
