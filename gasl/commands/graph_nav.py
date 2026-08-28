"""
Graph Navigation command handlers.
"""

import re
from dataclasses import dataclass
from typing import Any, List, Dict, Tuple
from .base import CommandHandler
from ..types import Command, ExecutionResult, Provenance
from ..search_refinement_agent import (
    TRIGGER_EMPTY_PILOT,
    LLMSearchRefinementAgent,
    refinement_record,
)
from ..adapters.base import (
    BOUND_KIND_NONE,
    BOUND_KIND_WALK_NODE_BUDGET,
    BOUND_KIND_WALK_SEED_BUDGET,
    BOUND_KIND_WALK_YIELD_STOP,
    GraphAdapter,
    complete_result,
    completeness,
    node_entity_type,
)
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
from ..contracts import make_contract
from ..state_manager import StateManager


# Bounds on the pilot walk that feeds the refinement judgement. NO MEASUREMENT
# JUSTIFIES ANY OF THESE THREE and none is cited in the tree. They are named
# here rather than inlined because they now travel to the planner beside the
# hint: a judgement formed under a 60-row cap is a different claim from the same
# judgement formed over a whole neighbourhood, and the planner could not
# previously tell which it was reading.
# `edge_cap` is measured -- see the citation at the fan-out cut in `_walk`. It
# binds on under 2% of nodes and discards 15-19% of edge traversal on the three
# benchmark graphs, because the degree distribution is heavy-tailed.
#
# NO MEASUREMENT JUSTIFIES `max_nodes = 60`, and none is cited in the tree. What
# IS measured is that median node degree is 1-2, so 60 rows is roughly 30 seeds'
# worth at depth 1 against a `source_cap` of 10 -- it does not bind at depth 1,
# and binds progressively harder as depth rises. That is an observation about
# when it fires, not a justification of the number.
#
# NO MEASUREMENT JUSTIFIES `source_cap = 10` either.
PILOT_CAPS = {"source_cap": 10, "max_nodes": 60, "edge_cap": 15}

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

# ---------------------------------------------------------------------------
# The walk as a composition of `Episode` (docs/ACQUISITION_LOOP.md §"The
# template", phase 4E-b). `walk ⊃ seed`, with `query ⊃ walk` above it
# AVAILABLE BUT UNBOUND: nothing here constructs a `query` grain, because no
# component in this engine owns a query-scoped episode today — the charter's
# compositions table names the row and leaves who binds it undecided. The
# `seed` grain (one depth step per unit) is likewise NOT bound: a seed
# episode's unit count is exactly the requested `depth`, and this grain's
# policy needs `min_observations = 8` observations before it may stop, so a
# depth-step verdict cannot fire on any walk shallower than 8 hops. The
# per-step partition of every seed's encounters is emitted anyway (the facet
# groups below), so that decision is recomputable from the export rather than
# asserted here.
#
# The grain is declared ONCE, as data, with its unit and credit sentences and
# its policy (charter rule 4). The scope level and key that used to be string
# literals at the episode-composition call site come from this declaration.
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


