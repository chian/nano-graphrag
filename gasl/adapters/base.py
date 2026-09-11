"""
Base graph adapter.
"""

from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import Any, Dict, Iterator, List, Optional
from ..types import AdapterCapabilities
from ..errors import AdapterCapabilityError, AdapterError


# Retrieval surfaces a filter mapping can be addressed to.
NODE_SURFACE = "nodes"
EDGE_SURFACE = "edges"
PATH_SURFACE = "paths"

# The canonical filter vocabulary, keyed by retrieval surface. Every key here is
# part of the engine's canonical graph abstraction (ids, entity/relation types,
# endpoints, descriptions) or an engine-level retrieval concept (`raw_criteria`).
# Adapters declare which of these they actually ENFORCE; anything a caller sends
# that the adapter does not enforce is rejected rather than dropped, because a
# dropped filter always fails open — it silently widens the result set.
CANONICAL_FILTER_KEYS: Dict[str, frozenset] = {
    NODE_SURFACE: frozenset(
        {"id_filter", "entity_type", "relationship_name", "description_contains", "raw_criteria"}
    ),
    EDGE_SURFACE: frozenset(
        {"source", "target", "relationship_name", "relation_type", "description_contains", "raw_criteria"}
    ),
    PATH_SURFACE: frozenset({"source_filter", "target_filter", "relation_type"}),
}

# Filter keys whose value is itself a node-filter mapping.
NESTED_NODE_FILTER_KEYS = frozenset({"source_filter", "target_filter"})

# Sentinel distinguishing "this node carries no entity_type" from "entity_type is
# the empty string". Returning "" for both is what let a wrong-depth read pass as
# a legitimate value.
ENTITY_TYPE_ABSENT = None


# ---------------------------------------------------------------------------
# Completeness disclosure
#
# A retrieval that stops early and a retrieval that ran out of matches used to
# be the same observable: both returned a list, and the caller could not tell
# them apart. Every retrieval call now states which one happened, so a bounded
# result is bounded *in the emitted data* rather than only in the adapter's
# head.
#
# The complete case is disclosed too, and disclosed positively. If completeness
# were signalled by the absence of a key, then "complete", "the adapter forgot"
# and "an older adapter that predates this mechanism" would collapse back into
# one observable, which is the defect this exists to remove.
# ---------------------------------------------------------------------------

# What kind of bound stopped a retrieval. Empty string means none did.
BOUND_KIND_NONE = ""
# The work budget in path generation was exhausted: the number of SOURCES the
# traversal was allowed to expand. It counted (source, target) pairs while path
# generation ran one graph search per pair; a single-source traversal reaches
# every target at once, so pairs are no longer a unit of work that anything
# does.
BOUND_KIND_PATH_SOURCE_BUDGET = "path_source_budget"
# A caller-supplied probe size stopped path emission. Never a default.
BOUND_KIND_PATH_EMIT_BOUND = "path_emit_bound"
# A server-side page size was in play. Transport only: the rows are all here.
BOUND_KIND_TRANSPORT_WINDOW = "transport_window"
# GRAPHWALK stopped expanding seeds: the declared per-walk seed budget ran out.
BOUND_KIND_WALK_SEED_BUDGET = "walk_seed_budget"
# GRAPHWALK stopped emitting rows: the per-walk row budget ran out. A different
# bound from the seed budget and reported as one, because "we ran out of seeds"
# and "we ran out of room" are different things for a caller to act on.
BOUND_KIND_WALK_NODE_BUDGET = "walk_node_budget"
#: Not a cap: the measured yield verdict said further seeds stop producing
#: new nodes (docs/ACQUISITION_LOOP.md, phase 4B). Distinct from every budget
#: kind so a consumer can always tell a decision from a resource limit.
BOUND_KIND_WALK_YIELD_STOP = "walk_yield_stop"


def completeness(
    *,
    complete: bool,
    returned: int,
    bound: Optional[int] = None,
    bound_kind: str = BOUND_KIND_NONE,
    residual_known: bool = False,
    residual: Optional[int] = None,
    **detail: Any,
) -> Dict[str, Any]:
    """Build the typed completeness disclosure for one retrieval call.

    - `complete`   — was every matching row delivered?
    - `returned`   — how many rows were delivered
    - `bound`      — the numeric bound that applied, or None if none existed
    - `bound_kind` — which bound; one of the BOUND_KIND_* constants
    - `residual_known` / `residual` — how many matches were left behind, when
      that is knowable. For most bounds it is not: stopping a scan early means
      the size of what was skipped was never computed. Reporting an unknown
      residual as 0 would read as "nothing was lost", so it is reported as
      unknown instead.

    `detail` carries bound-specific context (for a work budget, how much of the
    candidate space was covered). A bare "a bound fired" is not actionable; a
    coverage fraction is.
    """
    disclosure: Dict[str, Any] = {
        "complete": bool(complete),
        "returned": int(returned),
        "bound": bound,
        "bound_kind": bound_kind,
        "residual_known": bool(residual_known),
        "residual": residual,
    }
    disclosure.update(detail)
    return disclosure


