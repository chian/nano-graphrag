"""
Graph Navigation command handlers.
"""

import re
from typing import Any, List, Dict
from .base import CommandHandler
from ..types import Command, ExecutionResult, Provenance
from ..search_refinement_agent import (
    TRIGGER_EMPTY_PILOT,
    LLMSearchRefinementAgent,
    refinement_record,
)
from ..adapters.base import (
    GraphAdapter,
    node_entity_type,
)
from ..contracts import make_contract
from ..state_manager import StateManager
from ..walk_binding import GraphWalkBinding


# Bounds on the pilot walk that feeds the refinement judgement. NO MEASUREMENT
# JUSTIFIES ANY OF THESE THREE and none is cited in the tree. They are named
# here rather than inlined because they now travel to the planner beside the
# hint: a judgement formed under a 60-row cap is a different claim from the same
# judgement formed over a whole neighbourhood, and the planner could not
# previously tell which it was reading.
# `edge_cap` is measured -- see the citation at the fan-out cut in
# `GraphWalkBinding.walk`. It
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
        self.walk_binding = GraphWalkBinding(
            adapter,
            incident_edges=self._incident_edges,
            canonicalize_relation_token=self._canonicalize_relation_token,
        )
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
            pilot, _pilot_completeness = self.walk_binding.walk(
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
        walked_data, walk_completeness = self.walk_binding.walk(
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
