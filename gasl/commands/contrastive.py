"""
Contrastive Analysis Commands
Commands for finding alternative mechanisms, opposing effects, and competing entities
"""

from typing import Any, List, Dict
from .base import CommandHandler
from ..types import Command, ExecutionResult, Provenance
from ..adapters.base import GraphAdapter
from ..state_manager import StateManager
from query_generation.graph_validator import get_causal_edge_types


class FindAlternativesHandler(CommandHandler):
    """
    FIND_ALTERNATIVES command: Find different mechanisms achieving the same outcome.

    Usage: FIND_ALTERNATIVES target_entity domain_name AS result_var
    """

    def __init__(self, state_store, context_store, adapter: GraphAdapter, domain_name: str, state_manager=None):
        super().__init__(state_store, context_store, state_manager)
        self.adapter = adapter
        self.domain_name = domain_name
        self.state_manager = state_manager or StateManager(state_store, context_store)

    def can_handle(self, command: Command) -> bool:
        return command.command_type == "FIND_ALTERNATIVES"

    def execute(self, command: Command) -> ExecutionResult:
        """Find alternative mechanisms that lead to the same outcome."""
        try:
            args = command.args
            target_entity = args.get("target_entity")

            if not target_entity:
                return self._create_result(
                    command=command,
                    status="error",
                    error_message="target_entity is required"
                )

            # Get causal edge types for this domain
            causal_types = get_causal_edge_types(self.domain_name)

            # Find all incoming edges to the target entity
            incoming_edges = self.adapter.find_edges({
                "target": target_entity
            })

            # Filter for causal edges
            causal_incoming = []
            for edge in incoming_edges:
                edge_data = edge.get("data", {})
                relation_type = edge_data.get("relation_type", "")
                if relation_type.upper() in [ct.upper() for ct in causal_types]:
                    causal_incoming.append(edge)

            # Extract source entities (alternative mechanisms)
            alternatives = []
            for edge in causal_incoming:
                source = edge.get("source") or edge.get("src_id")
                edge_data = edge.get("data", {})
                if source:
                    # Get source node details
                    source_node = self.adapter.find_nodes({"id": source})
                    if source_node:
                        alternatives.append({
                            "entity": source,
                            "entity_type": source_node[0].get("entity_type", "UNKNOWN") if source_node else "UNKNOWN",
                            "relation_type": edge_data.get("relation_type"),
                            "description": edge_data.get("description", ""),
                            "weight": edge_data.get("weight", 0),
                            "source_papers": edge_data.get("source_papers", [])
                        })

            # Store result
            if "result_var" in args and args["result_var"]:
                self.state_manager.store_variable_data(
                    args["result_var"],
                    alternatives,
                    store_in_state=True,
                    store_in_context=True,
                    description=f"Alternative mechanisms for {target_entity}"
                )

            provenance = [
                self._create_provenance(
                    source_id="contrastive-analysis",
                    method="find_alternatives",
                    target_entity=target_entity,
                    num_alternatives=len(alternatives)
                )
            ]

            return self._create_result(
                command=command,
                status="success" if alternatives else "empty",
                data=alternatives,
                count=len(alternatives),
                provenance=provenance
            )

        except Exception as e:
            return self._create_result(
                command=command,
                status="error",
                error_message=str(e)
            )


