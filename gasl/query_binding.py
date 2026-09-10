"""Bind the GASL query surface to the generic acquisition Episode.

The surface vocabulary and nesting live here, at the binding boundary
(phase G; design: experiments/log/phase-G-gasl-query-binding.md §1):

    gasl-query Episode                        [NEW: bound by this phase]
      unit: one completed GASL operation track
      credit: distinct opaque identities the operation contributed (kernel fan-up)
      └── operation unit
            GRAPHWALK → child Episode = existing WALK_GRAIN (walk ⊃ seed)   [bound]
            FIND / other graph-reading ops → Leaf
              (unit: one executed operation; credits: opaque encountered identities)
            (seed grain beneath a walk stays unbound with per-depth facet disclosure)

    source: the two-phase planner (model string work proposes plans/operations;
            the numerical controller verdict decides continue/stop)
    fan-up: operation credits -> query record; a bound-cut walk's credits stay
            nested and NEVER enter query incidence (charter §Fan-up)
    nesting: walk Episode ⊂ query Episode; FIND/SUBGRAPH/GRAPHCONNECT/
             GRAPHPATTERN are Leaves of the query Episode (no scope of their own)

Only the query and walk grains are bound. Per-depth encounter disclosure
preserves the seed-grain observations needed to evaluate that later binding
without claiming that a seed Episode currently runs. The command handlers
supply the graph adapter and remain responsible for command parsing and
result storage; the executor injects its existing planner, track, repair,
and adaptation machinery through :class:`QueryBindingServices` — this module
adds no machinery of its own, it wires the existing parts into one
composition (the Phase G operator ruling: binding layers to Episodes, that
is all).
"""

import json
from dataclasses import dataclass, replace
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

from method_loop import (
    END_BOUND_HIT,
    END_EXHAUSTED,
    END_REASON_UNIT_BOUND,
    END_SOURCE_FAILED,
    END_YIELD_STOP,
    Context,
    Contribution,
    Episode,
    EpisodeRecord,
    EpisodeUpdate,
    Grain,
    Leaf,
    SourceEnd,
    UnitRecord,
    UnitView,
    leaves,
)
from rarefaction import (
    OBSERVATION_FAILED,
    ChannelSchema,
    ControlStep,
    ControllerConfig,
    IncidenceObservation,
    IncidenceState,
    bind_controller,
)

from .adapters.base import (
    BOUND_KIND_NONE,
    BOUND_KIND_WALK_NODE_BUDGET,
    BOUND_KIND_WALK_SEED_BUDGET,
    BOUND_KIND_WALK_YIELD_STOP,
    GraphAdapter,
    complete_result,
    completeness,
)


# The walk's yield-stop policy (docs/ACQUISITION_LOOP.md, phase 4B). The paired
# component reduces its complete incidence vector to predicted next-seed
# marginal hypervolume. The fixed scalar threshold requires its upper band to
# be zero for the declared streak.
WALK_YIELD_CONTROL = ControllerConfig.uniform(
    ("overall",), gamma=0.0, rho=0.0, streak_length=8
)

# The grain is declared ONCE, as data, with its unit and credit sentences and
# its policy (docs/ACQUISITION_LOOP.md rule 4). The scope level and key that
# used to be string literals at the episode-composition call site come from
# this declaration.
WALK_GRAIN_NAME = "walk"


def _walk_grain(channel_schema: ChannelSchema) -> Grain:
    return Grain(
        name=WALK_GRAIN_NAME,
        unit=(
            "one seed expansion: every hop this walk makes outward from one "
            "seed node, to the requested depth"
        ),
        result="the binding-defined node encounters returned by that seed",
        controller=bind_controller(
            channel_schema=channel_schema,
            control=WALK_YIELD_CONTROL,
        ),
    )

# The query grain's yield-stop policy (phase G, design §2). Thresholds are
# STATED DEFAULTS, NEVER FITTED so a verdict fires — the same numbers and the
# same documentation posture as WALK_YIELD_CONTROL above and the provider
# grains: the scalar hypervolume threshold is declared before observation and
# is not fitted to make a verdict fire. At the root, a low-hypervolume stop
# whose column state remains incomplete is reported as `root_incomplete`.
QUERY_YIELD_CONTROL = ControllerConfig.uniform(
    ("overall",), gamma=0.0, rho=0.0, streak_length=8
)

QUERY_GRAIN_NAME = "query"


def _query_grain() -> Grain:
    return Grain(
        name=QUERY_GRAIN_NAME,
        unit=(
            "one completed GASL graph-reading operation, including its "
            "compile and repair attempts"
        ),
        result="the binding-defined graph-node encounters returned by the operation",
        controller=bind_controller(
            channel_schema=ChannelSchema.single(),
            control=QUERY_YIELD_CONTROL,
        ),
    )


def _incidence_state(record: EpisodeRecord) -> IncidenceState:
    state = record.controller_state
    if not isinstance(state, IncidenceState):
        raise TypeError("GASL Episode did not use the incidence controller")
    return state


def _incidence_step(record: UnitRecord | UnitView) -> ControlStep:
    step = record.controller_step
    if not isinstance(step, ControlStep):
        raise TypeError("GASL unit did not use the incidence controller")
    return step


def _incidence_input(value: object) -> IncidenceObservation:
    if not isinstance(value, IncidenceObservation):
        raise TypeError("GASL unit did not provide an incidence observation")
    return value


def _episode_observation(record: EpisodeRecord) -> IncidenceObservation:
    observations = tuple(
        _incidence_input(unit.controller_input) for unit in record.unit_records
    )
    if record.ended_by not in (END_EXHAUSTED, END_YIELD_STOP):
        reason = f":{record.end_reason}" if record.end_reason else ""
        return IncidenceObservation.excluded(
            f"child ended {record.ended_by}{reason}; its trace is retained but "
            "it does not enter the parent's controller"
        )
    if observations and all(
        observation.status == OBSERVATION_FAILED
        for observation in observations
    ):
        return IncidenceObservation.failed(
            "child made no numerical judgement: every unit failed"
        )
    combined = IncidenceObservation.combine(observations)
    schema = _incidence_state(record).report.channel_schema
    if schema.union_channel is None:
        return combined
    return IncidenceObservation(
        identities=combined.identities,
        channels={
            channel: combined.channels.get(channel, ())
            for channel in schema.base_channels
        },
    )

#: The query episode's scope key — code-minted, constant per invocation (each
#: invocation owns a fresh Context, so the constant never re-opens a path).
QUERY_EPISODE_KEY = "gasl-query"

#: A standalone walk's episode key. One standalone GRAPHWALK runs one walk
#: episode in its own Context, so the key is constant; nested walks under the
#: query episode use a per-operation key (``op-<unit index>``) instead,
#: because a scope path never reopens (design §2/F2).
WALK_EPISODE_KEY = "graphwalk"

#: Facet name prefix for the per-depth-step partition of a seed's encounters.
#: The suffix is the 1-based depth step, taken from the command's own `depth`
#: argument -- no graph key is involved.
DEPTH_FACET_PREFIX = "depth_"

#: The graph-reading command types — the operations that are units of the
#: query grain (design §4, accepted by gasl-design-steward ruling 1). Every
#: other command is string/state work riding inside the source's advance.
#: These are engine command types, not schema words.
GRAPH_READING_COMMANDS = (
    "FIND",
    "GRAPHWALK",
    "SUBGRAPH",
    "GRAPHCONNECT",
    "GRAPHPATTERN",
)

# Fate labels for operation tracks (design §5). Suffixes on `op_error` and
# `seed_expansion_error` are exception CLASS names captured via
# type(e).__name__ — never message text, which can carry provider or model
# prose (G4). A track whose error carries no captured class gets the
# suffix-free label.
FATE_OP_SUCCESS = "op_success"
FATE_OP_EMPTY = "op_empty"
FATE_OP_REPAIRED = "op_repaired"
FATE_OP_ERROR = "op_error"
FATE_COMPILE_BLOCKED = "compile_blocked"
#: An ON unit whose condition did not match: the operation never read the
#: graph, so it made no crediting judgement — a disclosed non-judgement,
#: distinct from a barren judged unit (implementation choice recorded in the
#: design log's implementation amendments).
FATE_OP_NOT_TRIGGERED = "op_not_triggered"

