"""Identity: what names a run, what digests a payload, what keys a query.

Nothing here does I/O and nothing here interprets meaning.  Every function is a
pure, deterministic function of its arguments, so two processes agree without
coordinating.

Three separate notions of identity live here and are deliberately **not**
interchangeable:

``payload_digest``
    A write-once byte comparison, and nothing else.  It exists so a repeated
    write can be told apart from a contradicting one.  It is deliberately named
    differently from any domain id so nobody assumes the two must agree.  The
    store never re-derives a domain id -- it stores the id the producer
    computed.

``fingerprint``
    A deterministic id over a small structured payload, used for
    :func:`projection_request_id` and :func:`question_context_id`.  Full hex
    digest, never truncated.

``query_key`` / ``query_tokens``
    The search side's **opaque** index fields.  ``run_store`` provides a
    default structural tokenizer so ingest has something to run, but the caller
    owns query normalization, the near-duplicate verdict, and every threshold.
    The store counts; it never rules.

The identity contract
---------------------

The store MAY define and compute **request** and **context** identity -- the
fingerprint of the *question asked*.  :func:`projection_request_id` and
:func:`question_context_id` are exactly that, and :class:`ProjectionScope` is
the closed vocabulary one of them is built from.

The store MUST NEVER compute or re-derive **content** identity:
``CriteriaSnapshot.id``, snapshot content digests, or source ids.  Those are the
identity of the *answer*, and they belong to the producer that computed them.
The store records the id it was given and joins on it; it never recomputes one,
because a recomputed id that disagrees with the producer's is a join that fails
silently.

**The producer owns the identity of the answer; the store owns the identity of
the question.**

``CriteriaSnapshot.id`` is the case that makes this concrete.  It is
content-addressed over criterion states on purpose, which is what makes
"nothing changed" observable as an identity rather than as an empty diff of two
distinct ids.  Folding request options into it would trade a join defect for a
signal defect and invalidate every id already stamped into a decision -- so the
pair key exists instead, and the content half of that pair arrives from
``criteria.py`` untouched.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from .result import ProjectionScope

__all__ = [
    "RunRef",
    "TOKENIZER_VERSION",
    "CORPUS_ID_RULE_VERSION",
    "PROJECTION_REQUEST_VERSION",
    "QUESTION_CONTEXT_VERSION",
    "canonical_json",
    "payload_digest",
    "fingerprint",
    "default_query_tokens",
    "default_query_key",
    "default_corpus_id",
    "projection_request_id",
    "question_context_id",
]


#: Bumped whenever :func:`default_query_tokens` or :func:`default_query_key`
#: changes.  It is stored on every ingested record, so a tokenizer change shows
#: up as a detectable **version skew** rather than as silently stale keys that
#: still look like keys.
TOKENIZER_VERSION = "run_store_structural_tokenizer_v1"

#: Bumped whenever :func:`default_corpus_id` changes.
CORPUS_ID_RULE_VERSION = "run_store_corpus_id_v1"

#: Bumped whenever the :func:`projection_request_id` payload shape changes.
PROJECTION_REQUEST_VERSION = "run_store_projection_request_v1"

#: Bumped whenever the :func:`question_context_id` payload shape changes.
QUESTION_CONTEXT_VERSION = "run_store_question_context_v1"


#: Purely structural word shape.  No stopword list and no domain vocabulary:
#: a stopword list *is* vocabulary, and AGENTS.md bans question-specific
#: vocabulary in code.
_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_.+-]*")

#: Trailing run-name segments that are timestamp-ish or attempt-ish.  Structural
#: shapes only -- digits and the literal word "attempt" -- never topic words.
_RUN_SUFFIX_RE = re.compile(r"\A(?:\d+|attempt\d*[a-z]*|v\d+|retry\d*)\Z")


@dataclass(frozen=True)
class RunRef:
    """One recorded run: where it is, what it is called, which corpus it is in.

    ``run_dir`` is always absolute.  ``corpus_id`` is the question family the
    run belongs to; it is the granularity at which contradictory URL verdicts
    were measured to be real disagreements rather than legitimate differences
    of question, which is why decisions are keyed by ``(url, question context)``
    and never by ``url`` alone.
    """

    run_dir: str
    run_name: str
    corpus_id: str

    def to_record(self) -> Mapping[str, Any]:
        return {
            "run_dir": self.run_dir,
            "run_name": self.run_name,
            "corpus_id": self.corpus_id,
        }


def _canonical(value: Any) -> Any:
    """Reduce ``value`` to JSON-serializable primitives, deterministically."""

    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _canonical(item) for key, item in sorted(value.items(), key=_by_key)}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted(_canonical(item) for item in value)
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"{type(value).__name__} has no stable serialization in run_store")


def _by_key(item: Any) -> str:
    return str(item[0])


def canonical_json(payload: Any) -> str:
    """Deterministic JSON: sorted keys, no whitespace, no NaN."""

    return json.dumps(
        _canonical(payload),
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        ensure_ascii=True,
    )


def payload_digest(payload: Any) -> str:
    """SHA-256 over the canonical JSON of ``payload``.

    Used for **write-once byte comparison only**.  It is not a domain id, it is
    not stable across a payload-shape change, and nothing downstream should
    join on it.
    """

    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def fingerprint(payload: Any) -> str:
    """A deterministic id for the *question* ``payload`` describes.

    Full SHA-256 hex digest, never truncated.  Truncating a digest to a hex
    prefix is a deliberate omission: this package refuses positional slicing on
    every code path, and an index key built from a prefix of anything is the
    same class of defect as ``search_memory._query_terms``' ``[:12]`` -- it
    makes two different inputs collide by construction.

    Why this is **not** called ``stable_id``
    ----------------------------------------

    ``question_pipeline/control.py`` (lines 1417 and 1434) exports a function
    named ``stable_id`` which is **SHA-1 truncated to a 16-character hex
    prefix**.  This one is full-width SHA-256.  Two functions sharing a name
    across the boundary while differing in algorithm *and* in width is an
    invitation to assume an id round-trips between the two sides, and it does
    not: the failure surfaces as a join that silently matches nothing, which is
    the precise defect class this store was built to eliminate.  The name is
    therefore different on purpose, and must stay different.

    Why this is **not** merged into :func:`payload_digest`
    ------------------------------------------------------

    The two bodies are byte-identical today.  They must still not be merged,
    because their *contracts* differ and only one of them is free to move:

    * :func:`payload_digest` is a write-once byte comparison.  Nothing may join
      on it, nothing may persist it as an identity, and its algorithm may be
      changed at any time without consulting a downstream consumer.
    * :func:`fingerprint` is question identity.  Downstream code joins on it,
      values are already stamped into stored rows, and its algorithm may
      **not** drift without a schema version bump and a migration.

    Merging them would make the first function's freedom to change silently
    become the second function's obligation not to.  Identical implementations
    are a coincidence of the current moment, not evidence of one concept.

    This distinction cannot be enforced by a test.  Asserting anything about
    ``control.stable_id`` from here would require importing
    ``question_pipeline``, which V1 forbids outright -- so this docstring is the
    only available guard, and it is load-bearing rather than decorative.
    """

    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def default_query_tokens(query: str) -> tuple[str, ...]:
    """A structural token set for ``query``: sorted, deduplicated, complete.

    Lowercase, split on word shape, and that is all.  No stopword list, no
    domain vocabulary, no length filter, and -- emphatically -- no truncation.

    ``question_pipeline/search_memory.py::_query_terms`` must not be copied
    here.  It ends in ``[:12]``, so a key computed from it collapses two
    different long queries onto one value.  That is a correctness bug in an
    index key, not a truncation-policy preference.

    Callers that own a better tokenizer inject it at ingest; this is the
    default, versioned by :data:`TOKENIZER_VERSION`.
    """

    return tuple(sorted(set(_TOKEN_RE.findall(query.lower()))))


def default_query_key(query: str) -> str:
    """An exact-identity key for ``query``, modulo case, punctuation, spacing.

    Order-sensitive and duplicate-sensitive on purpose: two queries with the
    same words in a different order are different queries, and only the
    *overlap* view is allowed to treat them as related.  Relatedness is
    :mod:`run_store.overlap`'s job, and it returns counts, never a verdict.
    """

    ordered = tuple(_TOKEN_RE.findall(query.lower()))
    return fingerprint({"tokenizer": TOKENIZER_VERSION, "terms": list(ordered)})


def default_corpus_id(run_name: str) -> str:
    """The question family ``run_name`` belongs to.

    Structural only: trailing segments that are pure digits, or that match
    ``attempt``/``v``/``retry`` plus digits, are dropped.  No topic words appear
    in the rule, so it stays generic across questions.  Versioned by
    :data:`CORPUS_ID_RULE_VERSION`.
    """

    parts = run_name.split("_")
    while len(parts) > 1 and _RUN_SUFFIX_RE.match(parts[len(parts) - 1]):
        parts.pop()
    return "_".join(parts) or run_name


def projection_request_id(
    *,
    projection_version: str,
    scope: ProjectionScope,
    supplied: Iterable[str],
    deliverable_tables: Iterable[str],
) -> str:
    """The id of a projection *request* -- the other half of a snapshot's key.

    A ``CriteriaSnapshot.id`` alone is unjoinable, because five call sites in
    ``pipeline.py`` pass five different optional-kwarg sets and each set changes
    the resulting id.  Measured on
    ``question_runs/earthquake_impact_20260817_052120_attempt4b``: the 11
    control decisions carry 4 distinct ``criteria_snapshot_id`` values and
    **zero** appear as any reward snapshot id.

    So the snapshot primary key is the **pair** ``(projection_request_id,
    snapshot_id)``, and this is the first half.

    * ``scope`` is a required **closed enum**, never free text.  Kwarg names
      alone are not enough: ``pipeline.py:5856`` and ``pipeline.py:5938`` pass
      an identical kwarg set over completely different row domains, and a
      kwargs-only fingerprint would call them one request -- a join that
      succeeds while meaning nothing.
    * ``supplied`` is the sorted **names** of the optional kwargs actually
      passed, never their values.  ``accepted_source_ids`` legitimately changes
      every round; folding its contents in would make every round a new request.
    * ``deliverable_tables`` goes in **verbatim**.  It is a scope declaration,
      not data volume.

    ``CriteriaSnapshot.id`` itself is untouched by all of this.  It is
    content-addressed over criterion states on purpose -- that is what makes
    "nothing changed" observable as an identity rather than as an empty diff --
    and folding options into it would trade a join defect for a signal defect
    while invalidating every id already stamped into a decision.
    """

    if not isinstance(scope, ProjectionScope):
        raise TypeError(
            "scope must be a ProjectionScope member; free-text scope is prose "
            "steering a join and is refused here"
        )
    return fingerprint(
        {
            "request_version": PROJECTION_REQUEST_VERSION,
            "projection_version": projection_version,
            "scope": scope.value,
            "supplied": sorted(str(name) for name in supplied),
            "deliverable_tables": [str(name) for name in deliverable_tables],
        }
    )


def question_context_id(
    *,
    corpus_id: str,
    task_id: str,
    topic: str,
    target_table: str,
    target_id: str,
) -> str:
    """The context a URL verdict was reached in.

    Measured on the recorded corpus: of 16 URLs carrying contradictory
    accept/reject verdicts, 11 contradict **inside** one question family and 5
    differ only **across** families -- the second group being legitimate.  A
    verdict keyed by URL alone therefore cannot distinguish a real
    inconsistency from two different questions, which is why every decision
    carries this id and the read hands back the context with the outcome.
    """

    return fingerprint(
        {
            "context_version": QUESTION_CONTEXT_VERSION,
            "corpus_id": corpus_id,
            "task_id": task_id,
            "topic": topic,
            "target_table": target_table,
            "target_id": target_id,
        }
    )
