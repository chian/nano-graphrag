"""Pure field-to-chunk trace annotations for materialised table rows.

This module performs deterministic string containment only. Its annotations
support inspection and source navigation; evidence acceptance is owned by the
durable registry's exact source/version/chunk/span/assertion chain.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Mapping

FIELD_PROVENANCE_SUFFIX = "_source_chunks"

#: Provenance columns are recognised by the shape of their name, not by an
#: enumerated list of spellings. Every provenance column in this codebase --
#: `source_refs`, `source_chunks`, `edge_source_refs`, `edge_source_chunk`,
#: `relation_source_refs`, `<field>_source_chunks` -- contains "ref" or
#: "chunk", and a list of six suffixes only ever catches the six somebody
#: thought of. A pattern catches the next spelling too.
#:
#: This is the one place a regex beats an enumeration: the thing being matched
#: really is a naming convention, so matching the name is the direct test
#: rather than a proxy for one.
#:
#: It lives here rather than with any single consumer because the convention is
#: this module's subject, and it now has two consumers that must agree: what
#: `criteria` refuses to treat as a datapoint and what `goals` refuses to treat
#: as a fillable column have to be the same set, or the run will search for
#: columns it will never credit.
PROVENANCE_NAME_RE = re.compile(r"(?:^|_)(?:refs?|chunks?)(?:$|_)", re.I)


def is_provenance_name(name: Any) -> bool:
    """True when a column name denotes provenance rather than an observation."""

    return bool(PROVENANCE_NAME_RE.search(str(name or "")))

#: Records the chunking a row's `source_chunks` ids were minted under, as
#: "<chunk_size>:<chunk_overlap>". Chunk ids are only meaningful relative to a
#: split: change `chunk_size` and `X_chunk_3` names different text. Without
#: this, a row seeded from an earlier run would be grounded against a
#: reconstruction that does not match what its extractor saw, producing a
#: citation that is confidently wrong and raises nothing.
CHUNK_PARAMS_FIELD = "_chunk_params"


def chunk_params(chunk_size, chunk_overlap) -> str:
    return f"{int(chunk_size)}:{int(chunk_overlap)}"

#: Values shorter than this are not matched. "1" or "NA" occurs in almost any
#: chunk, so a hit would be coincidence rather than evidence.
MIN_GROUNDABLE_VALUE_CHARS = 3

_WS_RE = re.compile(r"\s+")



def _normalize_for_match(text):
    return _WS_RE.sub(" ", str(text or "")).strip().casefold()

def derive_field_provenance(row, chunk_texts, groundable_fields):
    """Attribute each field to the parent chunks whose text contains its value.

    ``chunk_texts`` maps chunk id -> that chunk's text. Returns
    ``(row_with_provenance, report)``. Deterministic: same row and same chunks
    give the same answer, and no citation can name a chunk that does not
    contain the value.

    ``groundable_fields`` is **required** and is the exact, declared set of
    columns that are datapoints -- normally the table spec's own columns. It is
    not optional and there is no "ground everything" fallback, because the
    question "does this value appear in the text" is only meaningful for a
    measured value.

    Iterating every key in the row was the original mistake: a materialised row
    also carries the graph structure it came from, so `src_id = "COVID-19"`
    (the source endpoint of the edge) got matched against five chunks. That
    said nothing about whether the edge was supported -- the entity exists
    because extraction built the graph, not because a chunk contains its name.

    The first fix was a denylist of structural fields, which was the same
    mistake once removed: a denylist only excludes what its author thought of
    and admits every field nobody anticipated. An allowlist of declared
    columns fails safe -- an unrecognised field is simply not a datapoint.

    A traversal's COLLAPSE and AGGREGATE mint structural columns describing the
    GROUPING rather than the subject -- `occurrence_count`, `items`, `item_ids`.
    Those reach exported tables, and they reach them inside compiled answer
    views, which are declared by construction: the answer-layer builders take
    their measure field from the contract's `metric_field`, and for a COLLAPSE
    contract that field IS `occurrence_count`. So they arrive allowlisted, and
    `criteria.project_rows` mints criteria from them. Measured across recorded
    runs this fired at scale rather than in theory -- one run minted 12,206
    structural criteria of which 646 reached SUPPORTED, another 2,081 and 94.

    The declared-field allowlist keeps those trace annotations scoped to
    intended datapoint columns. It does not establish criterion support.

    A field is grounded when its value appears verbatim (whitespace- and
    case-normalised) in at least one parent chunk. Several chunks may contain
    it, and all of them are recorded -- multiple pieces of evidence for one
    cell is the normal case, not a conflict.
    """

    groundable = {str(f) for f in (groundable_fields or ())}
    out = dict(row)
    grounded, ungrounded = {}, []

    for field, value in list(row.items()):
        name = str(field)
        if name.startswith("_"):
            continue
        if name not in groundable:
            continue
        needle = _normalize_for_match(value)
        if len(needle) < MIN_GROUNDABLE_VALUE_CHARS:
            continue
        hits = sorted(
            chunk_id
            for chunk_id, text in (chunk_texts or {}).items()
            if needle in _normalize_for_match(text)
        )
        if hits:
            out[f"{name}{FIELD_PROVENANCE_SUFFIX}"] = hits
            grounded[name] = hits
        else:
            ungrounded.append(name)

    return out, {
        "fields_grounded_verbatim": sorted(grounded),
        "fields_not_verbatim": sorted(ungrounded),
        "chunks_searched": len(chunk_texts or {}),
        "declared_datapoint_fields": len(groundable),
        "grounding": "deterministic_verbatim_match",
    }
