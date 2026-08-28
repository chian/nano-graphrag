"""
NetworkX adapter for GASL system.
"""

import re

import networkx as nx
from typing import Any, Dict, Iterator, List, Set
from .base import (
    BOUND_KIND_PATH_EMIT_BOUND,
    BOUND_KIND_PATH_SOURCE_BUDGET,
    EDGE_SURFACE,
    NODE_SURFACE,
    PATH_SURFACE,
    GraphAdapter,
    complete_result,
    completeness,
)
from ..types import AdapterCapabilities
from ..errors import AdapterError


class NetworkXAdapter(GraphAdapter):
    """NetworkX implementation of GraphAdapter."""

    def _get_capabilities(self) -> AdapterCapabilities:
        """Get NetworkX adapter capabilities."""
        return AdapterCapabilities(
            supports_path_finding=True,
            supports_cypher=False,
            supports_networkx=True,
            max_path_length=10,
            # No standing work bound. Measurement refuted the previous value
            # (250,000 pairs) from both directions at once: p90 endpoint
            # products reach 4.2e8 pairs, so no honest pair budget could let a
            # real query finish -- and with per-source traversal below, the
            # median query costs a few thousand graph searches and finishes
            # unbounded anyway. A bound nobody has measured is what this
            # campaign has been deleting.
            path_source_budget=None,
            # The graph is already in this process. There is no transport to
            # window.
            transport_window=None,
            # NO MEASUREMENT JUSTIFIES 100, and none is cited anywhere in the
            # tree; it is carried forward from the hardcoded `source_cap = 100`
            # this replaces. What changed is that it is now declared in one
            # place and announces itself when it fires, so a walk that covered
            # 100 of 4,000 seeds says so instead of returning a confident
            # partial answer. The value is a candidate for the first experiment
            # that measures it.
            walk_seed_budget=100,
            supported_node_properties=self._get_node_properties(),
            supported_edge_properties=self._get_edge_properties()
        )
    
    def get_schema(self) -> Dict[str, Any]:
        """Get graph schema information."""
        return {
            "node_labels": self._get_node_labels(),
            "edge_types": self._get_edge_types(),
            "node_properties": self._get_node_properties(),
            "edge_properties": self._get_edge_properties(),
            "total_nodes": self.graph.number_of_nodes(),
            "total_edges": self.graph.number_of_edges()
        }
    
    def find_nodes(self, filters: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Find nodes matching filters."""
        filters = self._validate_filters(filters, NODE_SURFACE, "find_nodes")
        try:
            nodes = []

            for node_id, data in self.graph.nodes(data=True):
                if self._node_matches_filters(node_id, data, filters):
                    node_info = {
                        "id": node_id,
                        "data": data,
                        "type": "node"
                    }
                    nodes.append(node_info)

            # No cap. The full match list is materialized above, so slicing it
            # here freed no memory — it only destroyed the only copy of the
            # rows past the cut, chosen by `nx.Graph.nodes()` insertion order
            # rather than by anything the caller asked for.
            self._disclose(complete_result(len(nodes)))
            return nodes

        except Exception as e:
            raise AdapterError(f"Failed to find nodes: {e}", "networkx", "find_nodes")
    
    def find_edges(self, filters: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Find edges matching filters."""
        filters = self._validate_filters(filters, EDGE_SURFACE, "find_edges")
        try:
            edges = []

            for source, target, data in self.graph.edges(data=True):
                if self._edge_matches_filters(source, target, data, filters):
                    edge_info = {
                        "source": source,
                        "target": target,
                        "data": data,
                        "type": "edge"
                    }
                    edges.append(edge_info)

            # No cap, for the same reason as find_nodes above.
            self._disclose(complete_result(len(edges)))
            return edges

        except Exception as e:
            raise AdapterError(f"Failed to find edges: {e}", "networkx", "find_edges")
    
    def find_paths(self, filters: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Find paths matching filters.

        Fully drains `iter_paths`, which owns the bounds and the disclosure.
        There is no cap here: the emit bound this method used to apply on top of
        the iterator was positional over an arbitrary product order, so raising
        or lowering it changed *which* paths the caller saw, not just how many.
        """
        filters = self._validate_filters(filters, PATH_SURFACE, "find_paths")
        try:
            return list(self.iter_paths(filters))

        except Exception as e:
            raise AdapterError(f"Failed to find paths: {e}", "networkx", "find_paths")

    def iter_paths(self, filters: Dict[str, Any]) -> Iterator[Dict[str, Any]]:
        """Yield paths incrementally so callers can probe early results before widening.

        One traversal per SOURCE, not one per (source, target) pair. This used
        to call `nx.shortest_path` inside a nested loop, paying a fresh graph
        search for every target of every source; `single_source_shortest_path`
        returns the paths from one source to every reachable node in a single
        pass, which is the same information for `|targets|` times less work. On
        this repo's median graph a fully-unfiltered path query drops from ~12.5
        million searches to ~3,540.

        That is not a speedup on top of a bound — it is what makes the bound
        unnecessary. The previous work budget was refuted from both ends: p90
        endpoint products are 4.2e8 pairs, so no pair budget both let real
        queries finish and kept the run alive, while under per-source traversal
        the median query completes with no bound at all.

        Two bounds may still apply, and they differ in kind:

        - `_max_sources` (falling back to `capabilities.path_source_budget`)
          bounds the *work*, counted in sources expanded. There is no standing
          default; a caller that wants a probe asks for one.
        - `_max_results` bounds *emission*. Also a probe size, also never a
          default: a default emit bound is positional truncation, discarding
          paths by iteration order rather than by anything the caller asked for.

        Either bound firing is disclosed, so a probe-sized answer is never
        mistakable for an exhaustive one.
        """
        filters = self._validate_filters(filters, PATH_SURFACE, "iter_paths")
        max_path_length = self.capabilities.max_path_length
        # An explicit budget always wins, including an explicit 0, which has
        # always meant "no work bound" and still does. `_max_pairs` is still
        # read so that no caller that worked before stops working; its value is
        # taken as a source budget, because pairs are no longer a unit of work
        # anything performs.
        if "_max_sources" in filters:
            source_budget = int(filters["_max_sources"] or 0)
        elif "_max_pairs" in filters:
            source_budget = int(filters["_max_pairs"] or 0)
        else:
            source_budget = int(self.capabilities.path_source_budget or 0)
        emit_bound = int(filters.get("_max_results") or 0)
        relation_type = str(filters.get("relation_type", "") or "").strip('"').strip("'")

        source_nodes = self._get_nodes_by_filter(filters.get("source_filter", {}))
        target_nodes = self._get_nodes_by_filter(filters.get("target_filter", {}))
        if not source_nodes or not target_nodes:
            self._disclose(complete_result(0))
            return

        search_graph = self._relation_filtered_graph(relation_type) if relation_type else self.graph

        # Drop endpoints that provably cannot participate, measured on the graph
        # actually being searched. `_relation_filtered_graph` copies EVERY node
        # and only the matching edges, so under a relation filter most of the
        # source set has no outgoing edge of that type and cannot begin a path
        # at all -- on this repo's largest graph that is 80-95% of the seeds,
        # expanded in full before this.
        #
        # This is not a bound and is not disclosed: a node with no outgoing edge
        # in the search graph cannot start a path, so no result is lost. It is
        # the removal of provably dead work, which is also why the coverage
        # denominator below counts expandable sources rather than nominal ones
        # -- a fraction over seeds incapable of producing a path would describe
        # phantom work.
        source_nodes = self._endpoints_with_incident_edges(search_graph, source_nodes, outgoing=True)
        target_nodes = self._endpoints_with_incident_edges(search_graph, target_nodes, outgoing=False)
        if not source_nodes or not target_nodes:
            self._disclose(complete_result(0))
            return

        sources_total = len(source_nodes)
        sources_expanded = 0
        emitted = 0
        # Stop the traversal at the longest path that could survive the filter
        # rather than computing longer ones and discarding them afterwards.
        # `cutoff` counts edges; `max_path_length` bounds nodes.
        cutoff = max(int(max_path_length) - 1, 0)

        for source in source_nodes:
            if source_budget and sources_expanded >= source_budget:
                # The work budget stopped the traversal. How many paths lie
                # under the unexpanded sources is unknown -- that is what not
                # expanding them means -- so the coverage of the source set is
                # reported instead of a fabricated residual.
                self._disclose(
                    completeness(
                        complete=False,
                        returned=emitted,
                        bound=source_budget,
                        bound_kind=BOUND_KIND_PATH_SOURCE_BUDGET,
                        residual_known=False,
                        residual=None,
                        sources_expanded=sources_expanded,
                        sources_total=sources_total,
                    )
                )
                return
            sources_expanded += 1
            try:
                reachable = nx.single_source_shortest_path(
                    search_graph, source, cutoff=cutoff
                )
            except nx.NodeNotFound:
                continue

            for target in target_nodes:
                if source == target:
                    continue
                path = reachable.get(target)
                if path is None:
                    continue
                edge_types = self._path_edge_types(path)
                source_entity = str((self.graph.nodes.get(source) or {}).get("entity_type") or "").strip('"').strip("'")
                target_entity = str((self.graph.nodes.get(target) or {}).get("entity_type") or "").strip('"').strip("'")
                # Standing disclosure for a consumer that stops draining early:
                # no bound of ours fired, but the scan is not finished either,
                # so this must not read as complete.
                self._disclose(
                    completeness(
                        complete=False,
                        returned=emitted + 1,
                        residual_known=False,
                        residual=None,
                        sources_expanded=sources_expanded,
                        sources_total=sources_total,
                    )
                )
                yield {
                    "source": source,
                    "target": target,
                    "path": path,
                    "length": len(path) - 1,
                    "type": "path",
                    "edge_types": edge_types,
                    "source_entity_type": source_entity,
                    "target_entity_type": target_entity,
                }
                emitted += 1
                if emit_bound and emitted >= emit_bound:
                    self._disclose(
                        completeness(
                            complete=False,
                            returned=emitted,
                            bound=emit_bound,
                            bound_kind=BOUND_KIND_PATH_EMIT_BOUND,
                            residual_known=False,
                            residual=None,
                            sources_expanded=sources_expanded,
                            sources_total=sources_total,
                        )
                    )
                    return

        self._disclose(complete_result(emitted))

    @staticmethod
    def _endpoints_with_incident_edges(search_graph, nodes: List[Any], *, outgoing: bool) -> List[Any]:
        """Keep only nodes that could begin (or end) a path in this graph.

        Order is preserved: this filters the endpoint list, it does not reorder
        it, so which paths come out first is unchanged.
        """
        if not search_graph.is_directed():
            # Undirected: a single incident edge lets a node serve either end.
            return [node for node in nodes if search_graph.degree(node) > 0]
        degree = search_graph.out_degree if outgoing else search_graph.in_degree
        return [node for node in nodes if degree(node) > 0]

    def _relation_filtered_graph(self, relation_type: str):
        """Return a graph view restricted to a specific relation type."""
        if not relation_type:
            return self.graph
        relation_type = str(relation_type).strip('"').strip("'").lower()
        if isinstance(self.graph, nx.MultiDiGraph):
            g = nx.MultiDiGraph()
            g.add_nodes_from(self.graph.nodes(data=True))
            for u, v, k, data in self.graph.edges(data=True, keys=True):
                edge_rel = str(data.get("relation_type") or data.get("relationship_name") or "").strip('"').strip("'").lower()
                if edge_rel == relation_type:
                    g.add_edge(u, v, key=k, **data)
            return g
        else:
            g = type(self.graph)()
            g.add_nodes_from(self.graph.nodes(data=True))
            for u, v, data in self.graph.edges(data=True):
                edge_rel = str(data.get("relation_type") or data.get("relationship_name") or "").strip('"').strip("'").lower()
                if edge_rel == relation_type:
                    g.add_edge(u, v, **data)
            return g

    def _path_edge_types(self, path: List[Any]) -> List[str]:
        """Return relation types along a path to make path semantics inspectable."""
        edge_types: List[str] = []
        if len(path) < 2:
            return edge_types
        for i in range(len(path) - 1):
            u, v = path[i], path[i + 1]
            if isinstance(self.graph, nx.MultiDiGraph):
                edge_data = self.graph.get_edge_data(u, v) or {}
                rel = None
                for _, data in edge_data.items():
                    rel = data.get("relation_type") or data.get("relationship_name")
                    if rel:
                        break
            else:
                data = self.graph.get_edge_data(u, v) or {}
                rel = data.get("relation_type") or data.get("relationship_name")
            edge_types.append(str(rel or ""))
        return edge_types
    
    def _node_matches_filters(self, node_id: Any, data: Dict[str, Any], filters: Dict[str, Any]) -> bool:
        """Check if node matches filters."""
        if "id_filter" in filters and str(node_id) != str(filters["id_filter"]):
            return False

        # Check entity_type filter
        if "entity_type" in filters:
            entity_type = filters["entity_type"]
            node_entity_type = data.get("entity_type")
            
            # Handle multiple entity types (list)
            if isinstance(entity_type, list):
                clean_node = (node_entity_type or "").strip('"').strip("'")
                if not any(clean_node == et.strip('"').strip("'") for et in entity_type):
                    return False
            else:
                # Handle single entity type — compare with and without surrounding quotes
                clean_filter = entity_type.strip('"').strip("'")
                clean_node = (node_entity_type or "").strip('"').strip("'")
                if clean_node != clean_filter:
                    return False
        
        # Check relationship_name filter (for nodes, this might be in data)
        if "relationship_name" in filters:
            relationship_name = filters["relationship_name"]
            node_relationship_name = data.get("relationship_name")
            if node_relationship_name == f'"{relationship_name}"':
                pass  # Match found with quotes
            elif node_relationship_name == relationship_name:
                pass  # Match found without quotes
            else:
                return False  # No match found
        
        # Check description contains filter
        if "description_contains" in filters:
            description = data.get("description", "")
            description_filters = filters["description_contains"]
            if isinstance(description_filters, str):
                description_filters = [description_filters]
            if not any(
                str(term).lower() in description.lower()
                for term in description_filters
            ):
                return False
        
        # Check raw criteria (bulletproof keyword matching)
        if "raw_criteria" in filters:
            criteria = filters["raw_criteria"].lower()
            node_text = f"{node_id} {str(data)}".lower()
            
            raw_entity_types = self._entity_types_from_raw_criteria(criteria)
            if raw_entity_types:
                clean_node = str(data.get("entity_type") or "").strip('"').strip("'").lower()
                if clean_node not in raw_entity_types:
                    return False
            elif not self._has_structured_filter(
                filters,
                {"id_filter", "entity_type", "relationship_name", "description_contains"},
            ):
                if criteria not in node_text:
                    return False
        
        return True

    @staticmethod
    def _entity_types_from_raw_criteria(criteria: str) -> Set[str]:
        entity_list_match = re.search(
            r"(?:entity_type|label)\s+in\s*\[([^\]]+)\]", criteria, re.IGNORECASE
        )
        if entity_list_match:
            return {
                match.group(1).strip().lower()
                for match in re.finditer(
                    r"['\"]?([a-z0-9_]+)['\"]?",
                    entity_list_match.group(1),
                    re.IGNORECASE,
                )
            }

        patterns = [
            r"(?:entity_type|label)\s*[=:]\s*['\"]?([a-z0-9_|]+)['\"]?",
            r"(?:entity_type|label)\s+['\"]?([a-z0-9_|]+)['\"]?",
        ]
        for pattern in patterns:
            match = re.search(pattern, criteria, re.IGNORECASE)
            if match:
                return {
                    entity_type.strip().lower()
                    for entity_type in match.group(1).replace("|", ",").split(",")
                    if entity_type.strip()
                }
        return set()
    
    def _edge_matches_filters(self, source: Any, target: Any, data: Dict[str, Any], filters: Dict[str, Any]) -> bool:
        """Check if edge matches filters."""
        # Check relationship_name filter (check both relationship_name and relation_type)
        if "relationship_name" in filters:
            relationship_name = filters["relationship_name"]
            edge_relationship_name = data.get("relationship_name") or data.get("relation_type")
            clean_edge = str(edge_relationship_name or "").strip('"').strip("'").lower()
            clean_filter = str(relationship_name).strip('"').strip("'").lower()
            if clean_edge != clean_filter:
                return False  # No match found

        if "relation_type" in filters:
            edge_relation_type = data.get("relation_type") or data.get("relationship_name")
            clean_edge = str(edge_relation_type or "").strip('"').strip("'").lower()
            clean_filter = str(filters["relation_type"]).strip('"').strip("'").lower()
            if clean_edge != clean_filter:
                return False

        # Check source filter
        if "source" in filters:
            if source != filters["source"]:
                return False

        # Check target filter
        if "target" in filters:
            if target != filters["target"]:
                return False

        # Check description contains filter
        if "description_contains" in filters:
            description = data.get("description", "")
            description_filters = filters["description_contains"]
            if isinstance(description_filters, str):
                description_filters = [description_filters]
            if not any(
                str(term).lower() in description.lower()
                for term in description_filters
            ):
                return False

        # Check raw criteria
        if "raw_criteria" in filters:
            criteria = filters["raw_criteria"].lower()
            edge_text = f"{source} {target} {str(data)}".lower()
            if (
                not self._has_structured_filter(
                    filters,
                    {
                        "source",
                        "target",
                        "relationship_name",
                        "relation_type",
                        "description_contains",
                    },
                )
                and criteria not in edge_text
            ):
                return False

        return True

    @staticmethod
    def _has_structured_filter(filters: Dict[str, Any], keys: Set[str]) -> bool:
        return any(key in filters for key in keys)
    
    def _get_nodes_by_filter(self, filters: Dict[str, Any]) -> List[Any]:
        """Get nodes matching specific filters."""
        nodes = []
        for node_id, data in self.graph.nodes(data=True):
            if self._node_matches_filters(node_id, data, filters):
                nodes.append(node_id)
        return nodes
    
    def _get_node_labels(self) -> List[str]:
        """Get available node labels (entity types)."""
        labels = set()
        for _, data in self.graph.nodes(data=True):
            # Try direct entity_type first
            entity_type = data.get("entity_type")
            if not entity_type and "data" in data:
                # Try nested data structure
                entity_type = data.get("data", {}).get("entity_type")
            if entity_type:
                # Remove quotes if present
                clean_type = entity_type.strip('"')
                labels.add(clean_type)
        return list(labels)
    
    def _get_edge_types(self) -> List[str]:
        """Get available edge types (relationship names)."""
        types = set()
        for _, _, data in self.graph.edges(data=True):
            relationship_name = data.get("relationship_name") or data.get("relation_type")
            if relationship_name:
                clean_type = str(relationship_name).strip('"').strip("'")
                types.add(clean_type)
        return list(types)
    
    def _get_node_properties(self) -> List[str]:
        """Get available node properties."""
        properties = set()
        for _, data in self.graph.nodes(data=True):
            properties.update(data.keys())
        return list(properties)
    
    def _get_edge_properties(self) -> List[str]:
        """Get available edge properties."""
        properties = set()
        for _, _, data in self.graph.edges(data=True):
            properties.update(data.keys())
        return list(properties)