# Typed source-end reasons (charter rule 6): a spent planner budget is a cap,
# reported `bound_hit`; a planner raise is a dead stream, reported
# `source_failed`; a clean completion by the written counting rule is genuine
# exhaustion, recorded in the source summary.
SOURCE_END_PLANNER_BOUND = "planner_iteration_bound"
SOURCE_END_PLANNER_ERROR = "planner_error"
END_REASON_PLAN_COMPLETED = "plan_completed_clean"

# Payload ceiling on the per-unit records carried in the emitted yield,
# counted in CREDIT IDENTITIES rather than in units, because identities are
# what the payload is made of. NO MEASUREMENT JUSTIFIES 5,000; it is stated
# here so that it is one number in one place, and every episode that reaches
# it says so in the emitted `units.window` record rather than quietly
# shortening the evidence. It is above the largest emission this engine has
# recorded on a real graph (2,000 encounters over 40 seeds), so it does not
# bind there.
#
# Every unit's label survives the window unconditionally. What the window can
# cost is the omitted units' incidence membership, so exact Q1/Q2,
# rarefaction, and pairwise variance cannot be recomputed from the windowed
# unit list alone. The final estimator record remains emitted, and this loss
# of a second route is stated in the record instead of hidden
# (docs/ACQUISITION_LOOP.md §"What this does not change").
WALK_UNIT_CREDIT_WINDOW = 5000


@dataclass
class NodeBudget:
    """The walk's row budget, as a declared object with a limit and a count.

    It exists so that the extractor and the hook share no mutable state
    (docs/ACQUISITION_LOOP.md rule 7). The hook charges rows onto it as each
    seed's rows land; the seed source reads it before a pull and ends the
    stream by name when it is spent. `expand` never sees it.
    """

    limit: int
    spent: int = 0

    @property
    def exhausted(self) -> bool:
        return self.spent >= self.limit

    def charge(self, rows: int) -> None:
        self.spent += int(rows)


@dataclass(frozen=True)
class SeedExpansion:
    """What expanding one seed produced. The extractor's whole output.

    `rows` are the seed's final-depth rows (what the walk returns);
    `encounters_by_step` is the seed's node encounters partitioned by depth
    step, in step order. The partition is what lets a reader recompute what a
    depth-step (seed-grain) episode would have decided, from the export alone.
    """

    rows: Tuple[dict, ...]
    encounters_by_step: Tuple[Tuple[str, ...], ...]

    @property
    def encounters(self) -> Tuple[str, ...]:
        return tuple(
            identity for step in self.encounters_by_step for identity in step
        )


@dataclass(frozen=True)
class FailedSeedExpansion:
    """A seed whose adapter/expansion work raised — a typed non-judgement.

    Distinct from ``None`` (a seed that carries no id) on purpose: the two
    are different observables and each maps to its own disabled credit note.
    The catch that produces this is bounded to ONE seed's expansion work (G3);
    it applies on the nested, standalone, and pilot walk paths alike, because
    they share one ``expand``. Before this phase the same raise killed the
    whole GRAPHWALK through the handler's catch; under nesting it would have
    killed the whole query episode, so a per-seed instrument failure now
    becomes a disclosed disabled unit and the walk continues (design §7,
    reviewed explicitly as the one behavior change).
    """

    error_class: str


class _SeedStream:
    """The walk's unit source: seeds in order, with the node budget named.

    When the row budget is spent the stream reports
    `SourceEnd(END_BOUND_HIT, BOUND_KIND_WALK_NODE_BUDGET)` rather than
    returning silently, so the loop records the cut as the cap it is instead
    of recording exhaustion and having a wrapper correct the contract
    afterwards (docs/ACQUISITION_LOOP.md rule 6). A seed never expanded
    because the budget was spent is not a barren seed, and it never enters the
    yield history either way.
    """

    def __init__(self, nodes: List[dict], budget: NodeBudget) -> None:
        self._iterator = iter(nodes)
        self._budget = budget

    def next(self, view: Any) -> Any:
        if self._budget.exhausted:
            return SourceEnd(END_BOUND_HIT, BOUND_KIND_WALK_NODE_BUDGET)
        return next(self._iterator, None)


def _window_unit_records(unit_records: Tuple[UnitRecord, ...]) -> Dict[str, Any]:
    """Emit an episode's per-unit records, windowed with disclosure.

    The kernel emits each unit's full credit identities; a broad episode can
    make thousands of them, and this record travels to the planner. So the
    records are carried whole up to `WALK_UNIT_CREDIT_WINDOW` identities,
    taken from both ends of the episode (the first units and the last ones,
    alternating), and the omitted middle is named -- count, index range, and
    what is still recoverable without it. Nothing is sliced silently, and the
    units list is never replaced by a summary of itself.
    """

    total = len(unit_records)
    costs = [
        len(_incidence_input(record.controller_input).identities)
        for record in unit_records
    ]
    credits_total = sum(costs)

    if credits_total <= WALK_UNIT_CREDIT_WINDOW:
        kept = list(range(total))
    else:
        head: List[int] = []
        tail: List[int] = []
        remaining = WALK_UNIT_CREDIT_WINDOW
        low, high = 0, total - 1
        from_head = True
        while low <= high:
            index = low if from_head else high
            if costs[index] > remaining:
                break
            remaining -= costs[index]
            if from_head:
                head.append(index)
                low += 1
            else:
                tail.append(index)
                high -= 1
            from_head = not from_head
        kept = head + sorted(tail)

    kept_set = set(kept)
    omitted = [index for index in range(total) if index not in kept_set]
    return {
        "count": total,
        # Every unit's label, always, whether or not its identities were
        # carried: which units ran is never a casualty of a payload ceiling.
        "labels_first_seen_order": [record.unit_label for record in unit_records],
        "records": [unit_records[index].as_record() for index in kept],
        "window": {
            "credit_ceiling": WALK_UNIT_CREDIT_WINDOW,
            "credits_total": credits_total,
            "credits_emitted": sum(costs[index] for index in kept),
            "units_emitted": len(kept),
            "units_omitted": len(omitted),
            "omitted_unit_index_range": (
                [omitted[0], omitted[-1]] if omitted else None
            ),
            "still_recoverable": (
                "every unit's label and the final role-based incidence estimate"
            ),
            "not_recoverable_when_omitted": (
                "the omitted units' incidence membership, so Q1/Q2, exact "
                "rolling rarefaction, and pairwise variance cannot be "
                "independently recomputed from this window"
            ),
        },
    }


@dataclass
class WalkComposition:
    """One composed-but-not-run walk Episode plus its hook-written state.

    Built by :meth:`GraphWalkBinding.compose`; run either standalone by
    :meth:`GraphWalkBinding.walk` (own Context, kernel per-depth partition) or
    nested by the query episode's kernel (shared Context, single channel).
    ``rows`` and ``step_disclosure`` are filled by the walk's collect hook as
    the kernel runs; ``interpret`` reads them beside the emitted record.
    ``source_cap`` and ``edge_cap`` ride here so ``interpret`` can name the
    bound that fired (an implementation addition to the design's field list,
    recorded in the design log's implementation amendments).
    """

    episode: Episode
    rows: List[dict]
    budget: NodeBudget
    stats: Dict[str, int]
    seeds_total: int
    depth: int
    step_disclosure: List[dict]
    source_cap: Optional[int]
    edge_cap: int


@dataclass(frozen=True)
class WalkEpisodeOutput:
    """The completed walk data its parent operation needs."""

    rows: tuple[dict, ...]
    completeness: Mapping[str, Any]
    ended_by: str


