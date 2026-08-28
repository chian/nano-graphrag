from __future__ import annotations
"""
FIND command handler.
"""

import re
from typing import Any, List
from .base import CommandHandler
from ..types import Command, ExecutionResult, Provenance
from ..adapters.base import (
    EDGE_SURFACE,
    NODE_SURFACE,
    PATH_SURFACE,
    GraphAdapter,
    complete_result,
    select_filters,
)
from ..search_refinement_agent import LLMSearchRefinementAgent, refinement_record
from ..state_manager import StateManager
from ..contracts import make_contract


class FindHandler(CommandHandler):
    """Handles FIND commands for graph traversal."""

    # Size of the probe that precedes a full path retrieval, counted in
    # sources expanded. NO MEASUREMENT
    # JUSTIFIES EITHER NUMBER — neither is cited anywhere in this tree, and both
    # predate any recorded experiment on probe sizing.
    #
    # They are kept anyway, on a narrower warrant than the constants deleted
    # alongside them: these bound a SAMPLE that exists to be a sample. The probe
    # feeds a refinement judgement about whether to widen or tighten, and its
    # rows are only ever the returned answer in the one branch that has nothing
    # to tighten — where the disclosure says outright that the output is
    # probe-bounded. A probe that is honest about being a probe is not
    # truncation; it becomes truncation exactly when its output is passed off as
    # the result, which is the case this disclosure exists to make visible.
    PATH_PROBE_SOURCE_BUDGET = 120
    PATH_POST_PROBE_SIZE = 20

    def __init__(self, state_store, context_store, adapter: GraphAdapter, llm_func=None, state_manager=None, prompt_logger=None):
        super().__init__(state_store, context_store)
        self.adapter = adapter
        self.search_refinement_agent = LLMSearchRefinementAgent(llm_func, prompt_logger=prompt_logger)
        self.state_manager = state_manager or StateManager(state_store, context_store)
    
    def can_handle(self, command: Command) -> bool:
        return command.command_type == "FIND"
    
    def execute(self, command: Command) -> ExecutionResult:
        """Execute FIND command."""
        try:
            args = command.args
            target = args["target"]  # nodes, edges, paths
            criteria = args["criteria"]
            
            # Parse criteria to extract filters
            filters = self._parse_criteria(criteria)
            
            strategy = "default"
            diagnostics = {}
            # One criteria string parses into a union of node-, edge- and
            # path-shaped keys. Route each retrieval surface only the keys it
            # enforces instead of handing it the whole union: the adapter now
            # refuses filters it will not apply, and silently handing it keys
            # meant for another surface is exactly the fail-open this guards.
            # `select_filters` drops nothing a surface would have honoured, so
            # this is behaviour-preserving for FIND.
            routed_filters = {}
            # Every retrieval below states whether it delivered every match.
            # This is read immediately after each call, while it still describes
            # that call, and it is never left unset: a FIND with no disclosure
            # would be indistinguishable from a complete one, which is the
            # confusion the disclosure exists to remove.
            result_completeness = complete_result(0)
            if target == "nodes":
                routed_filters = select_filters(filters, NODE_SURFACE)
                result = self.adapter.find_nodes(routed_filters)
                result_completeness = self.adapter.last_completeness()
            elif target == "edges":
                routed_filters = select_filters(filters, EDGE_SURFACE)
                result = self.adapter.find_edges(routed_filters)
                result_completeness = self.adapter.last_completeness()
            elif target == "paths":
                routed_filters = path_filters = select_filters(filters, PATH_SURFACE)
                result, result_completeness = self._find_paths_with_refinement(command, path_filters)
                strategy = path_filters.get("_strategy", "adapter_find_paths")
                diagnostics = path_filters.get("_refinement", {})
            else:
                return self._create_result(
                    command=command,
                    status="error",
                    error_message=f"Unknown target type: {target}"
                )
            
            result_contract = make_contract(
                payload_kind=target,
                data=result,
                label_field="data.entity_name" if target == "nodes" else "id",
                scope="current_rows_only",
                usable_by=["PROCESS", "GRAPHWALK", "AGGREGATE", "SHOW", "SELECT"],
                grain_type="node" if target == "nodes" else ("edge" if target == "edges" else "path"),
                grain_keys=["id"] if target == "nodes" else (["src_id", "tgt_id", "relation_type"] if target == "edges" else ["path"]),
                multiplicity_preserved=True,
            )
            if strategy != "default":
                result_contract["notes"] = [f"retrieval_strategy: {strategy}"]
            if diagnostics:
                result_contract["refinement"] = diagnostics
            # Emitted on EVERY FIND, including the complete case. `complete:
            # True` with `bound: None` is a positive assertion that nothing was
            # left behind — not the absence of a warning — so a consumer can
            # tell "all of it" from "as much as some bound allowed" without
            # having to know which bounds this engine happens to have.
            result_contract["completeness"] = dict(
                result_completeness,
                returned=len(result) if isinstance(result, list) else result_completeness.get("returned", 0),
            )
            # Store result using centralized state manager
            result_key = f"find_{target}_{len(self.context_store.keys())}"
            self.state_manager.store_variable_data(result_key, result, store_in_state=False, store_in_context=True, contract=result_contract)
            
            # Also store as last_nodes_result for compatibility
            self.state_manager.store_variable_data("last_nodes_result", result, store_in_state=False, store_in_context=True, contract=result_contract)
            
            # Store with user-specified variable name if AS clause was used
            if "result_var" in args and args["result_var"]:
                self.state_manager.store_variable_data(
                    args["result_var"], 
                    result, 
                    store_in_state=True,  # Store in state for persistence
                    store_in_context=True,
                    description=f"Nodes found with criteria: {criteria}",
                    contract=result_contract,
                )
                print(f"DEBUG: FIND - Saved result to variable: {args['result_var']}")
            
            # Create provenance. Both the parsed union and the subset actually
            # sent to the adapter are recorded: logging only the union would
            # claim constraints the query never carried, and logging only the
            # routed subset would hide that the criteria asked for more.
            provenance = [
                self._create_provenance(
                    source_id="graph-adapter",
                    method="find",
                    target=target,
                    criteria=criteria,
                    filters=filters,
                    parsed_filters=filters,
                    routed_filters=routed_filters,
                    filters_not_routed=sorted(set(filters) - set(routed_filters)),
                )
            ]
            
            # More meaningful status based on actual results
            if not result:
                status = "empty"
                count = 0
            elif isinstance(result, list) and len(result) == 0:
                status = "empty" 
                count = 0
            else:
                status = "success"
                count = len(result) if isinstance(result, list) else (1 if result else 0)
            
            # Create initial result
            result_obj = self._create_result(
                command=command,
                status=status,
                data=result,
                count=count,
                provenance=provenance,
                contract=result_contract,
            )
            
            return result_obj
            
        except Exception as e:
            return self._create_result(
                command=command,
                status="error",
                error_message=str(e)
            )
    
    def _parse_criteria(self, criteria: str) -> dict:
        """Parse criteria string into filter dictionary - bulletproof version."""
        print(f"DEBUG: Parsing criteria: '{criteria}'")
        filters = {}
        
        # Clean up the criteria string
        criteria = criteria.strip().rstrip(';')
        
        # Path-style semantics: source entity_type=X edge relation_type=R target entity_type=Y
        source_match = re.search(r"source\s+entity_type\s*=\s*['\"]?([A-Z0-9_]+)['\"]?", criteria, re.IGNORECASE)
        target_match = re.search(r"target\s+entity_type\s*=\s*['\"]?([A-Z0-9_]+)['\"]?", criteria, re.IGNORECASE)
        relation_match = re.search(r"edge\s+relation_type\s*=\s*['\"]?([A-Z0-9_]+)['\"]?", criteria, re.IGNORECASE)
        if source_match:
            filters["source_filter"] = {"entity_type": f"\"{source_match.group(1).strip()}\""}
        if target_match:
            filters["target_filter"] = {"entity_type": f"\"{target_match.group(1).strip()}\""}
        if relation_match:
            filters["relation_type"] = relation_match.group(1).strip()

        # Entity type parsing - handle any variation of quotes, spaces, etc.
        entity_list_match = re.search(
            r"(?:entity_type|label)\s+in\s*\[([^\]]+)\]", criteria, re.IGNORECASE
        )
        if entity_list_match:
            entity_types = self._parse_type_list(entity_list_match.group(1))
            if entity_types:
                filters["entity_type"] = entity_types
                print(f"DEBUG: Extracted entity_type list: {filters['entity_type']}")

        if "entity_type" in criteria.lower() or "label" in criteria.lower():
            if "entity_type" in filters:
                pass
            # Handle OR conditions by splitting on OR and processing each part
            elif " OR " in criteria.upper():
                # Split on OR and process each part
                parts = re.split(r'\s+OR\s+', criteria, flags=re.IGNORECASE)
                entity_types = []
                for part in parts:
                    # Match: entity_type=PERSON, entity_type="PERSON", entity_type='PERSON', entity_type = PERSON, etc.
                    patterns = [
                        r"(?:entity_type|label)\s*=\s*['\"]?([A-Z0-9_|]+)['\"]?",
                        r"(?:entity_type|label)\s*:\s*['\"]?([A-Z0-9_|]+)['\"]?",
                        r"(?:entity_type|label)\s+['\"]?([A-Z0-9_|]+)['\"]?",
                    ]
                    
                    for pattern in patterns:
                        match = re.search(pattern, part, re.IGNORECASE)
                        if match:
                            for entity_type in self._parse_type_list(match.group(1)):
                                entity_types.append(entity_type)
                                print(f"DEBUG: Extracted entity_type from OR part: '{entity_type}'")
                            break
                
                if entity_types:
                    filters["entity_type"] = entity_types
                    print(f"DEBUG: Final entity_types: {entity_types}")
            else:
                # Single entity type (no OR)
                patterns = [
                    r"(?:entity_type|label)\s*=\s*['\"]?([A-Z0-9_|]+)['\"]?",
                    r"(?:entity_type|label)\s*:\s*['\"]?([A-Z0-9_|]+)['\"]?",
                    r"(?:entity_type|label)\s+['\"]?([A-Z0-9_|]+)['\"]?",
                ]
                
                for pattern in patterns:
                    match = re.search(pattern, criteria, re.IGNORECASE)
                    if match:
                        entity_types = self._parse_type_list(match.group(1))
                        filters["entity_type"] = (
                            entity_types[0]
                            if len(entity_types) == 1
                            else entity_types
                        )
                        print(f"DEBUG: Extracted entity_type: '{match.group(1)}' -> '{filters['entity_type']}'")
                        break
        
        # Relationship name parsing
        if "relationship_name" in criteria.lower():
            patterns = [
                r"relationship_name\s*=\s*['\"]?([A-Z0-9_]+)['\"]?",
                r"relationship_name\s*:\s*['\"]?([A-Z0-9_]+)['\"]?",
                r"relationship_name\s+['\"]?([A-Z0-9_]+)['\"]?",
            ]
            for pattern in patterns:
                match = re.search(pattern, criteria, re.IGNORECASE)
                if match:
                    rel_name = match.group(1).strip()
                    filters["relationship_name"] = f'"{rel_name}"'
                    print(f"DEBUG: Extracted relationship_name: '{rel_name}' -> '{filters['relationship_name']}'")
                    break
        
        # Description contains parsing
        if "description" in criteria.lower() and "contains" in criteria.lower():
            patterns = [
                r"description\s+contains\s+['\"]([^'\"]*)['\"]",
                r"description\s*:\s*contains\s+['\"]([^'\"]*)['\"]",
                r"description\s*=\s*contains\s+['\"]([^'\"]*)['\"]",
            ]
            
            any_match = re.search(
                r"description\s+contains\s+any\s+of\s*\[([^\]]+)\]",
                criteria,
                re.IGNORECASE,
            )
            if any_match:
                terms = [
                    match.group(1).strip()
                    for match in re.finditer(
                        r"['\"]([^'\"]+)['\"]",
                        any_match.group(1),
                    )
                    if match.group(1).strip()
                ]
                if terms:
                    filters["description_contains"] = terms
                    print(f"DEBUG: Extracted description_contains any: {terms}")

            or_terms = [
                match.group(1).strip()
                for match in re.finditer(
                    r"description\s+contains\s+['\"]([^'\"]+)['\"]",
                    criteria,
                    re.IGNORECASE,
                )
                if match.group(1).strip()
            ]
            if len(or_terms) > 1:
                filters["description_contains"] = or_terms
                print(f"DEBUG: Extracted description_contains OR terms: {or_terms}")

            for pattern in patterns:
                if "description_contains" in filters:
                    break
                match = re.search(pattern, criteria, re.IGNORECASE)
                if match:
                    desc_text = match.group(1).strip()
                    filters["description_contains"] = desc_text
                    print(f"DEBUG: Extracted description_contains: '{desc_text}'")
                    break
        
        # Store raw criteria for fallback matching
        filters["raw_criteria"] = criteria
        
        print(f"DEBUG: Final filters: {filters}")
        return filters

    @staticmethod
    def _parse_type_list(raw_types: str) -> List[str]:
        return [
            match.group(1).strip()
            for match in re.finditer(r"['\"]?([A-Z0-9_]+)['\"]?", raw_types.replace("|", ","), re.IGNORECASE)
        ]

    def _clean_type(self, value: str | None) -> str:
        return str(value or "").strip('"').strip("'").strip()

    def _find_paths_with_refinement(self, command: Command, filters: dict) -> tuple[list[dict], dict]:
        """Probe, then run the retrieval the probe's verdict selects.

        Returns the rows and the completeness disclosure that describes them.
        Each branch below ends in a different retrieval, and they are not
        equally complete — the probe branch returns probe-sized output — so the
        disclosure is produced per branch rather than inferred afterwards from
        the row count.
        """
        initial_filters = dict(filters)
        initial_filters["_max_results"] = self.PATH_POST_PROBE_SIZE
        initial_filters["_max_sources"] = self.PATH_PROBE_SOURCE_BUDGET
        initial_rows = list(self.adapter.iter_paths(initial_filters))
        probe_completeness = self.adapter.last_completeness()
        refinement = self.search_refinement_agent.get_find_refinement(command.args, iter(initial_rows))
        # The declared shape, not a wrapper. The old
        # `{"refinement": ..., "sample_size": ...}` nesting meant the executor's
        # `refinement.get("refinement_hint")` read off the wrapper and got None,
        # so FIND's hint never once reached a planner prompt.
        filters["_refinement"] = refinement_record(
            hint=refinement.get("refinement_hint", ""),
            available=bool(refinement.get("refinement_available", True)),
            trigger=refinement.get("refinement_unavailable_trigger", ""),
            sample_size=len(initial_rows),
            caps={
                "probe_source_budget": self.PATH_PROBE_SOURCE_BUDGET,
                "probe_emit_bound": self.PATH_POST_PROBE_SIZE,
            },
        )

        if refinement.get("refinement_hint", "keep") == "keep":
            filters["_strategy"] = "refinement_keep"
            # No `_max_results`. The full run is bounded by the adapter's
            # declared path work budget, not by a count of rows: a count bound
            # here would decide which paths exist by product-iteration order.
            full_filters = dict(filters)
            rows = self.adapter.find_paths(full_filters)
            return rows, self.adapter.last_completeness()

        if filters.get("source_filter") and filters.get("target_filter") and filters.get("relation_type"):
            filters["_strategy"] = "refinement_tighten_strict_relation"
            full_filters = dict(filters)
            full_filters["_max_sources"] = 0
            return self._strict_relation_paths(full_filters)

        # Nothing to tighten, so the PROBE'S OWN ROWS are the answer. That
        # output is probe-sized by construction, and the probe's disclosure is
        # what says so.
        filters["_strategy"] = "refinement_no_tightening_available"
        return initial_rows, probe_completeness

    def _strict_relation_paths(self, filters: dict) -> tuple[list[dict], dict]:
        # The `source_limit` parameter is gone. Its only call site passed None,
        # so `source_nodes[:source_limit]` was always the identity -- a dormant
        # positional cut on traversal seeds, wired to a knob nothing set.
        # Deleted rather than disclosed: there is no bound here to report,
        # and leaving it would be leaving a loaded gun with the safety on.
        source_nodes = self.adapter.find_nodes(filters["source_filter"])
        target_nodes = self.adapter.find_nodes(filters["target_filter"])
        target_ids = {row["id"] for row in target_nodes}
        source_ids = {row["id"] for row in source_nodes}
        relation_type = filters.get("relation_type", "")
        if not source_ids or not target_ids or not relation_type:
            return [], complete_result(0)
        matched = []
        edges = self.adapter.find_edges({"relation_type": relation_type})
        edge_completeness = self.adapter.last_completeness()
        for edge in edges:
            if edge["source"] in source_ids and edge["target"] in target_ids:
                matched.append(
                    {
                        "source": edge["source"],
                        "target": edge["target"],
                        "path": [edge["source"], edge["target"]],
                        "length": 1,
                        "type": "path",
                        "relation_type": relation_type,
                    }
                )
        # The count cut that used to end this loop truncated an in-memory scan
        # over an already-materialized edge list. There is no combinatorial
        # explosion behind this loop — it is a membership test per edge — so the
        # cut bought nothing and discarded matches by edge-iteration order.
        #
        # This result is exactly as complete as the edge scan it filters, so it
        # inherits that disclosure with its own returned count.
        return matched, dict(edge_completeness, returned=len(matched))
