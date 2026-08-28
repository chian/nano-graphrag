"""Provenance slots the engine reads off rows, and how a weight was derived.

This module exists because `gasl/commands/` used to import
`nano_graphrag.graph_slots` to read provenance. That is the dependency running
the wrong way — the generic query engine reaching into the ingestion layer —
and it carried a concrete invariant violation with it: `get_source_refs` falls
back to `source_papers`, which `docs/RUNTIME_INVARIANTS.md` names verbatim as a
forbidden feature-specific field. Every COLLAPSE, PROJECT and AGGREGATE reached
that fallback transitively, and `tools/check_runtime_invariants.py` reported a
clean tree because the literal lives outside the paths it scans.

So the accessors move here, and the legacy aliases do not come with them. A
graph that genuinely stores provenance under another key declares where, via
the contract (`source_ref_field`); it does not get a hardcoded guess.

## Weight bases

A number's value is not enough to interpret it — reward and audit need to know
what produced it. `1.0` from a row with a single cited source and `1.0` from a
row with no provenance at all are the same number and mean opposite things, and
the second is exactly the "no signal and no problem are the same observable"
shape the engine is not allowed to have. Every weight therefore travels with a
basis token naming its derivation.

**Each basis names its own dedup domain.** A count deduplicated within one row
and a count deduplicated across a group's rows answer different questions —
twelve rows citing one source versus twelve rows citing twelve — and a single
token covering both would move the arithmetic while leaving the ambiguity
exactly where it was. Hence `..._ROW` and `..._GROUP` are separate tokens, and
a cross-row-deduped number is never emitted under a row-grain basis.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from .field_resolution import read_field_path


#: Canonical slot holding the source documents a row is evidenced by.
CANONICAL_SOURCE_REFS = "source_refs"
#: Canonical slot holding the chunk ids a row was extracted from.
CANONICAL_SOURCE_CHUNKS = "source_chunks"
#: Contract key naming where provenance lives when it is not in the canonical
#: slot. This is the same shape as the contract's existing `label_field`,
#: `metric_field` and `row_weight_field` declarations: the producer says which
#: of ITS columns holds the concept, and the engine reads that rather than
#: guessing a name.
CONTRACT_SOURCE_REF_FIELD = "source_ref_field"

# Weight derivation bases. Flat tokens, each naming its dedup domain where it
# has one.
WEIGHT_BASIS_CONTRACT_ROW_WEIGHT = "contract_row_weight"
WEIGHT_BASIS_RESOLVED_METRIC = "resolved_metric"
WEIGHT_BASIS_LIST_LENGTH = "list_length"
WEIGHT_BASIS_SOURCE_REF_COUNT_ROW = "source_ref_count_row"
WEIGHT_BASIS_SOURCE_REF_COUNT_GROUP = "source_ref_count_group"
#: The row carried no evidence of any kind and was weighted 1.0 by default.
#: This is the token the whole basis mechanism exists to make visible: without
#: it, "one source" and "no sources" are both the number 1.
WEIGHT_BASIS_NO_EVIDENCE_DEFAULT = "no_evidence_default"

#: The upstream declared a weight column but no basis for it, so the derivation
#: is genuinely unknown. This exists so that a basis is NEVER a bare channel
#: name: "it came from a contract" says which pipe carried the number, not what
#: produced it, and a pipe name read as a derivation is the pass-through erasure
#: this vocabulary exists to prevent.
WEIGHT_BASIS_UNKNOWN = "unknown"

#: Separator for the two composition forms below. Both are parsed by
#: `basis_components`, in this module, beside the functions that write them --
#: an encoding whose only reader is a human eye is text, not a typed value.
BASIS_INHERIT_SEP = ":"
BASIS_MIX_SEP = "+"

#: Bases whose weight is derived from provenance rather than asserted.
EVIDENCE_BASES = frozenset(
    {WEIGHT_BASIS_SOURCE_REF_COUNT_ROW, WEIGHT_BASIS_SOURCE_REF_COUNT_GROUP}
)


def inherited_basis(basis: str, inherited: str) -> str:
    """Compose a basis that was read from an upstream contract's declaration.

    A weight taken from a contract's `row_weight_field` records only *that* it
    came from a contract, which erases what the upstream actually derived it
    from. That erasure is a laundering channel with a live path through this
    engine: PROJECT writes a defaulted `1.0` into a column, declares that column
    as `row_weight_field`, and COLLAPSE then reads it back and labels it
    `contract_row_weight` -- so a row that had no evidence at all arrives at the
    second hop wearing a basis that sounds like a real derivation.

    Carrying the upstream basis through instead keeps `no_evidence_default`
    visible however many hops it travels. When the upstream declared no basis at
    all -- any contract built before this vocabulary existed -- the result is
    `contract_row_weight:unknown` rather than a bare `contract_row_weight`,
    because "some contract said so" is a channel and must never be readable as
    a derivation.
    """
    return f"{basis}{BASIS_INHERIT_SEP}{inherited or WEIGHT_BASIS_UNKNOWN}"


def combine_bases(bases: Iterable[str]) -> str:
    """One basis describing a column whose rows were derived differently.

    Collapsing a mix to a single winner would hide the weakest member, so every
    distinct basis is kept and `basis_components` reads them all back.
    """
    distinct = sorted({str(basis) for basis in bases if basis})
    return BASIS_MIX_SEP.join(distinct)


def basis_components(basis: str) -> List[str]:
    """Every originating basis inside a possibly composed basis token."""
    text = str(basis or "")
    if not text:
        return []
    out: List[str] = []
    for part in text.split(BASIS_MIX_SEP):
        if not part:
            continue
        # The rightmost inheritance segment is the originating derivation; the
        # segments before it are the channels that forwarded it.
        out.append(part.split(BASIS_INHERIT_SEP)[-1])
    return out


def underlying_basis(basis: str) -> str:
    """The originating basis, for a token known to describe one derivation."""
    components = basis_components(basis)
    return components[0] if len(components) == 1 else ""


def is_no_evidence(basis: str) -> bool:
    """True when ANY row behind this weight came from the no-provenance default.

    Deliberately pessimistic for a mixed column. A projection where half the
    rows carried no provenance is not an evidenced column, and answering False
    here because the other half was fine is how a partially-empty weight becomes
    indistinguishable from a real one at the consumer.
    """
    return WEIGHT_BASIS_NO_EVIDENCE_DEFAULT in basis_components(basis)


def _as_list(value: Any) -> List[str]:
    """Normalize a provenance slot's value to a list of ref strings."""
    if value is None:
        return []
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    if isinstance(value, (list, tuple, set)):
        out: List[str] = []
        for item in value:
            if item is None:
                continue
            text = str(item).strip()
            if text:
                out.append(text)
        return out
    text = str(value).strip()
    return [text] if text else []