class GraphWalkBinding:
    """Compose one GRAPHWALK over the generic Episode method."""

    def __init__(
        self,
        adapter: GraphAdapter,
        *,
        incident_edges: Callable[[Any], list[tuple[dict, str]]],
        canonicalize_relation_token: Callable[[str], str],
    ) -> None:
        self.adapter = adapter
        self._incident_edges = incident_edges
        self._canonicalize_relation_token = canonicalize_relation_token

    def compose(
        self,
        source_nodes: list[dict],
        follow_filters: list[str],
        depth: int,
        *,
        key: str,
        source_cap: int | None,
        max_nodes: int,
        edge_cap: int,
        nested: bool,
        grain: Optional[Grain] = None,
    ) -> WalkComposition:
        """Everything ``walk()`` does before ``Episode(...).run(...)``.

        The walk is a composition of one `Episode` (`WALK_GRAIN`) and writes no
        loop of its own: the kernel pulls a seed, expands it, credits its node
        encounters, records the numbers, and reads the verdict
        (docs/ACQUISITION_LOOP.md §"The template", rule 1).

        ``nested`` carries the crediter switch EXPLICITLY (G2): a nested walk
        runs under the query Context's single frozen channel schema, where
        ``ChannelSchema.project`` raises on membership groups, so its
        ``credit_seed`` supplies NO facets and the per-depth identities are
        preserved as hook-written ``step_disclosure`` instead; a standalone
        walk keeps the kernel per-depth partition exactly as before. The
        verdict-semantics consequence is disclosed in the binding summary:
        a nested walk's stop rule conjoins only the union channel, while a
        standalone walk conjoins every per-depth channel, so a nested walk
        can go flat, and stop, earlier than the same walk standalone; whether
        that difference would have changed any nested walk's stop is
        recomputable offline from ``step_disclosure`` (the extended 4E-b
        registration).
        """
        walked_data: list[dict] = []
        visited_hops = set()
        seeds_total = len(source_nodes)
        stats = {
            "nodes_with_truncated_fanout": 0,
            "edges_discarded_by_fanout_cap": 0,
        }
        budget = NodeBudget(limit=max_nodes)
        step_disclosure: list[dict] = []
        step_names = tuple(
            f"{DEPTH_FACET_PREFIX}{step + 1}" for step in range(depth)
        )
        channel_schema = (
            ChannelSchema.single()
            if nested
            else ChannelSchema.partition(step_names, overlap_allowed=True)
            if step_names
            else ChannelSchema.single()
        )
        walk_grain = grain if grain is not None else _walk_grain(channel_schema)

        def expand(node: dict) -> SeedExpansion | FailedSeedExpansion | None:
            """Expand one seed. The grain's extractor; it decides nothing.

            Returns the seed's final-depth rows plus the node encounters made
            on the way, partitioned by depth step (one entry per accepted,
            non-duplicate hop arrival -- re-arrivals at a node via distinct
            hops are genuine repeat encounters and feed Q1/Q2). ``None`` means
            the seed carries no id and could not be expanded at all -- a
            non-judgement, not a barren seed. A raise inside ONE seed's
            adapter/expansion work returns a typed ``FailedSeedExpansion``
            (G3) instead of propagating: the kernel has no per-unit catch, so
            the raise would otherwise kill the whole episode -- and, nested,
            the whole query.

            It reads NOTHING the hook writes (rule 7). The row-budget check
            that used to sit in these two loops read `walked_data`, which
            `collect` fills -- and could only ever read the value that was
            already there when this seed was pulled, because the hook does not
            run until this function returns. It was therefore the same test the
            seed source now makes before the pull, one call later, and it is
            gone rather than duplicated.
            """
            if not node.get("id"):
                return None
            try:
                encounters_by_step: list[tuple[str, ...]] = []
                current_nodes = [node]
                for step in range(depth):
                    step_encounters: list[str] = []
                    next_nodes = []
                    for current_node in current_nodes:
                        edges = self._incident_edges(current_node["id"])
                        if len(edges) > edge_cap:
                            # A per-node fan-out cut, counted in BOTH units on
                            # purpose. MEASURED over the three benchmark graphs
                            # recorded runs actually queried plus the largest
                            # question_runs graph: degree p50 is 1-2 and p90 is 4-6,
                            # but the max is 1,879 / 977 / 1,932 / 41, so
                            # `edge_cap=15` binds on under 2% of nodes while
                            # discarding 15.5% / 17.7% / 19.3% / 4.7% of all edge
                            # traversal. The distribution is heavy-tailed and every
                            # discarded edge is at a hub.
                            #
                            # That gap is why the node count alone is a misleading
                            # instrument: "2% of nodes truncated" reads as a rounding
                            # error and "a fifth of edges dropped" does not, and they
                            # are the same event. Reporting only the first would be
                            # a disclosure that technically fires and practically
                            # conceals -- the same shape as the bound it describes,
                            # inert on the typical case and biting hardest exactly
                            # where the graph carries the most structure.
                            stats["nodes_with_truncated_fanout"] += 1
                            stats["edges_discarded_by_fanout_cap"] += len(edges) - edge_cap
                        for edge, traversal_direction in edges[:edge_cap]:
                            edge_rel = (
                                edge.get("data", {}).get("relation_type")
                                or edge.get("data", {}).get("relationship_name")
                                or ""
                            )
                            canonical_edge_rel = self._canonicalize_relation_token(edge_rel)
                            if follow_filters and canonical_edge_rel not in follow_filters:
                                continue
                            neighbor_id = (
                                edge["target"]
                                if traversal_direction == "out"
                                else edge["source"]
                            )
                            neighbor_nodes = self.adapter.find_nodes({"id_filter": neighbor_id})
                            if not neighbor_nodes:
                                continue
                            neighbor_node = neighbor_nodes[0]
                            neighbor_id = neighbor_node["id"]
                            hop_key = (
                                current_node["id"],
                                edge["source"],
                                edge["target"],
                                step + 1,
                                canonical_edge_rel,
                                traversal_direction,
                            )
                            if hop_key in visited_hops:
                                continue
                            visited_hops.add(hop_key)
                            step_encounters.append(str(neighbor_id))
                            target_data = dict(neighbor_node.get("data", {}))
                            edge_data = dict(edge.get("data", {}))
                            row_data = {
                                **target_data,
                                "src_id": current_node["id"],
                                "tgt_id": neighbor_id,
                                "edge_src_id": edge["source"],
                                "edge_tgt_id": edge["target"],
                                "relation_type": edge_rel,
                                "traversal_direction": traversal_direction,
                                "path_depth": step + 1,
                                "edge_relation_type": edge_rel,
                                "edge_source_refs": edge_data.get("source_refs"),
                                "edge_source_chunks": edge_data.get("source_chunks"),
                                "edge_source_chunk": edge_data.get("source_chunk"),
                                "edge_description": edge_data.get("description"),
                            }
                            for provenance_key in (
                                "source_refs",
                                "source_chunks",
                                "source_chunk",
                            ):
                                edge_value = edge_data.get(provenance_key)
                                if edge_value:
                                    row_data[provenance_key] = edge_value
                            enriched_target = {
                                **neighbor_node,
                                "src_id": current_node["id"],
                                "tgt_id": neighbor_id,
                                "edge_data": edge_data,
                                "data": row_data,
                            }
                            next_nodes.append(enriched_target)
                    encounters_by_step.append(tuple(step_encounters))
                    current_nodes = next_nodes
                return SeedExpansion(
                    rows=tuple(current_nodes),
                    encounters_by_step=tuple(encounters_by_step),
                )
            except Exception as exc:
                # Bounded to this one seed's expansion work; the class name,
                # never the message, becomes the fate suffix (G3/G4).
                return FailedSeedExpansion(error_class=type(exc).__name__)

        if nested:

            def result_seed(node: dict, expansion: Any) -> IncidenceObservation:
                """The grain's crediter under the query's single channel.

                Supplies NO facets: the shared Context freezes one schema per
                grain name, the nested walk's schema is
                ``ChannelSchema.single()``, and ``project`` raises on
                membership groups for a single-channel schema (G2). The
                per-depth partition these facets used to carry is preserved as
                the collect hook's ``step_disclosure`` instead, so a reader
                can still rebuild what a depth-step episode would have seen
                without re-walking the graph.
                """
                if expansion is None:
                    return IncidenceObservation.failed(
                        "seed carries no id and could not be expanded"
                    )
                if isinstance(expansion, FailedSeedExpansion):
                    return IncidenceObservation.failed(
                        f"seed_expansion_error:{expansion.error_class}"
                    )
                return IncidenceObservation(identities=expansion.encounters)

        else:

            def result_seed(node: dict, expansion: Any) -> IncidenceObservation:
                """The grain's crediter: opaque node ids, grouped by depth step.

                The groups partition the seed's credits exactly, so the per-step
                curves the kernel accumulates from them are a partition of the
                walk's curve, and a reader can rebuild what a depth-step episode
                would have seen without re-walking the graph.
                """
                if expansion is None:
                    return IncidenceObservation.failed(
                        "seed carries no id and could not be expanded"
                    )
                if isinstance(expansion, FailedSeedExpansion):
                    return IncidenceObservation.failed(
                        f"seed_expansion_error:{expansion.error_class}"
                    )
                return IncidenceObservation(
                    identities=expansion.encounters,
                    channels=dict(zip(step_names, expansion.encounters_by_step)),
                )

        def collect(leaf: Any, contribution: Any, record: UnitView) -> None:
            """The grain's hook: the rows, and the budget those rows spend.

            Decoupled from crediting by construction -- the loop discards what
            this returns, and nothing it writes is read by `expand`. On the
            nested path it additionally appends each seed's per-depth
            encounters to ``step_disclosure`` (hook writes, extract never
            reads), preserving per-depth recomputability under the single
            channel schema (G2/F1).
            """
            expansion = contribution.output
            if not isinstance(expansion, SeedExpansion):
                return
            walked_data.extend(expansion.rows)
            budget.charge(len(expansion.rows))
            if nested:
                step_disclosure.append(
                    {
                        "seed": record.unit_label,
                        "encounters_by_step": [
                            list(step) for step in expansion.encounters_by_step
                        ],
                    }
                )

        episode = Episode(
            grain=walk_grain,
            key=key,
            source=leaves(
                _SeedStream(source_nodes, budget),
                expand,
                result_seed,
                label=lambda node: str(node.get("id") or "<no-id>"),
            ),
            on_unit=collect,
            # The declared per-walk seed budget is the episode's safety bound:
            # a cap, ending `bound_hit` with `unit_bound`, never a verdict.
            bound=source_cap,
        )
        return WalkComposition(
            episode=episode,
            rows=walked_data,
            budget=budget,
            stats=stats,
            seeds_total=seeds_total,
            depth=depth,
            step_disclosure=step_disclosure,
            source_cap=source_cap,
            edge_cap=edge_cap,
        )

    def interpret(
        self, comp: WalkComposition, record: EpisodeRecord
    ) -> tuple[list[dict], dict]:
        """Translate the end THE LOOP named into the caller's completeness.

        `source_cap` of None expands every seed. Whichever end stops the walk
        is named BY THE LOOP -- a yield verdict, the seed bound, the node
        budget the source reports -- and this method translates that named end
        into the caller's completeness disclosure. A caller that gets 500 rows
        needs to know whether that is the whole neighbourhood, all the room
        there was, or all the seeds that fit.
        """
        walked_data = comp.rows
        stats = comp.stats
        seeds_total = comp.seeds_total
        max_nodes = comp.budget.limit
        source_cap = comp.source_cap
        edge_cap = comp.edge_cap

        walk_yield = record.as_record()
        # Windowed with disclosure, never replaced by a summary of itself: the
        # per-unit credit identities are what lets a reader rebuild incidence
        # membership and estimator arithmetic rather than only read the result.
        walk_yield["units"] = _window_unit_records(record.unit_records)

        units_crediting_disabled = sum(
            1
            for unit in record.unit_records
            if _incidence_input(unit.controller_input).status == OBSERVATION_FAILED
        )
        seed_expansion_errors = sum(
            1
            for unit in record.unit_records
            if _incidence_input(unit.controller_input).note.startswith(
                "seed_expansion_error"
            )
        )
        seeds_expanded = record.units_consumed - units_crediting_disabled
        seeds_skipped = seeds_total - seeds_expanded
        detail = {
            "seeds_expanded": seeds_expanded,
            "seeds_total": seeds_total,
            # A seed that carried no id was counted and could not be judged.
            # Named here so "nothing was found" and "nothing was asked" stay
            # different observables at the caller, not only in the yield curve.
            # Expansion errors (a typed per-seed instrument failure, G3) are
            # split out so they never masquerade as absent ids.
            "seeds_without_id": units_crediting_disabled - seed_expansion_errors,
            "seed_expansion_errors": seed_expansion_errors,
            # The requested depth is the number of units a seed-grain episode
            # would have had, which is what decides whether that grain could
            # ever fire; carried so the decision is checkable from the export.
            "walk_depth": comp.depth,
            "nodes_with_truncated_fanout": stats["nodes_with_truncated_fanout"],
            "edges_discarded_by_fanout_cap": stats["edges_discarded_by_fanout_cap"],
            "walk_yield": walk_yield,
        }
        # Every branch below reads the end THE LOOP named. There is no
        # side-channel flag and no correction after the fact: what the record
        # says ended the walk is what the caller is told (rule 6).
        if (
            record.ended_by == END_BOUND_HIT
            and record.end_reason == BOUND_KIND_WALK_NODE_BUDGET
        ):
            return walked_data, completeness(
                complete=False,
                returned=len(walked_data),
                bound=max_nodes,
                bound_kind=BOUND_KIND_WALK_NODE_BUDGET,
                # The seeds left unpulled are countable, but how many ROWS they
                # would have produced is not, and the row count is what this
                # bound is denominated in -- so the residual stays unknown here
                # and `seeds_expanded`/`seeds_total` carry the seed-grain fact.
                residual_known=False,
                residual=None,
                **detail,
            )
        if record.ended_by == END_YIELD_STOP:
            return walked_data, completeness(
                complete=False,
                returned=len(walked_data),
                bound=None,
                bound_kind=BOUND_KIND_WALK_YIELD_STOP,
                # A decision, not a cap: the posterior said further seeds stop
                # producing new nodes. The unexpanded seeds are known and
                # counted; the rows they would have produced are not claimed.
                residual_known=True,
                residual=seeds_skipped,
                **detail,
            )
        if (
            record.ended_by == END_BOUND_HIT
            and record.end_reason == END_REASON_UNIT_BOUND
        ):
            return walked_data, completeness(
                complete=False,
                returned=len(walked_data),
                bound=source_cap,
                bound_kind=BOUND_KIND_WALK_SEED_BUDGET,
                # Unlike most bounds this residual IS known at the seed grain:
                # the seeds were in hand and simply not expanded. How many ROWS
                # they would have produced is not known, and is not claimed.
                residual_known=True,
                residual=seeds_skipped,
                **detail,
            )
        if record.ended_by != END_EXHAUSTED:
            # Only `source_failed` reaches here, and nothing in this walk
            # produces it today. It is mapped rather than left to fall through,
            # because falling through would report a walk whose stream died as
            # a complete answer -- the exact silent failure the named ends
            # exist to remove.
            return walked_data, completeness(
                complete=False,
                returned=len(walked_data),
                bound=None,
                bound_kind=BOUND_KIND_NONE,
                residual_known=True,
                residual=seeds_skipped,
                **detail,
            )
        if stats["nodes_with_truncated_fanout"]:
            return walked_data, completeness(
                complete=False,
                returned=len(walked_data),
                bound=edge_cap,
                bound_kind=BOUND_KIND_WALK_NODE_BUDGET,
                residual_known=False,
                residual=None,
                **detail,
            )
        if units_crediting_disabled:
            # The stream ran out with every seed offered, and some of those
            # seeds could not be expanded at all. No bound fired, so there is no
            # bound kind to name -- but the walk is not complete either, and
            # reporting it as complete with a zero residual (which is what
            # happened before the ends were read here) would claim coverage the
            # walk never had.
            return walked_data, completeness(
                complete=False,
                returned=len(walked_data),
                bound=None,
                bound_kind=BOUND_KIND_NONE,
                residual_known=True,
                residual=seeds_skipped,
                **detail,
            )
        return walked_data, dict(complete_result(len(walked_data)), **detail)

    def parent_update(
        self,
        comp: WalkComposition,
        record: EpisodeRecord,
    ) -> EpisodeUpdate:
        """Compress a completed walk for its parent query Episode."""

        rows, walk_completeness = self.interpret(comp, record)
        state = _incidence_state(record)
        observation = _episode_observation(record)
        return EpisodeUpdate(
            record_id=record.episode_id,
            controller_input=observation,
            prompt_context={
                "episode_id": record.episode_id,
                "units_processed": record.units_consumed,
                "ended_by": record.ended_by,
                "distinct_nodes": len(observation.identities),
                "estimate": state.report.primary.as_record(),
                "verdict": state.verdict.as_record(),
            },
            output=WalkEpisodeOutput(
                rows=tuple(rows),
                completeness=dict(walk_completeness),
                ended_by=record.ended_by,
            ),
        )

    def walk(
        self,
        source_nodes: list[dict],
        follow_filters: list[str],
        depth: int,
        *,
        source_cap: int | None,
        max_nodes: int,
        edge_cap: int,
    ) -> tuple[list[dict], dict]:
        """Walk standalone, and report what the walk did not reach.

        The standalone/pilot path: its own throwaway Context, the kernel
        per-depth partition intact, the constant episode key. Nested walks
        under the query episode go through ``compose``/``interpret`` with a
        per-operation key instead; this method's signature and behavior are
        unchanged for every non-Episode caller.
        """
        comp = self.compose(
            source_nodes,
            follow_filters,
            depth,
            key=WALK_EPISODE_KEY,
            source_cap=source_cap,
            max_nodes=max_nodes,
            edge_cap=edge_cap,
            nested=False,
        )
        record = comp.episode.run(
            Context(order=(comp.episode.grain,))
        )
        return self.interpret(comp, record)