class GraphNavHandler(CommandHandler):
    """Handles graph navigation commands: GRAPHWALK, GRAPHCONNECT, SUBGRAPH, GRAPHPATTERN."""

    # Cap on partial matches carried between GRAPHPATTERN hops. Registered as a
    # stated bound, reported whenever it binds, and never tuned to move a result.
    PATTERN_PARTIAL_BUDGET = 5000


    def __init__(self, state_store, context_store, adapter: GraphAdapter, llm_func=None, state_manager=None, prompt_logger=None):
        super().__init__(
            state_store,
            context_store,
            state_manager or StateManager(state_store, context_store),
        )
        self.adapter = adapter
        self.search_refinement_agent = LLMSearchRefinementAgent(llm_func, prompt_logger=prompt_logger)
    
    def can_handle(self, command: Command) -> bool:
        return command.command_type in ["GRAPHWALK", "GRAPHCONNECT", "SUBGRAPH", "GRAPHPATTERN"]
    
    def execute(self, command: Command) -> ExecutionResult:
        """Execute graph navigation command."""
        try:
            if command.command_type == "GRAPHWALK":
                return self._execute_graphwalk(command)
            elif command.command_type == "GRAPHCONNECT":
                return self._execute_graphconnect(command)
            elif command.command_type == "SUBGRAPH":
                return self._execute_subgraph(command)
            elif command.command_type == "GRAPHPATTERN":
                return self._execute_graphpattern(command)
            else:
                return self._create_result(
                    command=command,
                    status="error",
                    error_message=f"Unknown graph navigation command: {command.command_type}"
                )
        except Exception as e:
            return self._create_result(
                command=command,
                status="error",
                error_message=str(e)
            )
    
    def _execute_graphwalk(self, command: Command) -> ExecutionResult:
        """Execute GRAPHWALK command."""
        args = command.args
        from_var = args["from_variable"]
        follow_types = args["relationship_types"]
        depth = int(args.get("depth", 1))
        result_var = args.get("result_var")
        
        print(f"DEBUG: GRAPHWALK - from: {from_var}, follow: {follow_types}, depth: {depth}")
        
        # Get source nodes
        source_nodes = self._get_variable_data(from_var)
        if not source_nodes:
            # If the specified variable is empty, try to use last_nodes_result
            if self.context_store.has("last_nodes_result"):
                source_nodes = self.context_store.get("last_nodes_result")
                print(f"DEBUG: GRAPHWALK - Using last_nodes_result as fallback: {len(source_nodes)} nodes")
            else:
                return self._create_result(command=command, status="error", 
                                         error_message=f"Variable {from_var} not found or empty, and no last_nodes_result available")
        
        # Perform graph walk with memory limit
        follow_filters = self._normalize_follow_types(follow_types)

        pilot_refinement = {}
        if len(source_nodes) > 10 or depth > 1:
            pilot, _pilot_completeness = self._walk(
                source_nodes, follow_filters, depth, **PILOT_CAPS
            )
            pilot_contract = make_contract(
                payload_kind="walk_rows",
                data=pilot,
                label_field="data.entity_name",
                scope="current_rows_only",
                usable_by=["PROCESS", "AGGREGATE", "SHOW", "SELECT"],
                grain_type="edge",
                grain_keys=["src_id", "tgt_id", "relation_type", "path_depth"],
                multiplicity_preserved=True,
            )
            # WHY THIS CALL STILL EXISTS, now that it steers nothing here.
            #
            # Everything in this method that once acted on the answer is gone:
            # the depth/seed narrowing that read the hint, and the `min()` that
            # folded the model's confidence into the contract. What remains is
            # disclosure -- the typed record built below, carried to the planner
            # as `refinement_hint` beside the sample size and the caps the
            # sample was formed under.
            #
            # That is a real justification, not a placeholder: the planner is
            # the component that can act on a retrieval hint, because it can
            # re-issue the command. The engine acting on it invisibly was the
            # defect. So the call is kept ON THE CONDITION that its output
            # reaches the planner as data the planner weighs, and it is written
            # down here because a call that steers nothing is exactly what gets
            # rediscovered later and reconnected by whoever finds it useful.
            #
            # Two costs are open and neither is settled here: it is a large
            # model at reasoning_effort="high" on every walk with >10 seeds or
            # depth >1, and `gasl/` has no cost metering, so it is invisible to
            # the cost vector reward divides by. Wiring the prompt logger below
            # makes the call VISIBLE, not COSTED. If a measurement later shows
            # the disclosure does not change planner behaviour, this call has no
            # remaining defence and should go.
            pilot_refinement = self.search_refinement_agent.get_graphwalk_refinement(
                command.args,
                source_nodes[:10],
                iter(pilot),
                contract=pilot_contract,
            )
            # The pilot-driven adaptive reduction that stood here is DELETED.
            # It fired on exactly two paths and neither was salvageable by
            # retuning:
            #
            #   - an empty pilot, where absence of data narrowed the real walk.
            #     The sign is backwards: finding nothing at depth N is a reason
            #     to look further, not to cut to depth 1.
            #   - a >=25-row pilot the model flagged, via a predicate that
            #     answered True for `broaden` as readily as for `tighten`. A
            #     model asking for MORE breadth caused strictly less.
            #
            # It could also fire on neither: the default payload written when
            # the refinement call raised carried confidence 0.5 against a 0.55
            # threshold, so any failure of an unlogged LLM call silently halved
            # the walk while the planner was told the model chose to keep the
            # strategy. Two uncited constants 0.05 apart, and nobody chose that.
            #
            # With it gone the walk always runs at the requested depth under
            # the adapter's declared seed budget, so an unavailable refinement
            # agent leaves retrieval breadth unchanged -- which is the property
            # the typed fallback marker was going to have to police.

        # The seed budget is the adapter's declared work bound now, not a
        # literal here. None means expand every seed.
        walked_data, walk_completeness = self._walk(
            source_nodes,
            follow_filters,
            depth,
            source_cap=self.adapter.capabilities.walk_seed_budget,
            # NO MEASUREMENT JUSTIFIES EITHER NUMBER. Both are inline
            # constants carried forward, and both are now disclosed when they
            # fire rather than silently shortening the answer. `edge_cap=50` is
            # looser than the pilot's 15 but the same hub-suppressing shape:
            # p99 degree is 24-27, so it still binds at the tail.
            max_nodes=10000,
            edge_cap=50,
        )
        
        if result_var:
            walk_contract = make_contract(
                payload_kind="walk_rows",
                data=walked_data,
                label_field="data.entity_name",
                scope="current_rows_only",
                usable_by=["PROCESS", "AGGREGATE", "SHOW", "SELECT"],
                grain_type="edge",
                grain_keys=["src_id", "tgt_id", "relation_type", "path_depth"],
                multiplicity_preserved=True,
            )
            self.state_manager.store_variable_data(
                result_var,
                walked_data,
                store_in_state=True,
                store_in_context=True,
                description=f"Graph walk results for {result_var}",
                contract=walk_contract,
            )

        # Store result in context
        walk_contract = make_contract(
            payload_kind="walk_rows",
            data=walked_data,
            label_field="data.entity_name",
            scope="current_rows_only",
            usable_by=["PROCESS", "AGGREGATE", "SHOW", "SELECT"],
            grain_type="edge",
            grain_keys=["src_id", "tgt_id", "relation_type", "path_depth"],
            multiplicity_preserved=True,
        )
        self.context_store.set("last_walk_result", walked_data, contract=walk_contract)
        # Compatibility: many plans expect the most recent graph navigation result
        # to be accessible via last_nodes_result for downstream PROCESS/AGGREGATE.
        self.context_store.set("last_nodes_result", walked_data, contract=walk_contract)
        print(f"DEBUG: GRAPHWALK - stored {len(walked_data)} nodes in last_walk_result")
        
        # Create initial result
        result_obj = self._create_result(
            command=command,
            status="success",
            data=walked_data,
            count=len(walked_data),
            contract=walk_contract,
            provenance=[self._create_provenance("graph-walk", "graphwalk", 
                                               from_variable=from_var, depth=depth)]
        )
        
        # No `refinement:` free-text notes. The reason already has a structured
        # home under `walk_contract["refinement"]`, and the depth-adaptation
        # note described a narrowing that no longer exists -- it was also, while
        # it did exist, the ONLY record anywhere that the walk had been cut,
        # encoded as prose nothing could read.
        notes = list(walk_contract.get("notes", []))
        if pilot_refinement:
            # Recorded as a labelled model self-report, and nothing more. The
            # `min()` that used to fold the model's own confidence into the
            # contract's is gone: an LLM-emitted number may be disclosed, never
            # compared, thresholded or aggregated by engine code, because doing
            # so treats an assertion as a measurement.
            walk_contract["refinement"] = refinement_record(
                hint=pilot_refinement.get("refinement_hint", ""),
                available=bool(pilot_refinement.get("refinement_available", True)),
                trigger=(
                    pilot_refinement.get("refinement_unavailable_trigger", "")
                    or (TRIGGER_EMPTY_PILOT if not pilot else "")
                ),
                sample_size=len(pilot),
                caps=PILOT_CAPS,
                requested_depth=depth,
                effective_depth=depth,
            )
        # Emitted on every GRAPHWALK including the complete case, so a missing
        # key can never be read as "nothing was left out".
        walk_contract["completeness"] = walk_completeness
        walk_contract["notes"] = notes
        if result_var:
            self.context_store.set(result_var, walked_data, contract=walk_contract)
            if self.state_store.has_variable(result_var):
                self.state_store.set_variable_contract(result_var, walk_contract)
        self.context_store.set("last_walk_result", walked_data, contract=walk_contract)
        self.context_store.set("last_nodes_result", walked_data, contract=walk_contract)
        result_obj.contract = walk_contract
        
        return result_obj

    def _walk(
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

    def _incident_edges(self, node_id: Any) -> list[tuple[dict, str]]:
        edges: list[tuple[dict, str]] = []
        seen: set[tuple[str, str, str]] = set()
        for direction, filters in (
            ("out", {"source": node_id}),
            ("in", {"target": node_id}),
        ):
            for edge in self.adapter.find_edges(filters):
                key = (
                    str(edge.get("source")),
                    str(edge.get("target")),
                    str(
                        edge.get("data", {}).get("relation_type")
                        or edge.get("data", {}).get("relationship_name")
                        or ""
                    ),
                )
                if key in seen:
                    continue
                seen.add(key)
                edges.append((edge, direction))
        return edges

    @staticmethod
    def _normalize_follow_types(follow_types: str) -> list[str]:
        text = (follow_types or "").strip()
        if not text or text.lower() in {"*", "all", "any"}:
            return []
        if "=" in text:
            key, value = text.split("=", 1)
            if key.strip().lower() in {"relation_type", "relationship_name"}:
                text = value
        return [
            GraphNavHandler._canonicalize_relation_token(part)
            for part in re.split(r"[,|]", text)
            if part.strip()
        ]

    @staticmethod
    def _canonicalize_relation_token(text: str) -> str:
        raw = str(text or "").strip().strip('"').strip("'").lower()
        raw = re.sub(r"[\s\-\/]+", "_", raw)
        raw = re.sub(r"__+", "_", raw)
        return raw
    
    def _execute_graphconnect(self, command: Command) -> ExecutionResult:
        """Execute GRAPHCONNECT command."""
        args = command.args
        var1 = args["variable1"]
        var2 = args["variable2"]
        via_pattern = args.get("via_pattern", "")
        
        print(f"DEBUG: GRAPHCONNECT - {var1} to {var2} via {via_pattern}")
        
        # Get source node sets
        nodes1 = self._get_variable_data(var1)
        nodes2 = self._get_variable_data(var2)
        
        if not nodes1 or not nodes2:
            return self._create_result(command=command, status="error",
                                     error_message=f"Variables {var1} or {var2} not found or empty")
        
        # Find connections between node sets
        connections = []
        for node1 in nodes1:
            for node2 in nodes2:
                if node1.get("id") != node2.get("id"):  # Don't connect to self
                    # Path endpoint filters are node-filter mappings. Passing a
                    # formatted string here meant every membership test inside
                    # the adapter ran as a substring test against that string,
                    # matched nothing, and left both endpoints unconstrained —
                    # so every node pair in the graph came back as "connected".
                    paths = self.adapter.find_paths({
                        "source_filter": {"id_filter": node1["id"]},
                        "target_filter": {"id_filter": node2["id"]},
                    })
                    if paths:
                        connections.append({
                            "source": node1,
                            "target": node2,
                            "paths": paths
                        })
        
        # Store result in context
        self.context_store.set("last_connect_result", connections)
        print(f"DEBUG: GRAPHCONNECT - found {len(connections)} connections")
        
        return self._create_result(
            command=command,
            status="success",
            data=connections,
            count=len(connections),
            provenance=[self._create_provenance("graph-connect", "graphconnect",
                                               variable1=var1, variable2=var2)]
        )
    
    def _execute_subgraph(self, command: Command) -> ExecutionResult:
        """Execute SUBGRAPH command."""
        args = command.args
        around_var = args["around_variable"]
        radius = int(args.get("radius", 1))
        # "".split(",") is [""], which is truthy and then matched as a substring
        # against every candidate type. Parse to a canonical set so "no include
        # clause" is an empty set and reads as "no constraint".
        include_types = {
            self._canonicalize_relation_token(part)
            for part in (args.get("include_types") or "").split(",")
            if part.strip()
        }

        print(f"DEBUG: SUBGRAPH - around: {around_var}, radius: {radius}, include: {sorted(include_types)}")

        # Get center nodes
        center_nodes = self._get_variable_data(around_var)
        if not center_nodes:
            return self._create_result(command=command, status="error",
                                     error_message=f"Variable {around_var} not found or empty")

        # Every way a candidate can fail to enter the subgraph is counted, so an
        # empty or unexpanded result reports why instead of just being small.
        skipped = {
            "center_rows_without_id": 0,
            "center_ids_absent_from_graph": 0,
            "neighbors_absent_from_graph": 0,
            "neighbors_without_entity_type": 0,
            "neighbors_excluded_by_include_types": 0,
        }
        observed_types: set[str] = set()

        subgraph_nodes = set()
        subgraph_edges = []
        seen_edges: set[tuple] = set()
        center_ids: set = set()

        for center_node in center_nodes:
            center_id = center_node.get("id")
            if not center_id:
                skipped["center_rows_without_id"] += 1
                continue
            if not self.adapter.find_nodes({"id_filter": center_id}):
                skipped["center_ids_absent_from_graph"] += 1
                continue
            subgraph_nodes.add(center_id)
            center_ids.add(center_id)

            frontier = [center_id]
            for _step in range(radius):
                next_frontier = []
                for node_id in frontier:
                    # Shared with GRAPHWALK: one definition of what "the edges
                    # touching this node" means, so the two cannot drift. It also
                    # carries the correct edge-surface spelling (`source`/`target`);
                    # SUBGRAPH previously spelled it `source_filter`/`target_filter`,
                    # which the edge surface does not accept, so the filter was
                    # dropped and every edge in the graph came back for every node.
                    for edge, direction in self._incident_edges(node_id):
                        neighbor_id = edge["target"] if direction == "out" else edge["source"]
                        neighbor_rows = self.adapter.find_nodes({"id_filter": neighbor_id})
                        if not neighbor_rows:
                            skipped["neighbors_absent_from_graph"] += 1
                            continue
                        neighbor_type = node_entity_type(neighbor_rows[0])
                        if neighbor_type is not None:
                            observed_types.add(neighbor_type)
                        if include_types:
                            if neighbor_type is None:
                                skipped["neighbors_without_entity_type"] += 1
                                continue
                            if self._canonicalize_relation_token(neighbor_type) not in include_types:
                                skipped["neighbors_excluded_by_include_types"] += 1
                                continue

                        if neighbor_id not in subgraph_nodes:
                            next_frontier.append(neighbor_id)
                        subgraph_nodes.add(neighbor_id)
                        edge_key = (
                            edge["source"],
                            edge["target"],
                            str(
                                edge.get("data", {}).get("relation_type")
                                or edge.get("data", {}).get("relationship_name")
                                or ""
                            ),
                        )
                        if edge_key not in seen_edges:
                            seen_edges.add(edge_key)
                            subgraph_edges.append(edge)

                frontier = next_frontier

        # Get full node data for subgraph
        subgraph_node_data = []
        for node_id in subgraph_nodes:
            node_data = self.adapter.find_nodes({"id_filter": node_id})
            if node_data:
                subgraph_node_data.extend(node_data)

        neighbors_added = len(subgraph_nodes) - len(center_ids)
        disclosure = {
            "center_rows": len(center_nodes),
            "center_ids_resolved": len(center_ids),
            "neighbors_added": neighbors_added,
            "radius": radius,
            "include_types": sorted(include_types),
            "entity_types_observed_on_neighbors": sorted(observed_types),
            "skipped": skipped,
        }
        if include_types and not observed_types & include_types and skipped[
            "neighbors_excluded_by_include_types"
        ]:
            disclosure["warning"] = (
                "no neighbor entity_type matched any requested include type; "
                f"observed neighbor types were {sorted(observed_types)}"
            )

        subgraph_result = {
            "nodes": subgraph_node_data,
            "edges": subgraph_edges,
            "disclosure": disclosure,
        }

        # Store result in context
        self.context_store.set("last_subgraph_result", subgraph_result)
        print(
            f"DEBUG: SUBGRAPH - extracted {len(subgraph_node_data)} nodes, "
            f"{len(subgraph_edges)} edges, disclosure={disclosure}"
        )

        # A subgraph that adds no neighbor is a degradation, and the machinery
        # that acts on degradation is status-gated (the executor only inspects
        # results whose status is "error" or "empty"). Reporting "success" here
        # would leave the disclosure above accurate but unread.
        return self._create_result(
            command=command,
            status="success" if neighbors_added else "empty",
            data=subgraph_result,
            count=len(subgraph_node_data),
            provenance=[self._create_provenance("subgraph", "subgraph",
                                               around_variable=around_var, radius=radius,
                                               disclosure=disclosure)]
        )
    
    def _execute_graphpattern(self, command: Command) -> ExecutionResult:
        """Execute GRAPHPATTERN command."""
        args = command.args
        pattern_desc = args["pattern_description"]
        in_var = args["in_variable"]
        
        print(f"DEBUG: GRAPHPATTERN - pattern: {pattern_desc}, in: {in_var}")
        
        # Get nodes to search in
        search_nodes = self._get_variable_data(in_var)
        if not search_nodes:
            return self._create_result(command=command, status="error",
                                     error_message=f"Variable {in_var} not found or empty")
        
        # The pattern is a chain of node types joined by optional relation types,
        # read out of the command text. Previously one chain was hardcoded in
        # runtime code and every other pattern returned success with zero
        # matches, so "this graph has no such structure" and "this engine cannot
        # express your pattern" were the same observable.
        chain = self._parse_pattern_chain(pattern_desc)
        if len(chain["node_types"]) < 2:
            return self._create_result(
                command=command,
                status="error",
                error_message=(
                    f"GRAPHPATTERN could not read a node-type chain from {pattern_desc!r}. "
                    "Express the pattern as (TYPE_A)-[:RELATION]->(TYPE_B)... or "
                    "TYPE_A->TYPE_B->TYPE_C; at least two node types are required."
                ),
            )

        node_types = chain["node_types"]
        relation_types = chain["relation_types"]

        seeds = [
            node for node in search_nodes
            if self._type_token(node_entity_type(node)) == node_types[0]
        ]
        skipped = {
            "search_rows_without_entity_type": sum(
                1 for node in search_nodes if node_entity_type(node) is None
            ),
            "search_rows_wrong_head_type": len(search_nodes) - len(seeds),
        }
        observed_types = sorted(
            {self._type_token(node_entity_type(node)) for node in search_nodes} - {""}
        )

        pattern_matches: List[Dict] = []
        partials = [([node], []) for node in seeds]
        # Partial expansion is combinatorial and each partial costs an O(|E|)
        # scan per hop. The budget exists so a wide graph degrades instead of
        # hanging, and it is reported whenever it binds — a silent cap would make
        # a truncated match set indistinguishable from a complete one.
        budget_hit = False
        for hop in range(len(node_types) - 1):
            expected_type = node_types[hop + 1]
            expected_relation = relation_types[hop] if hop < len(relation_types) else ""
            extended = []
            for nodes_so_far, edges_so_far in partials:
                if len(extended) >= self.PATTERN_PARTIAL_BUDGET:
                    budget_hit = True
                    break
                tail_id = nodes_so_far[-1].get("id")
                if not tail_id:
                    continue
                for edge in self.adapter.find_edges({"source": tail_id}):
                    edge_relation = self._canonicalize_relation_token(
                        edge.get("data", {}).get("relation_type")
                        or edge.get("data", {}).get("relationship_name")
                        or ""
                    )
                    if expected_relation and edge_relation != expected_relation:
                        continue
                    neighbor_rows = self.adapter.find_nodes({"id_filter": edge["target"]})
                    if not neighbor_rows:
                        continue
                    if self._type_token(node_entity_type(neighbor_rows[0])) != expected_type:
                        continue
                    extended.append((nodes_so_far + [neighbor_rows[0]], edges_so_far + [edge]))
            partials = extended

        for nodes_so_far, edges_so_far in partials:
            pattern_matches.append({
                "pattern": pattern_desc,
                "node_types": node_types,
                "relation_types": relation_types,
                "nodes": nodes_so_far,
                "edges": edges_so_far,
            })

        disclosure = {
            "node_types": node_types,
            "relation_types": relation_types,
            "seed_rows": len(seeds),
            "entity_types_observed_in_search_variable": observed_types,
            "skipped": skipped,
            "ignored_clauses": chain.get("ignored_clauses", []),
            "partial_budget": self.PATTERN_PARTIAL_BUDGET,
            "partial_budget_reached": budget_hit,
        }
        warnings = []
        if not seeds:
            warnings.append(
                f"no row in {in_var} carries entity_type {node_types[0]!r}; "
                f"observed types were {observed_types}"
            )
        if chain.get("ignored_clauses"):
            warnings.append(
                "only the first chain in the pattern was matched; these clauses were "
                f"not applied: {chain['ignored_clauses']}"
            )
        if budget_hit:
            warnings.append(
                f"partial-match budget of {self.PATTERN_PARTIAL_BUDGET} was reached; "
                "the match set is incomplete"
            )
        if warnings:
            disclosure["warning"] = "; ".join(warnings)

        # Store result in context
        self.context_store.set("last_pattern_result", pattern_matches)
        print(f"DEBUG: GRAPHPATTERN - found {len(pattern_matches)} pattern matches, disclosure={disclosure}")

        # Keep the row-shaped payload downstream commands expect; the reason a
        # pattern found nothing rides along in provenance rather than changing
        # the shape of the result.
        return self._create_result(
            command=command,
            status="success" if pattern_matches else "empty",
            data=pattern_matches,
            count=len(pattern_matches),
            provenance=[self._create_provenance("graph-pattern", "graphpattern",
                                               pattern=pattern_desc, in_variable=in_var,
                                               disclosure=disclosure)]
        )

    @staticmethod
    def _type_token(value: Any) -> str:
        return GraphNavHandler._canonicalize_relation_token(value or "")

    @staticmethod
    def _parse_pattern_chain(pattern_desc: str) -> Dict[str, List[str]]:
        """Read a node-type / relation-type chain out of the pattern text.

        Accepts `(TYPE_A)-[:REL]->(TYPE_B)` and bare `TYPE_A->TYPE_B` forms. All
        types come from the command text; none are known to this module.
        """
        text = str(pattern_desc or "")
        # Only the first chain in the text is walked; `and`/`or`/`optional`
        # clauses describe alternatives this single-chain walk cannot express.
        # They are returned rather than dropped — a discarded constraint that
        # nobody reports is the same fail-open class as a dropped filter.
        clauses = re.split(r"\s+(?:and|or|optional)\s+", text, flags=re.IGNORECASE)
        head, ignored = clauses[0], [clause.strip() for clause in clauses[1:] if clause.strip()]

        node_types = [
            GraphNavHandler._canonicalize_relation_token(match)
            for match in re.findall(r"\(\s*([A-Za-z0-9_\- ]+?)\s*\)", head)
        ]
        relation_types = [
            GraphNavHandler._canonicalize_relation_token(match)
            for match in re.findall(r"\[\s*:?\s*([A-Za-z0-9_\- ]+?)\s*\]", head)
        ]
        if len(node_types) < 2:
            bare = [
                GraphNavHandler._canonicalize_relation_token(part)
                for part in head.split("->")
                if part.strip()
            ]
            if len(bare) >= 2:
                node_types, relation_types = bare, []
        return {
            "node_types": node_types,
            "relation_types": relation_types,
            "ignored_clauses": ignored,
        }
    
    def _get_variable_data(self, variable_name: str) -> List[Dict]:
        """Get data from state or context variable."""
        # Try context first
        if self.context_store.has(variable_name):
            return self.context_store.get(variable_name)
        
        # Try state
        if self.state_store.has_variable(variable_name):
            var_data = self.state_store.get_variable(variable_name)
            if isinstance(var_data, dict) and "items" in var_data:
                return var_data["items"]
            else:
                return var_data if isinstance(var_data, list) else [var_data]
        
        return []
