"""Bind GASL graph walking to the generic acquisition Episode.

The surface vocabulary and nesting live here, at the binding boundary:

    query Episode                                      [UNBOUND]
        └── walk Episode                                  [BOUND HERE]
              unit: one seed expansion
              credit: opaque node encounters
              └── seed Episode (unit: one depth step)      [UNBOUND]

Only the walk grain is bound today. Per-depth encounter facets preserve the
seed-grain observations needed to evaluate that later binding without claiming
that a seed Episode currently runs. The command handler supplies the graph
adapter and remains responsible for command parsing and result storage.
"""

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Tuple

from rarefaction import (
    END_BOUND_HIT,
    END_EXHAUSTED,
    END_REASON_UNIT_BOUND,
    END_YIELD_STOP,
    ChannelSchema,
    ControllerConfig,
    Context,
    CreditResult,
    Episode,
    Grain,
    SourceEnd,
    UnitRecord,
    leaves,
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


# The walk's yield-stop policy (docs/ACQUISITION_LOOP.md, phase 4B): stop
# expanding further seeds when the posterior says fewer than 1 in 4 further
# seeds would reach anything new, at 95% certainty, never before 8 seeds.
# These are the stop rule's documented defaults, not a fit to any graph;
# `rarefaction.searches_to_stop` reports the policy fires after 10 straight
# barren seeds. Walks under 8 seeds can never be cut by yield, only by the
# disclosed budget caps.
WALK_YIELD_CONTROL = ControllerConfig.uniform(
    ("overall",), gamma=0.0, rho=0.0, streak_length=8
)

# The grain is declared ONCE, as data, with its unit and credit sentences and
# its policy (docs/ACQUISITION_LOOP.md rule 4). The scope level and key that
# used to be string literals at the episode-composition call site come from
# this declaration.
WALK_GRAIN = Grain(
    name="walk",
    unit=(
        "one seed expansion: every hop this walk makes outward from one seed "
        "node, to the requested depth"
    ),
    credit=(
        "one node encounter: an accepted, non-duplicate hop arrival at a graph "
        "node, counted by its opaque node id, so re-arrivals via distinct hops "
        "are genuine repeat encounters"
    ),
    control=WALK_YIELD_CONTROL,
)

#: This walk's episode key. One GRAPHWALK runs one walk episode, so the key is
#: constant; it is the `scope_key` on the emitted record.
WALK_EPISODE_KEY = "graphwalk"

#: Facet name prefix for the per-depth-step partition of a seed's encounters.
#: The suffix is the 1-based depth step, taken from the command's own `depth`
#: argument -- no graph key is involved.
DEPTH_FACET_PREFIX = "depth_"

# Payload ceiling on the per-unit records carried in the emitted walk yield,
# counted in CREDIT IDENTITIES rather than in units, because identities are
# what the payload is made of. NO MEASUREMENT JUSTIFIES 5,000; it is stated
# here so that it is one number in one place, and every walk that reaches it
# says so in the emitted `units.window` record rather than quietly shortening
# the evidence. It is above the largest emission this engine has recorded on a
# real graph (2,000 encounters over 40 seeds), so it does not bind there.
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
    """Emit the walk's per-unit records, windowed with disclosure.

    The kernel emits each unit's full credit identities; a broad walk can make
    thousands of them, and this record travels to the planner. So the records
    are carried whole up to `WALK_UNIT_CREDIT_WINDOW` identities, taken from
    both ends of the walk (the first units and the last ones, alternating), and
    the omitted middle is named -- count, index range, and what is still
    recoverable without it. Nothing is sliced silently, and the units list is
    never replaced by a summary of itself.
    """

    total = len(unit_records)
    costs = [len(record.credits) for record in unit_records]
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
        # carried: which seeds ran is never a casualty of a payload ceiling.
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
        """Walk, and report what the walk did not reach.

        The walk is a composition of one `Episode` (`WALK_GRAIN`) and writes no
        loop of its own: the kernel pulls a seed, expands it, credits its node
        encounters, records the numbers, and reads the verdict
        (docs/ACQUISITION_LOOP.md §"The template", rule 1).

        `source_cap` of None expands every seed. Whichever end stops the walk is
        named BY THE LOOP -- a yield verdict, the seed bound, the node budget the
        source reports -- and this method translates that named end into the
        caller's completeness disclosure. A caller that gets 500 rows needs to
        know whether that is the whole neighbourhood, all the room there was, or
        all the seeds that fit.
        """
        walked_data: list[dict] = []
        visited_hops = set()
        seeds_total = len(source_nodes)
        stats = {
            "nodes_with_truncated_fanout": 0,
            "edges_discarded_by_fanout_cap": 0,
        }
        budget = NodeBudget(limit=max_nodes)
        step_names = tuple(
            f"{DEPTH_FACET_PREFIX}{step + 1}" for step in range(depth)
        )
        channel_schema = (
            ChannelSchema.partition(step_names, overlap_allowed=True)
            if step_names
            else ChannelSchema.single()
        )

        def expand(node: dict) -> SeedExpansion | None:
            """Expand one seed. The grain's extractor; it decides nothing.

            Returns the seed's final-depth rows plus the node encounters made
            on the way, partitioned by depth step (one entry per accepted,
            non-duplicate hop arrival -- re-arrivals at a node via distinct
            hops are genuine repeat encounters and feed Q1/Q2). ``None`` means
            the seed carries no id and could not be expanded at all -- a
            non-judgement, not a barren seed.

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

        def credit_seed(node: dict, expansion: SeedExpansion | None) -> CreditResult:
            """The grain's crediter: opaque node ids, grouped by depth step.

            The groups partition the seed's credits exactly, so the per-step
            curves the kernel accumulates from them are a partition of the
            walk's curve, and a reader can rebuild what a depth-step episode
            would have seen without re-walking the graph.
            """
            if expansion is None:
                return CreditResult.disabled(
                    "seed carries no id and could not be expanded"
                )
            return CreditResult(
                credits=expansion.encounters,
                facets=dict(zip(step_names, expansion.encounters_by_step)),
            )

        def collect(leaf: Any, contribution: Any, record: UnitRecord) -> None:
            """The grain's hook: the rows, and the budget those rows spend.

            Decoupled from crediting by construction -- the loop discards what
            this returns, and nothing it writes is read by `expand`.
            """
            expansion = contribution.extracted
            if expansion is None:
                return
            walked_data.extend(expansion.rows)
            budget.charge(len(expansion.rows))

        record = Episode(
            grain=WALK_GRAIN,
            key=WALK_EPISODE_KEY,
            source=leaves(
                _SeedStream(source_nodes, budget),
                expand,
                credit_seed,
                label=lambda node: str(node.get("id") or "<no-id>"),
            ),
            on_unit=collect,
            # The declared per-walk seed budget is the episode's safety bound:
            # a cap, ending `bound_hit` with `unit_bound`, never a verdict.
            bound=source_cap,
        ).run(
            Context(
                order=(WALK_GRAIN,),
                channel_schemas={WALK_GRAIN.name: channel_schema},
            )
        )

        walk_yield = record.as_record()
        # Windowed with disclosure, never replaced by a summary of itself: the
        # per-unit credit identities are what lets a reader rebuild incidence
        # membership and estimator arithmetic rather than only read the result.
        walk_yield["units"] = _window_unit_records(record.unit_records)

        units_crediting_disabled = sum(
            1 for unit in record.unit_records if unit.yield_record.crediting_disabled
        )
        seeds_expanded = record.units_consumed - units_crediting_disabled
        seeds_skipped = seeds_total - seeds_expanded
        detail = {
            "seeds_expanded": seeds_expanded,
            "seeds_total": seeds_total,
            # A seed that carried no id was counted and could not be judged.
            # Named here so "nothing was found" and "nothing was asked" stay
            # different observables at the caller, not only in the yield curve.
            "seeds_without_id": units_crediting_disabled,
            # The requested depth is the number of units a seed-grain episode
            # would have had, which is what decides whether that grain could
            # ever fire; carried so the decision is checkable from the export.
            "walk_depth": depth,
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