# --------------------------------------------------------------------------
# the operation crediter — deterministic, total, engine shapes only
# --------------------------------------------------------------------------


def _take_node_id(value: Any, credits: Dict[str, None]) -> bool:
    """Add one node identity to ``credits`` if ``value`` carries one.

    A node reference in an engine result is either an opaque id (string/int)
    or a node dict carrying the canonical ``id``. Anything else is not a node
    reference and the caller counts it as unmappable rather than raising —
    the crediter must be total (G10): a raise here propagates through the
    query ``Episode.run`` and kills the whole query.
    """
    if isinstance(value, (str, int)) and not isinstance(value, bool):
        credits[str(value)] = None
        return True
    if isinstance(value, dict):
        identity = value.get("id")
        if isinstance(identity, (str, int)) and not isinstance(identity, bool):
            credits[str(identity)] = None
            return True
    return False


def _row_node_ids(row: Any, credits: Dict[str, None]) -> bool:
    """Collect the node ids one engine-built result row carries.

    Only canonical literals and engine-owned result shapes are read (design
    §4, G9): ``id`` on node and walk rows; ``source``/``target`` endpoints
    (opaque ids on edge and path rows, full node dicts on GRAPHCONNECT rows —
    read ``["id"]`` off them); the members of an engine-emitted ``path``
    list; the path rows under a connection row's ``paths``; the node dicts
    under a GRAPHPATTERN match's ``nodes``; ``src_id``/``tgt_id`` on rows
    that carry endpoints under those canonical names. Returns whether
    anything was collected.
    """
    if not isinstance(row, dict):
        return False
    matched = False
    nodes = row.get("nodes")
    if isinstance(nodes, list):
        for node in nodes:
            matched = _take_node_id(node, credits) or matched
    if "source" in row or "target" in row:
        for endpoint in ("source", "target"):
            if endpoint in row:
                matched = _take_node_id(row[endpoint], credits) or matched
        path_members = row.get("path")
        if isinstance(path_members, list):
            for member in path_members:
                matched = _take_node_id(member, credits) or matched
        nested_paths = row.get("paths")
        if isinstance(nested_paths, list):
            for nested in nested_paths:
                if isinstance(nested, dict):
                    matched = _row_node_ids(nested, credits) or matched
    if _take_node_id(row, credits):
        matched = True
    else:
        for endpoint_key in ("src_id", "tgt_id"):
            value = row.get(endpoint_key)
            if isinstance(value, (str, int)) and not isinstance(value, bool):
                credits[str(value)] = None
                matched = True
    return matched