def complete_result(returned: int) -> Dict[str, Any]:
    """Disclosure for a retrieval that delivered every match, unbounded."""
    return completeness(
        complete=True,
        returned=returned,
        bound=None,
        bound_kind=BOUND_KIND_NONE,
        residual_known=True,
        residual=0,
    )


def node_entity_type(row: Any) -> Optional[str]:
    """Read the canonical `entity_type` off an adapter node row.

    Adapter rows nest graph properties under `data` (`{"id", "data", "type"}`),
    while rows that have already been through a command carry properties at the
    top level. Reading only one of those depths returns None on the other and
    that None then reads as "untyped node" rather than "looked in the wrong
    place", so both depths are checked here and absence is reported as None —
    never as an empty string that compares equal to a real value.

    Ambiguity is resolved the same way `field_resolution.resolve_field` resolves
    it: when both depths carry a value and they *disagree*, there is no single
    right answer and this returns None rather than silently preferring one. Two
    functions in the same engine must not disagree about what ambiguity means.
    Agreeing duplicates are not ambiguous and resolve normally.
    """
    if not isinstance(row, Mapping):
        return ENTITY_TYPE_ABSENT

    found = []
    nested = row.get("data")
    if isinstance(nested, Mapping) and nested.get("entity_type") is not None:
        found.append(str(nested["entity_type"]).strip('"').strip("'"))
    if row.get("entity_type") is not None:
        found.append(str(row["entity_type"]).strip('"').strip("'"))

    if not found:
        return ENTITY_TYPE_ABSENT
    if len(set(found)) > 1:
        return ENTITY_TYPE_ABSENT
    return found[0]


def select_filters(filters: Mapping, surface: str) -> Dict[str, Any]:
    """Return the subset of `filters` addressed to one retrieval surface.

    Callers that parse a single criteria string into a union of node-, edge- and
    path-shaped keys use this to route each surface its own keys instead of
    handing the whole union to every surface and relying on the unknown keys
    being ignored. Reserved control keys (leading underscore) always pass
    through.
    """
    allowed = CANONICAL_FILTER_KEYS.get(surface, frozenset())
    return {
        key: value
        for key, value in filters.items()
        if str(key).startswith("_") or key in allowed
    }