def source_ref_paths(contract: Optional[Mapping[str, Any]] = None) -> List[str]:
    """Where to look for a row's source refs, most authoritative first.

    A contract-declared location wins, because it is the producer stating a
    fact about its own payload rather than the engine guessing. The canonical
    slot is checked at both the row's top level and inside the adapter's `data`
    envelope, since adapter rows nest graph properties one level down.
    """
    paths: List[str] = []
    declared = str((contract or {}).get(CONTRACT_SOURCE_REF_FIELD) or "").strip()
    if declared:
        paths.append(declared)
    for path in (
        CANONICAL_SOURCE_REFS,
        f"data.{CANONICAL_SOURCE_REFS}",
        CANONICAL_SOURCE_CHUNKS,
        f"data.{CANONICAL_SOURCE_CHUNKS}",
    ):
        if path not in paths:
            paths.append(path)
    return paths


def row_source_refs(
    row: Any,
    *,
    contract: Optional[Mapping[str, Any]] = None,
) -> List[str]:
    """Every distinct source ref this row carries, in first-seen order.

    Deduplication here is WITHIN ONE ROW only. A caller counting evidence
    across rows must dedupe across them itself — see `distinct_source_refs` —
    because a source cited by twelve rows is one source, not twelve.
    """
    for path in source_ref_paths(contract):
        refs = _as_list(read_field_path(row, path))
        if refs:
            return list(dict.fromkeys(refs))
    return []


def distinct_source_refs(
    rows: Sequence[Any],
    *,
    contract: Optional[Mapping[str, Any]] = None,
) -> List[str]:
    """Source refs across many rows, deduplicated ACROSS rows.

    This is the count that may legitimately be called evidence for a group.
    Summing per-row counts instead is the propagation-as-replication error: it
    reports one source cited by twelve rows as twelve units of support.
    """
    seen: Dict[str, None] = {}
    for row in rows:
        for ref in row_source_refs(row, contract=contract):
            seen.setdefault(ref, None)
    return list(seen)