def operation_credits(data: Any) -> tuple[Tuple[str, ...], int]:
    """Map one operation's final result payload to distinct node identities.

    Deterministic, no model, never raises (G10). Rows whose shape resolves to
    no node id are counted and returned as ``unmappable`` for the credit
    note's disclosure — never silently dropped.
    """
    credits: Dict[str, None] = {}
    unmappable = 0
    if data is None:
        return (), 0
    if isinstance(data, dict):
        nodes = data.get("nodes")
        if isinstance(nodes, list):
            # SUBGRAPH's dict payload: node ids live under data["nodes"] (G9).
            for node in nodes:
                if not _take_node_id(node, credits):
                    unmappable += 1
            return tuple(credits), unmappable
        if not _row_node_ids(data, credits) and data:
            unmappable += 1
        return tuple(credits), unmappable
    if isinstance(data, list):
        for row in data:
            if not _row_node_ids(row, credits):
                unmappable += 1
        return tuple(credits), unmappable
    return (), 1


def result_for_track_outcome(outcome: "TrackOutcome") -> IncidenceObservation:
    """The operation crediter: fate label plus credits for one Leaf track.

    Every fate here is a typed label for an end the existing code already
    produces (design §5). ``op_error`` suffixes come from the captured
    exception class name only (G4) — where no class was captured the label is
    suffix-free, never derived from message text.
    """
    result = outcome.final_result
    if result is None:
        # The track appended no result at all — nothing was judged.
        return IncidenceObservation.failed(FATE_OP_ERROR)
    provenance_ids = [
        provenance.source_id for provenance in (result.provenance or [])
    ]
    if result.status == "error":
        if "step_compiler" in provenance_ids:
            return IncidenceObservation.failed(FATE_COMPILE_BLOCKED)
        error_class = ""
        for provenance in result.provenance or []:
            if provenance.source_id == "command_execution":
                error_class = str(provenance.extraction.get("error_type") or "")
                break
        if error_class:
            return IncidenceObservation.failed(f"{FATE_OP_ERROR}:{error_class}")
        return IncidenceObservation.failed(FATE_OP_ERROR)
    if (
        "gasl-on" in provenance_ids
        and isinstance(result.data, dict)
        and result.data.get("triggered") is False
    ):
        return IncidenceObservation.failed(FATE_OP_NOT_TRIGGERED)
    credits, unmappable = operation_credits(result.data)
    repaired = "command_repair" in provenance_ids
    if repaired and result.status == "success":
        fate = FATE_OP_REPAIRED
    elif credits:
        fate = FATE_OP_SUCCESS
    else:
        fate = FATE_OP_EMPTY
    note = fate
    if repaired and fate != FATE_OP_REPAIRED:
        note += " repaired"
    if unmappable:
        note += f" unmappable_rows={unmappable}"
    return IncidenceObservation(identities=credits, note=note)


# --------------------------------------------------------------------------
# operation Leaf units
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class TrackOutcome:
    """What one operation track produced — the Leaf extractor's whole output."""

    results: Tuple[Any, ...]
    final_result: Any
    previous_result: Any
    break_plan: bool