class GraphAdapter(ABC):
    """Base class for graph adapters."""

    # Per-surface filter keys this adapter actually enforces. Subclasses may
    # only NARROW these. The vocabulary is a closed engine-side set: an adapter
    # that could extend it would put a backend-specific filter name into command
    # code, which is exactly the boundary this mechanism exists to hold.
    ENFORCED_FILTER_KEYS: Dict[str, frozenset] = CANONICAL_FILTER_KEYS

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        declared = getattr(cls, "ENFORCED_FILTER_KEYS", {})
        unknown_surfaces = set(declared) - set(CANONICAL_FILTER_KEYS)
        if unknown_surfaces:
            raise TypeError(
                f"{cls.__name__}.ENFORCED_FILTER_KEYS declares unknown retrieval "
                f"surface(s) {sorted(unknown_surfaces)}; known surfaces are "
                f"{sorted(CANONICAL_FILTER_KEYS)}."
            )
        for surface, keys in declared.items():
            extra = set(keys) - set(CANONICAL_FILTER_KEYS[surface])
            if extra:
                raise TypeError(
                    f"{cls.__name__}.ENFORCED_FILTER_KEYS[{surface!r}] declares "
                    f"{sorted(extra)}, which are not in the canonical filter "
                    f"vocabulary. Adapters may only narrow the vocabulary, never "
                    f"extend it: a backend-specific filter name here would leak "
                    f"into command code."
                )

    def __init__(self, graph_instance: Any, graph_metadata: Optional[Dict[str, Any]] = None):
        self.graph = graph_instance
        self.graph_metadata: Optional[Dict[str, Any]] = graph_metadata
        self.capabilities = self._get_capabilities()
        # Disclosure for the most recent retrieval call on this adapter. Scoped
        # to a single call: read it immediately after the call whose
        # completeness you want, before issuing another. It is seeded with the
        # zero-row complete case so that a caller reading it on a fresh adapter
        # gets a well-formed disclosure rather than None — but every retrieval
        # below overwrites it unconditionally, so a stale value can only be read
        # by a caller that skipped its own retrieval.
        self._last_completeness: Dict[str, Any] = complete_result(0)

    def _disclose(self, disclosure: Dict[str, Any]) -> Dict[str, Any]:
        """Record the completeness of the retrieval that is about to return."""
        self._last_completeness = disclosure
        return disclosure

    def last_completeness(self) -> Dict[str, Any]:
        """The completeness disclosure of the most recent retrieval call."""
        return dict(self._last_completeness)

    def _validate_filters(self, filters: Any, surface: str, operation: str) -> Dict[str, Any]:
        """Fail closed on any filter this surface will not enforce.

        A filter key that a surface does not understand used to be dropped in
        silence, which turns a constraint into a pass-through: the caller sees a
        successful call over an unfiltered result set and cannot tell the
        difference between "nothing was excluded" and "the filter never ran".
        Every rejection here names the offending key and the vocabulary this
        surface does enforce, so the failure is diagnosable at the call site.
        """
        adapter_name = type(self).__name__
        if not isinstance(filters, Mapping):
            raise AdapterError(
                f"{operation} expects a filter mapping for surface '{surface}', "
                f"got {type(filters).__name__} ({filters!r}). Endpoint filters must be "
                f"expressed as a mapping, e.g. {{'id_filter': <node id>}}.",
                adapter_name,
                operation,
            )

        canonical = CANONICAL_FILTER_KEYS.get(surface, frozenset())
        enforced = self.ENFORCED_FILTER_KEYS.get(surface, frozenset())
        requested = [key for key in filters if not str(key).startswith("_")]

        # Two different failures wear the same shape here, and telling them apart
        # is what decides whether retrying can ever help.
        #   - misaddressed: the key is not in this surface's vocabulary at all.
        #     The command is wrong and rewriting it can fix that.
        #   - unimplemented: the key is canonical for this surface but this
        #     backend cannot translate it. No rewrite will ever satisfy it.
        misaddressed = sorted(key for key in requested if key not in canonical)
        unimplemented = sorted(
            key for key in requested if key in canonical and key not in enforced
        )

        if misaddressed:
            other_surfaces = {
                name: sorted(set(keys) & set(misaddressed))
                for name, keys in CANONICAL_FILTER_KEYS.items()
                if name != surface and set(keys) & set(misaddressed)
            }
            hint = (
                f" Key(s) address surface(s): {other_surfaces}."
                if other_surfaces
                else " Key(s) are not part of the canonical filter vocabulary."
            )
            raise AdapterError(
                f"{operation} received filter key(s) {misaddressed} that surface "
                f"'{surface}' does not accept; refusing to run an unconstrained query. "
                f"Filter keys for '{surface}': {sorted(canonical)}.{hint}",
                adapter_name,
                operation,
            )

        if unimplemented:
            raise AdapterCapabilityError(
                f"{operation} cannot run: adapter '{adapter_name}' does not implement "
                f"filter key(s) {unimplemented} on surface '{surface}'. The command is "
                f"well-formed — this is a gap in the {adapter_name} backend, not in the "
                f"command, so retrying or rewriting it against this adapter will not "
                f"help. Keys this adapter implements for '{surface}': {sorted(enforced)}.",
                adapter_name,
                operation,
                unsupported_keys=unimplemented,
                surface=surface,
            )

        for key in NESTED_NODE_FILTER_KEYS & set(filters):
            nested = filters[key]
            if not isinstance(nested, Mapping):
                raise AdapterError(
                    f"{operation} filter '{key}' must be a node-filter mapping, got "
                    f"{type(nested).__name__} ({nested!r}). Use e.g. "
                    f"{{'{key}': {{'id_filter': <node id>}}}}.",
                    adapter_name,
                    operation,
                )
            self._validate_filters(nested, NODE_SURFACE, f"{operation}.{key}")

        return dict(filters)


    @abstractmethod
    def _get_capabilities(self) -> AdapterCapabilities:
        """Get adapter capabilities."""
        pass
    
    @abstractmethod
    def find_nodes(self, filters: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Find nodes matching filters."""
        pass
    
    @abstractmethod
    def find_edges(self, filters: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Find edges matching filters."""
        pass
    
    @abstractmethod
    def find_paths(self, filters: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Find paths matching filters."""
        pass

    def iter_paths(self, filters: Dict[str, Any]) -> Iterator[Dict[str, Any]]:
        """Yield path results incrementally.

        Adapters may override this with a true iterator. The default fallback
        simply yields the materialized `find_paths` results.
        """
        for row in self.find_paths(filters):
            yield row
    
    def get_schema(self) -> Dict[str, Any]:
        """Get graph schema information."""
        return {
            "node_labels": self._get_node_labels(),
            "edge_types": self._get_edge_types(),
            "node_properties": self._get_node_properties(),
            "edge_properties": self._get_edge_properties()
        }
    
    @abstractmethod
    def _get_node_labels(self) -> List[str]:
        """Get available node labels."""
        pass
    
    @abstractmethod
    def _get_edge_types(self) -> List[str]:
        """Get available edge types."""
        pass
    
    @abstractmethod
    def _get_node_properties(self) -> List[str]:
        """Get available node properties."""
        pass
    
    @abstractmethod
    def _get_edge_properties(self) -> List[str]:
        """Get available edge properties."""
        pass