class FindOpposingHandler(CommandHandler):
    """
    FIND_OPPOSING command: Find entities with opposing effects.

    Usage: FIND_OPPOSING entity domain_name AS result_var
    """

    def __init__(self, state_store, context_store, adapter: GraphAdapter, domain_name: str, state_manager=None):
        super().__init__(state_store, context_store, state_manager)
        self.adapter = adapter
        self.domain_name = domain_name
        self.state_manager = state_manager or StateManager(state_store, context_store)

    def can_handle(self, command: Command) -> bool:
        return command.command_type == "FIND_OPPOSING"

    def execute(self, command: Command) -> ExecutionResult:
        """Find entities with opposing effects (activators vs inhibitors)."""
        try:
            args = command.args
            entity = args.get("entity")

            if not entity:
                return self._create_result(
                    command=command,
                    status="error",
                    error_message="entity is required"
                )

            # Define opposing relationship pairs
            opposing_pairs = [
                ("ACTIVATES", "INHIBITS"),
                ("STIMULATES", "SUPPRESSES"),
                ("PROMOTES", "PREVENTS"),
                ("UPREGULATES", "DOWNREGULATES"),
                ("INCREASES", "DECREASES")
            ]

            # Find all outgoing edges from the entity
            outgoing_edges = self.adapter.find_edges({
                "source": entity
            })

            # Group targets by relationship type
            targets_by_relation = {}
            for edge in outgoing_edges:
                edge_data = edge.get("data", {})
                relation_type = edge_data.get("relation_type", "").upper()
                target = edge.get("target") or edge.get("tgt_id")

                if relation_type not in targets_by_relation:
                    targets_by_relation[relation_type] = []

                targets_by_relation[relation_type].append({
                    "target": target,
                    "description": edge_data.get("description", ""),
                    "weight": edge_data.get("weight", 0),
                    "source_papers": edge_data.get("source_papers", [])
                })

            # Find opposing pairs
            opposing_effects = []
            for positive, negative in opposing_pairs:
                if positive in targets_by_relation and negative in targets_by_relation:
                    opposing_effects.append({
                        "entity": entity,
                        "positive_relation": positive,
                        "negative_relation": negative,
                        "positive_targets": targets_by_relation[positive],
                        "negative_targets": targets_by_relation[negative],
                        "num_positive": len(targets_by_relation[positive]),
                        "num_negative": len(targets_by_relation[negative])
                    })

            # Store result
            if "result_var" in args and args["result_var"]:
                self.state_manager.store_variable_data(
                    args["result_var"],
                    opposing_effects,
                    store_in_state=True,
                    store_in_context=True,
                    description=f"Opposing effects for {entity}"
                )

            provenance = [
                self._create_provenance(
                    source_id="contrastive-analysis",
                    method="find_opposing",
                    entity=entity,
                    num_opposing_pairs=len(opposing_effects)
                )
            ]

            return self._create_result(
                command=command,
                status="success" if opposing_effects else "empty",
                data=opposing_effects,
                count=len(opposing_effects),
                provenance=provenance
            )

        except Exception as e:
            return self._create_result(
                command=command,
                status="error",
                error_message=str(e)
            )


class CompareMechanismsHandler(CommandHandler):
    """
    COMPARE_MECHANISMS command: Compare two mechanisms that achieve similar outcomes.

    Usage: COMPARE_MECHANISMS entity1 entity2 AS result_var
    """

    def __init__(self, state_store, context_store, adapter: GraphAdapter, state_manager=None):
        super().__init__(state_store, context_store, state_manager)
        self.adapter = adapter
        self.state_manager = state_manager or StateManager(state_store, context_store)

    def can_handle(self, command: Command) -> bool:
        return command.command_type == "COMPARE_MECHANISMS"

    def execute(self, command: Command) -> ExecutionResult:
        """Compare two mechanisms by analyzing their paths and targets."""
        try:
            args = command.args
            entity1 = args.get("entity1")
            entity2 = args.get("entity2")

            if not entity1 or not entity2:
                return self._create_result(
                    command=command,
                    status="error",
                    error_message="Both entity1 and entity2 are required"
                )

            # Get outgoing edges for both entities
            edges1 = self.adapter.find_edges({"source": entity1})
            edges2 = self.adapter.find_edges({"source": entity2})

            # Extract targets and relation types
            targets1 = {edge.get("target") or edge.get("tgt_id"): edge.get("data", {}).get("relation_type") for edge in edges1}
            targets2 = {edge.get("target") or edge.get("tgt_id"): edge.get("data", {}).get("relation_type") for edge in edges2}

            # Find common and unique targets
            common_targets = set(targets1.keys()) & set(targets2.keys())
            unique_to_1 = set(targets1.keys()) - set(targets2.keys())
            unique_to_2 = set(targets2.keys()) - set(targets1.keys())

            # Analyze common targets
            common_analysis = []
            for target in common_targets:
                common_analysis.append({
                    "target": target,
                    "entity1_relation": targets1[target],
                    "entity2_relation": targets2[target],
                    "same_relation": targets1[target] == targets2[target]
                })

            comparison = {
                "entity1": entity1,
                "entity2": entity2,
                "num_targets_entity1": len(targets1),
                "num_targets_entity2": len(targets2),
                "num_common_targets": len(common_targets),
                "num_unique_to_entity1": len(unique_to_1),
                "num_unique_to_entity2": len(unique_to_2),
                "common_targets": list(common_analysis),
                "unique_to_entity1": list(unique_to_1),
                "unique_to_entity2": list(unique_to_2),
                "similarity_score": len(common_targets) / max(len(targets1), len(targets2)) if max(len(targets1), len(targets2)) > 0 else 0
            }

            # Store result
            if "result_var" in args and args["result_var"]:
                self.state_manager.store_variable_data(
                    args["result_var"],
                    comparison,
                    store_in_state=True,
                    store_in_context=True,
                    description=f"Comparison of {entity1} and {entity2}"
                )

            provenance = [
                self._create_provenance(
                    source_id="contrastive-analysis",
                    method="compare_mechanisms",
                    entity1=entity1,
                    entity2=entity2,
                    similarity_score=comparison["similarity_score"]
                )
            ]

            return self._create_result(
                command=command,
                status="success",
                data=comparison,
                count=1,
                provenance=provenance
            )

        except Exception as e:
            return self._create_result(
                command=command,
                status="error",
                error_message=str(e)
            )