@dataclass(frozen=True)
class OperationTrack:
    """One graph-reading operation frozen at yield time.

    Everything the track needs is captured here when the source yields the
    unit — including the previous result snapshot — so the Leaf's ``extract``
    reads nothing any hook writes (rule 7). The hook writes the outcome back
    into the source afterwards, sequentially by the kernel's fixed step order
    (the design §7 registry pattern).
    """

    services: "QueryBindingServices"
    plan: Any
    plan_json: Dict[str, Any]
    commands: Tuple[Any, ...]
    index: int
    command: Any
    previous_result: Any
    precompiled: Optional[tuple]
    step_id: str


def _run_operation_track(track: OperationTrack) -> TrackOutcome:
    """The Leaf extractor: run one command's full track via the injected
    callable — step-compile → execute → command-repair, history and trace
    included, exactly the executor's existing per-command body."""
    results: List[Any] = []
    previous_result, break_plan = track.services.run_track(
        plan=track.plan,
        plan_json=track.plan_json,
        commands=list(track.commands),
        index=track.index,
        command=track.command,
        previous_result=track.previous_result,
        results=results,
        precompiled=track.precompiled,
    )
    final_result = results[-1] if results else None
    return TrackOutcome(
        results=tuple(results),
        final_result=final_result,
        previous_result=previous_result,
        break_plan=break_plan,
    )


def _result_operation_track(
    track: OperationTrack,
    outcome: Any,
) -> IncidenceObservation:
    if not isinstance(outcome, TrackOutcome):
        # Totality guard (G10): a mis-shaped extraction is a disclosed
        # non-judgement, never a raise inside the kernel's credit step.
        return IncidenceObservation.failed(FATE_OP_ERROR)
    return result_for_track_outcome(outcome)


# --------------------------------------------------------------------------
# the injected services — the executor's existing machinery, as callables
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class QueryBindingServices:
    """The existing executor machinery the composition is wired from.

    Every callable here is the executor's own code (or a closure over it)
    injected at composition time; this module adds none of its own. Model
    string work lives inside ``acquire_plan`` (the planner), ``run_track``
    (extraction/repair inside a command), ``compile_command`` (the step
    compiler), and ``repair_and_adapt`` (plan repair, strategy adaptation) —
    and no output of any of them becomes an identity, an incidence input, or
    an Episode continue/stop input. The loop's only decision edges are the
    kernel verdict, the written completion counting rule inside
    ``summarize_outcomes``, and the typed planner-iteration budget.
    """

    #: (iteration, pending_plan_json) -> plan_json. Raises
    #: ``json.JSONDecodeError`` when the planner's output does not parse
    #: (counted, budget charged, planner re-asked); any other raise is a dead
    #: stream typed ``SourceEnd(END_SOURCE_FAILED, "planner_error")``.
    acquire_plan: Callable[[int, Optional[Dict[str, Any]]], Dict[str, Any]]
    #: plan_json -> (plan object, parsed command list); sets query/config in
    #: state exactly as ``execute_plan`` does.
    begin_plan: Callable[[Dict[str, Any]], tuple]
    #: The extracted per-command track body (executor ``_run_command_track``).
    run_track: Callable[..., tuple]
    #: (command, step_id, previous_command, next_command) ->
    #: (compiled_commands, compile_failure) — the executor's existing step
    #: compile, used by the source only to decide walk-vs-leaf for GRAPHWALK;
    #: its outcome is handed to ``run_track`` so nothing compiles twice.
    compile_command: Callable[..., tuple]
    #: (results, iteration) -> failure summary. The written completion
    #: counting rule: ``needs_repair`` is a count of unsuperseded errors plus
    #: blocking empties; the model never sees it.
    summarize_outcomes: Callable[[List[Any], int], Dict[str, Any]]
    #: (previous_plan_json, iteration, failure_summary) -> repaired plan_json
    #: or None. Plan repair, planner constraints, and strategy adaptation —
    #: string work between plans, exactly as today.
    repair_and_adapt: Callable[[Dict[str, Any], int, Dict[str, Any]], Optional[Dict[str, Any]]]
    #: command text -> command type ("" when unparsable); used to classify an
    #: ON command's nested action.
    parse_command_type: Callable[[str], str]
    #: GRAPHWALK pre-walk half (handler-provided): variable resolution, the
    #: ``last_nodes_result`` fallback, filter normalization, the pilot walk +
    #: refinement disclosure, and the declared caps — accepted inputs
    #: preserved verbatim (G7).
    prepare_graphwalk: Callable[[Any], Dict[str, Any]]
    #: GRAPHWALK post-walk half (handler-provided): contracts, storage,
    #: ExecutionResult — run in the query hook, post-verdict.
    finish_graphwalk: Callable[[Any, Dict[str, Any], list, dict], Any]
    #: (step_id, command, result) -> history entry + produced artifact for a
    #: nested walk's result, mirroring the track body's publication.
    publish_result: Callable[[str, Any, Any], None]
    #: current state snapshot, for the per-plan legacy records.
    get_state: Callable[[], Dict[str, Any]]
    #: the walk compose/interpret owner.
    walk_binding: GraphWalkBinding
    #: the graph adapter — read with getattr for the §8 identity disclosure.
    adapter: Any
    #: the trace logger; the summary writer emits through it.
    trace: Any


# --------------------------------------------------------------------------
# the source: the two-phase planner repackaged (the switch edge)
# --------------------------------------------------------------------------


class PlannerOperationSource:
    """``UnitSource`` over the two-phase planner (design §3).

    It owns all model string work on this surface and emits no number a
    branch consumes. Its only decision edges are written mechanical rules:

    - plan completed clean (``needs_repair == 0`` by the existing counting
      rule) → ``None`` — genuine exhaustion, reason recorded;
    - planner-iteration budget spent →
      ``SourceEnd(END_BOUND_HIT, "planner_iteration_bound")`` — the disclosed
      safety bound, never convergence;
    - planner raise → ``SourceEnd(END_SOURCE_FAILED, "planner_error")`` — a
      typing of an end that already happened;
    - a plan whose JSON does not parse mints NO unit: counted in
      ``plans_unparsed``, planner re-asked, budget still charged.

    Epoch mutation is not bound in Phase G: no ``next_epoch``, so a root
    saturation verdict ends the episode ``incomplete`` — the typed result,
    disclosed, never masquerading as convergence.
    """

    def __init__(
        self,
        *,
        services: QueryBindingServices,
        query: str,
        max_iterations: int,
        walk_grain: Grain,
    ) -> None:
        self._services = services
        self._query = query
        self._max_iterations = int(max_iterations)
        self._walk_grain = walk_grain

        # current-plan state
        self._plan: Any = None
        self._plan_json: Optional[Dict[str, Any]] = None
        self._commands: List[Any] = []
        self._command_index = 0
        self._previous_result: Any = None
        self._plan_results: List[Any] = []
        self._plan_broke = False
        # True once the completion rule has recorded the current plan, so a
        # later episode end never re-reports a completed plan as interrupted
        # work or counts its commands as unexecuted.
        self._plan_closed = False
        self._pending_plan_json: Optional[Dict[str, Any]] = None

        # walk-unit registry: written by the source at yield, read by the
        # query hook after the child ran — sequential by the kernel's fixed
        # step order (design §7).
        self._walk_registry: Dict[str, Dict[str, Any]] = {}
        self._step_disclosure: List[Dict[str, Any]] = []
        # compile outcomes carried from the walk-vs-leaf decision into the
        # Leaf track, so nothing compiles twice. Keyed by the plan-unique
        # unit key (the same discipline as `_walk_registry`), NEVER by the
        # plan-local command index: an index-keyed entry surviving a plan
        # reset would hand a later plan's leaf at the same index the previous
        # plan's compiled command — a silent cross-plan substitution (the
        # cycle-1 blocking defect). An entry lives for exactly one
        # `_advance_plan` step: popped by the fallback Leaf, or popped on the
        # compose-success path where no later reader exists.
        self._precompiled_by_unit: Dict[str, tuple] = {}

        # counters — the source summary's numbers (§3/§6)
        self.plans_charged = 0
        self.plans_generated = 0
        self.plans_from_repair = 0
        self.plans_unparsed = 0
        self.plans_repaired = 0
        self.operations_yielded = 0
        self.state_tracks_run = 0
        self.commands_discarded_by_plan_break = 0
        self.graphwalks_nested = 0
        self.graphwalks_leaf_fallback = 0
        self.on_graph_read_units = 0
        self.fate_tally: Dict[str, int] = {}
        self.plan_records: List[Dict[str, Any]] = []
        self.end_reason: str = ""
        self.planner_error_class: str = ""

    # ---------------------------------------------------------------- #
    # UnitSource
    # ---------------------------------------------------------------- #
    def next(self, view: Any) -> Any:
        while True:
            if self._plan is not None:
                unit = self._advance_plan()
                if unit is not None:
                    return unit
                # Plan finished (exhausted, or broke by its own config):
                # consult the written completion counting rule.
                failure_summary = self._services.summarize_outcomes(
                    list(self._plan_results), self.plans_charged
                )
                self._close_plan_record(failure_summary)
                if not failure_summary["needs_repair"]:
                    # Genuine exhaustion: the proposer's written numerical
                    # completion rule says there is nothing left to propose.
                    self.end_reason = END_REASON_PLAN_COMPLETED
                    return None
                if self.plans_charged >= self._max_iterations:
                    # A cap answers "how much am I allowed", never "is this
                    # still producing" — reported bound_hit, and (matching
                    # the replaced loop) no repair is attempted for a plan
                    # that could never run.
                    return SourceEnd(END_BOUND_HIT, SOURCE_END_PLANNER_BOUND)
                repaired = self._services.repair_and_adapt(
                    self._plan_json, self.plans_charged, failure_summary
                )
                if repaired is not None:
                    self.plans_repaired += 1
                    self._pending_plan_json = repaired
                self._reset_plan()
                continue

            # No current plan: budget-check BEFORE any generation (§3 item 4).
            if self.plans_charged >= self._max_iterations:
                return SourceEnd(END_BOUND_HIT, SOURCE_END_PLANNER_BOUND)
            self.plans_charged += 1
            pending, self._pending_plan_json = self._pending_plan_json, None
            if pending is not None:
                self.plans_from_repair += 1
            else:
                self.plans_generated += 1
            try:
                plan_json = self._services.acquire_plan(self.plans_charged, pending)
            except json.JSONDecodeError:
                # No unit minted: counted, budget charged, planner re-asked.
                self.plans_unparsed += 1
                continue
            except Exception as exc:  # a dead stream, named — never exhaustion
                self.planner_error_class = type(exc).__name__
                return SourceEnd(END_SOURCE_FAILED, SOURCE_END_PLANNER_ERROR)
            try:
                plan, commands = self._services.begin_plan(plan_json)
            except Exception:
                # Parsed JSON whose commands do not parse into a plan: the
                # same no-unit outcome as an undecodable response.
                self.plans_unparsed += 1
                continue
            self._plan = plan
            self._plan_json = plan_json
            self._commands = list(commands)
            self._command_index = 0
            self._previous_result = None
            self._plan_results = []
            self._plan_broke = False
            self._plan_closed = False

    # ---------------------------------------------------------------- #
    # plan advance — state transforms ride here; graph reads become units
    # ---------------------------------------------------------------- #
    def _advance_plan(self) -> Any:
        while self._command_index < len(self._commands):
            if self._plan_broke:
                # The plan's own config (a model-proposed advance rule inside
                # the proposal, scoped honestly — design §14 debt) stopped the
                # plan: the queued remainder is counted, never silent.
                discarded = len(self._commands) - self._command_index
                self.commands_discarded_by_plan_break += discarded
                self._command_index = len(self._commands)
                break
            index = self._command_index
            command = self._commands[index]
            kind = self._operation_kind(command)
            self._command_index += 1
            if kind == "state":
                # String/state work riding between units, yielding nothing.
                self.state_tracks_run += 1
                results: List[Any] = []
                previous_result, break_plan = self._services.run_track(
                    plan=self._plan,
                    plan_json=self._plan_json,
                    commands=self._commands,
                    index=index,
                    command=command,
                    previous_result=self._previous_result,
                    results=results,
                    precompiled=None,
                )
                self._previous_result = previous_result
                self._plan_results.extend(results)
                if break_plan:
                    self._plan_broke = True
                continue
            unit_key = f"op-{self.operations_yielded}"
            self.operations_yielded += 1
            if kind == "walk":
                unit = self._compose_walk_unit(command, index, unit_key)
                if unit is not None:
                    return unit
                self.graphwalks_leaf_fallback += 1
            if command.command_type == "ON":
                self.on_graph_read_units += 1
            return self._make_operation_leaf(command, index, unit_key)
        return None

    def _operation_kind(self, command: Any) -> str:
        if command.command_type == "GRAPHWALK":
            return "walk"
        if command.command_type in GRAPH_READING_COMMANDS:
            return "read"
        if command.command_type == "ON":
            action_type = self._services.parse_command_type(
                str((command.args or {}).get("action", ""))
            )
            if action_type in GRAPH_READING_COMMANDS:
                return "read"
        return "state"

    def _step_id(self, index: int) -> str:
        return f"{self._plan.plan_id}-step-{index + 1}"

    def _compose_walk_unit(self, command: Any, index: int, unit_key: str) -> Any:
        """Compile, then compose the walk child — or signal Leaf fallback.

        Returns the composed walk Episode, or ``None`` when this GRAPHWALK
        must run through the ordinary Leaf track instead: the compiler
        blocked or rewrote it into something other than a single GRAPHWALK,
        or the handler's pre-walk half could not resolve its inputs (the
        repair envelope then still applies, exactly as before). The compile
        outcome is carried into the Leaf so nothing compiles twice.
        """
        step_id = self._step_id(index)
        previous_command = self._commands[index - 1] if index > 0 else None
        next_command = (
            self._commands[index + 1] if index + 1 < len(self._commands) else None
        )
        precompiled = self._services.compile_command(
            command, step_id, previous_command, next_command
        )
        self._precompiled_by_unit[unit_key] = precompiled
        compiled_commands, compile_failure = precompiled
        if compile_failure is not None:
            return None
        if len(compiled_commands) != 1 or compiled_commands[0].command_type != "GRAPHWALK":
            return None
        compiled_command = compiled_commands[0]
        prep = self._services.prepare_graphwalk(compiled_command)
        if prep.get("status") != "ok":
            return None
        comp = self._services.walk_binding.compose(
            prep["source_nodes"],
            prep["follow_filters"],
            prep["depth"],
            key=unit_key,
            source_cap=prep["source_cap"],
            max_nodes=prep["max_nodes"],
            edge_cap=prep["edge_cap"],
            nested=True,
            grain=self._walk_grain,
        )
        comp.episode = replace(
            comp.episode,
            to_parent=lambda record: self._services.walk_binding.parent_update(
                comp, record
            ),
        )
        self.graphwalks_nested += 1
        self._walk_registry[unit_key] = {
            "command": command,
            "compiled_command": compiled_command,
            "prep": prep,
            "comp": comp,
            "step_id": step_id,
        }
        # Consumed: only the same-step fallback Leaf ever reads the entry,
        # and the walk path never does — popping here keeps the registry
        # empty between operations instead of retaining dead state.
        self._precompiled_by_unit.pop(unit_key, None)
        return comp.episode

    def _make_operation_leaf(self, command: Any, index: int, unit_key: str) -> Leaf:
        precompiled = self._precompiled_by_unit.pop(unit_key, None)
        track = OperationTrack(
            services=self._services,
            plan=self._plan,
            plan_json=self._plan_json,
            commands=tuple(self._commands),
            index=index,
            command=command,
            previous_result=self._previous_result,
            precompiled=precompiled,
            step_id=self._step_id(index),
        )
        return Leaf(
            unit=track,
            extract=_run_operation_track,
            result=_result_operation_track,
            label=unit_key,
        )

    # ---------------------------------------------------------------- #
    # the query grain's hook — post-verdict publication and writeback
    # ---------------------------------------------------------------- #
    def on_unit(self, item: Any, contribution: Contribution, record: UnitView) -> None:
        if contribution.episode_update is not None:
            entry = self._walk_registry.pop(item.key, None)
            if entry is None:
                return
            comp = entry["comp"]
            output = contribution.output
            if not isinstance(output, WalkEpisodeOutput):
                raise TypeError("nested walk returned no WalkEpisodeOutput")
            # This nested path applies no plan-break gate (the track body's
            # stop_on_error/continue_on_empty checks) because
            # `finish_graphwalk`'s only result constructor is
            # status="success", so no breaking status can arise here; a
            # future change to that status contract must revisit this hook
            # (code-review cycle 1, finding 4).
            result = self._services.finish_graphwalk(
                entry["compiled_command"],
                entry["prep"],
                list(output.rows),
                dict(output.completeness),
            )
            self._services.publish_result(
                entry["step_id"], entry["compiled_command"], result
            )
            self._plan_results.append(result)
            self._previous_result = result
            self._step_disclosure.append(
                {
                    "operation": item.key,
                    "walk_depth": comp.depth,
                    "per_seed_encounters_by_step": list(comp.step_disclosure),
                }
            )
            self._tally(f"walk:{output.ended_by}")
            return
        outcome = contribution.output
        if isinstance(outcome, TrackOutcome):
            self._plan_results.extend(outcome.results)
            self._previous_result = outcome.previous_result
            if outcome.break_plan:
                self._plan_broke = True
        note = _incidence_input(contribution.controller_input).note or FATE_OP_ERROR
        self._tally(note.split()[0])

    # ---------------------------------------------------------------- #
    # bookkeeping
    # ---------------------------------------------------------------- #
    def _tally(self, fate: str) -> None:
        self.fate_tally[fate] = self.fate_tally.get(fate, 0) + 1

    def _close_plan_record(self, failure_summary: Dict[str, Any]) -> None:
        self.plan_records.append(
            {
                "plan_id": getattr(self._plan, "plan_id", ""),
                "status": "completed",
                "needs_repair": bool(failure_summary.get("needs_repair")),
                "results": list(self._plan_results),
                "final_state": self._services.get_state(),
            }
        )
        self._plan_closed = True

    def _reset_plan(self) -> None:
        self._plan = None
        self._plan_json = None
        self._commands = []
        self._command_index = 0
        self._previous_result = None
        self._plan_results = []
        self._plan_broke = False
        self._plan_closed = False
        # Defensive (belt and braces beside the unit-key discipline above):
        # no compile outcome may ever cross a plan boundary.
        self._precompiled_by_unit.clear()

    def operations_unexecuted_at_stop(self) -> int:
        """The queued commands a mid-plan episode end left unexecuted.

        Emitted for EVERY end (zero when nothing was queued): a yield stop, a
        bound, a source failure, and an incomplete all discard the remainder
        the same way — the GASL analog of "buffered results left after a
        verdict get no page-level LLM work".
        """
        if self._plan is None or self._plan_closed:
            return 0
        return max(0, len(self._commands) - self._command_index)

    def interrupted_plan_record(self) -> Optional[Dict[str, Any]]:
        """The open plan's partial results when the episode ended mid-plan."""
        if self._plan is None or self._plan_closed:
            return None
        return {
            "plan_id": getattr(self._plan, "plan_id", ""),
            "status": "interrupted",
            "results": list(self._plan_results),
            "final_state": self._services.get_state(),
        }

    def summary(self) -> Dict[str, Any]:
        return {
            "plans_charged": self.plans_charged,
            "plans_generated": self.plans_generated,
            "plans_from_repair": self.plans_from_repair,
            "plans_unparsed": self.plans_unparsed,
            "plans_repaired": self.plans_repaired,
            "operations_yielded": self.operations_yielded,
            "state_tracks_run": self.state_tracks_run,
            "commands_discarded_by_plan_break": self.commands_discarded_by_plan_break,
            "graphwalks_nested": self.graphwalks_nested,
            "graphwalks_leaf_fallback": self.graphwalks_leaf_fallback,
            "on_graph_read_units": self.on_graph_read_units,
            "end_reason": self.end_reason,
            "planner_error_class": self.planner_error_class,
            "planner_iteration_budget": self._max_iterations,
        }