class FindCompetingHandler(CommandHandler):
    """
    FIND_COMPETING command: Find entities competing for the same target/resource.

    Usage: FIND_COMPETING target_entity domain_name AS result_var
    """

    def __init__(self, state_store, context_store, adapter: GraphAdapter, domain_name: str, state_manager=None):
        super().__init__(state_store, context_store, state_manager)
        self.adapter = adapter
        self.domain_name = domain_name
        self.state_manager = state_manager or StateManager(state_store, context_store)

    def can_handle(self, command: Command) -> bool:
        return command.command_type == "FIND_COMPETING"

    def execute(self, command: Command) -> ExecutionResult:
        """Find entities that compete for the same target."""
        try:
            args = command.args
            target_entity = args.get("target_entity")

            if not target_entity:
                return self._create_result(
                    command=command,
                    status="error",
                    error_message="target_entity is required"
                )

            # Find all incoming edges to the target
            incoming_edges = self.adapter.find_edges({
                "target": target_entity
            })

            # Group by relation type
            competitors_by_relation = {}
            for edge in incoming_edges:
                edge_data = edge.get("data", {})
                relation_type = edge_data.get("relation_type", "UNKNOWN")
                source = edge.get("source") or edge.get("src_id")

                if relation_type not in competitors_by_relation:
                    competitors_by_relation[relation_type] = []

                # Get source node details
                source_node = self.adapter.find_nodes({"id": source})

                competitors_by_relation[relation_type].append({
                    "entity": source,
                    "entity_type": source_node[0].get("entity_type", "UNKNOWN") if source_node else "UNKNOWN",
                    "description": edge_data.get("description", ""),
                    "weight": edge_data.get("weight", 0),
                    "source_papers": edge_data.get("source_papers", [])
                })

            # Find relation types with multiple competitors
            competing_groups = []
            for relation_type, competitors in competitors_by_relation.items():
                if len(competitors) >= 2:  # At least 2 entities competing
                    competing_groups.append({
                        "target": target_entity,
                        "relation_type": relation_type,
                        "num_competitors": len(competitors),
                        "competitors": competitors
                    })

            # Store result
            if "result_var" in args and args["result_var"]:
                self.state_manager.store_variable_data(
                    args["result_var"],
                    competing_groups,
                    store_in_state=True,
                    store_in_context=True,
                    description=f"Competing entities for {target_entity}"
                )

            provenance = [
                self._create_provenance(
                    source_id="contrastive-analysis",
                    method="find_competing",
                    target_entity=target_entity,
                    num_competing_groups=len(competing_groups)
                )
            ]

            return self._create_result(
                command=command,
                status="success" if competing_groups else "empty",
                data=competing_groups,
                count=len(competing_groups),
                provenance=provenance
            )

        except Exception as e:
            return self._create_result(
                command=command,
                status="error",
                error_message=str(e)
            )