@dataclass(frozen=True)
class QueryComposition:
    """One composed query episode, ready for exactly one ``Episode.run``."""

    episode: Episode
    context: Context
    source: PlannerOperationSource


class GaslQueryBinding:
    """Build and summarize the GASL query composition (design §§1-9)."""

    def __init__(self, services: QueryBindingServices) -> None:
        self._services = services

    def compose(self, *, query: str, max_iterations: int) -> QueryComposition:
        query_grain = _query_grain()
        walk_grain = _walk_grain(ChannelSchema.single())
        source = PlannerOperationSource(
            services=self._services,
            query=query,
            max_iterations=max_iterations,
            walk_grain=walk_grain,
        )
        episode = Episode(
            grain=query_grain,
            key=QUERY_EPISODE_KEY,
            source=source,
            on_unit=source.on_unit,
            # No Episode.bound: the planner-iteration budget is not a unit
            # count, so it is the SOURCE's typed cut (design §5).
            bound=None,
        )
        context = Context(order=(query_grain, walk_grain))
        return QueryComposition(episode=episode, context=context, source=source)

    def summarize(
        self, composition: QueryComposition, record: EpisodeRecord
    ) -> Dict[str, Any]:
        """The binding summary wrapped around the kernel's emitted record.

        Adds the source counters, the fate tally, the graph disclosure (§8),
        the un-run remainder, the verdict-semantics disclosure (G2), and the
        per-walk step disclosure. Unit records nest walk records via
        ``UnitRecord.child`` — one representation of the tree, windowed with
        disclosure where the payload ceiling bites, never sliced silently.
        """
        source = composition.source
        episode_record = record.as_record()
        episode_record["units"] = _window_unit_records(record.unit_records)
        adapter = self._services.adapter
        graph_path = getattr(adapter, "graph_source_path", None)
        graph_digest = getattr(adapter, "graph_source_sha256", None)
        summary = {
            "binding": QUERY_EPISODE_KEY,
            "episode": episode_record,
            "source": source.summary(),
            "fates": dict(source.fate_tally),
            # §8: absence is recorded explicitly — never silently missing.
            "graph": {
                "graph_source_path": str(graph_path) if graph_path else "unavailable",
                "graph_digest": str(graph_digest) if graph_digest else "unavailable",
            },
            "operations_unexecuted_at_stop": source.operations_unexecuted_at_stop(),
            # Cost has one owner (charter): gasl/ has no cost metering, and no
            # second meter is built — disclosed, not omitted.
            "cost_metering": "none_disclosed",
            # G2, second half: the frozen-kernel consequence of nesting,
            # stated where the records are read.
            "verdict_semantics": (
                "nested walks' stop rule conjoins only the union channel "
                "(ChannelSchema.single()); standalone walks conjoin per-depth "
                "channels, so a nested walk can go flat, and stop, earlier "
                "than the same walk standalone. Whether that difference would "
                "have changed any nested walk's stop is recomputable offline "
                "from walk_step_disclosure (the extended 4E-b registration)."
            ),
            # The pilot walk is a disclosed refinement instrument, not a unit:
            # it runs the standalone path in its own Context and its record
            # enters no incidence anywhere.
            "pilot_walks": "standalone refinement instruments; never units, never in incidence",
            "walk_step_disclosure": list(source._step_disclosure),
        }
        self._services.trace.log("query_episode_summary", summary)
        return summary
