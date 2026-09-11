"""
Neo4j adapter for GASL system.
"""

from typing import Any, Callable, Dict, List, Optional
from .base import (
    BOUND_KIND_PATH_EMIT_BOUND,
    BOUND_KIND_TRANSPORT_WINDOW,
    EDGE_SURFACE,
    NODE_SURFACE,
    PATH_SURFACE,
    GraphAdapter,
    complete_result,
    completeness,
)
from ..types import AdapterCapabilities
from ..errors import AdapterError


class Neo4jAdapter(GraphAdapter):
    """Neo4j implementation of GraphAdapter."""

    # Declared against what the Cypher builders below actually put in a WHERE
    # clause. Keys this adapter cannot translate are refused rather than dropped,
    # so a capability gap surfaces as an error instead of as a silently
    # unfiltered result set.
    #
    # PROVISIONAL: this declaration describes how complete the builders are
    # today, not a permanent limit on what Neo4j can express. Node and edge
    # identity filters below use `id(n)`, which is the identity this adapter's
    # own find_nodes/find_edges emit (`record["n"].id`), so the round-trip is
    # self-consistent. Widen this set as builders are written; never narrow it to
    # make a caller pass.
    #
    # NOTHING IN THIS CLASS HAS EVER BEEN EXECUTED.
    #
    # There is no Neo4j instance in this environment, no recorded run against
    # this backend, and — since the suite was removed — no fake-driver coverage
    # either. Every line below is verified by reading and by nothing else. The
    # first time a real Neo4j runs this code will be the first time it runs at
    # all, and that includes:
    #
    #   - the Cypher the builders emit, including the ORDER BY clauses added so
    #     that SKIP/LIMIT pages partition a result set instead of resampling an
    #     unstable one;
    #   - the `_run_paged` loop, its `LIMIT window + 1` sentinel, and its
    #     short-page termination;
    #   - the completeness disclosure those paths produce, which asserts to
    #     every downstream consumer that a result is complete.
    #
    # That last one is the sharpest: an unverified path here does not merely
    # return wrong rows, it returns wrong rows carrying a positive claim that
    # nothing was left out.
    #
    # This note previously said "NOT EXERCISED BY THE TEST SUITE" and described
    # the paging as unit-tested against a fake driver. Both halves are now
    # false — the suite is gone — and a stale reassurance is worse than none.
    # An unverified path and a verified one must not read the same in the
    # source, so this says plainly which one this is.
    #
    # Noted, and explicitly not a change request: if the paging ever misbehaves
    # against a real instance, the simpler shape is `LIMIT window + 1` with a
    # refusal on the sentinel row rather than a re-fetch at `SKIP += window`.
    ENFORCED_FILTER_KEYS = {
        NODE_SURFACE: frozenset(
            {"id_filter", "entity_type", "description_contains", "raw_criteria"}
        ),
        EDGE_SURFACE: frozenset(
            {"source", "target", "relationship_name", "relation_type",
             "description_contains", "raw_criteria"}
        ),
        PATH_SURFACE: frozenset({"source_filter", "target_filter", "relation_type"}),
    }

    # Rows fetched per round trip. NO MEASUREMENT JUSTIFIES THIS NUMBER — there
    # is no Neo4j in this environment to measure against, and none is cited
    # anywhere in the tree. It is carried over from the old `max_results=1000`
    # so the per-round-trip payload stays what operators have been running with.
    #
    # The difference from the constant it replaces is what makes shipping it
    # without a citation acceptable: this value cannot change the answer. It is
    # a page size inside a loop that keeps paging until the server returns a
    # short page, so raising or lowering it changes only the number of round
    # trips. The old constant chose *which rows existed*.
    DEFAULT_TRANSPORT_WINDOW = 1000

    @staticmethod
    def _literal(value: Any) -> str:
        """Quote a value for inline Cypher, escaping embedded quotes."""
        return "'" + str(value).replace("\\", "\\\\").replace("'", "\\'") + "'"


    def _get_capabilities(self) -> AdapterCapabilities:
        """Get Neo4j adapter capabilities."""
        return AdapterCapabilities(
            supports_path_finding=True,
            supports_cypher=True,
            supports_networkx=False,
            max_path_length=10,
            # Path generation happens server-side inside a variable-length
            # MATCH; this adapter never walks the |sources| x |targets| product
            # itself, so it has no client-side work budget to declare.
            path_source_budget=None,
            # Not declared: this adapter has never been exercised against a
            # live Neo4j, so any seed budget here would be an uncited guess
            # about a backend nobody has measured.
            walk_seed_budget=None,
            transport_window=self.DEFAULT_TRANSPORT_WINDOW,
            supported_node_properties=self._get_node_properties(),
            supported_edge_properties=self._get_edge_properties()
        )

    def _run_paged(
        self,
        build_query: Callable[[int, Optional[int]], str],
        *,
        emit_bound: Optional[int] = None,
    ) -> tuple[List[Any], Dict[str, Any]]:
        """Fetch every record for a query, one transport window at a time.

        `build_query(skip, limit)` renders the Cypher for one page; `limit` is
        None when no window applies and the whole result set is asked for in one
        round trip.

        Each page is requested with `LIMIT window + 1`. The extra row is a
        sentinel: if it comes back, there is at least one more row after this
        page, and if it does not, this page is the last one. That distinction is
        therefore free — no second round trip is needed to discover the end of
        the result set, and no page boundary is ever mistaken for exhaustion.
        The sentinel row itself is not consumed here; the next page re-fetches it
        at `SKIP += window`.

        Returns the accumulated records and the completeness disclosure. The
        window is transport, not a result bound: absent a caller-supplied
        `emit_bound`, every matching row is delivered, and the disclosure says
        so positively while still naming the window that was in play.
        """
        window = self.capabilities.transport_window
        if not window or window <= 0:
            records = list(self.graph.run(build_query(0, None)))
            if emit_bound and len(records) > emit_bound:
                return records[:emit_bound], completeness(
                    complete=False,
                    returned=emit_bound,
                    bound=emit_bound,
                    bound_kind=BOUND_KIND_PATH_EMIT_BOUND,
                    residual_known=True,
                    residual=len(records) - emit_bound,
                )
            return records, complete_result(len(records))

        accumulated: List[Any] = []
        skip = 0
        pages = 0
        while True:
            page = list(self.graph.run(build_query(skip, window + 1)))
            pages += 1
            accumulated.extend(page[:window])
            if emit_bound and len(accumulated) >= emit_bound:
                # A caller-supplied probe size stopped the fetch. How many rows
                # remain on the server was never counted, so it is unknown
                # rather than zero.
                return accumulated[:emit_bound], completeness(
                    complete=False,
                    returned=emit_bound,
                    bound=emit_bound,
                    bound_kind=BOUND_KIND_PATH_EMIT_BOUND,
                    residual_known=False,
                    residual=None,
                    transport_window=window,
                    pages_fetched=pages,
                )
            if len(page) <= window:
                # Short page (sentinel absent): the result set is exhausted.
                return accumulated, completeness(
                    complete=True,
                    returned=len(accumulated),
                    bound=window,
                    bound_kind=BOUND_KIND_TRANSPORT_WINDOW,
                    residual_known=True,
                    residual=0,
                    transport_window=window,
                    pages_fetched=pages,
                )
            skip += window


    def find_nodes(self, filters: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Find nodes matching filters using Cypher."""
        filters = self._validate_filters(filters, NODE_SURFACE, "find_nodes")
        try:
            records, disclosure = self._run_paged(
                lambda skip, limit: self._build_node_query(filters, skip, limit)
            )

            nodes = []
            for record in records:
                node_info = {
                    "id": record["n"].id,
                    "data": dict(record["n"]),
                    "type": "node"
                }
                nodes.append(node_info)

            # The post-fetch slice that used to sit here was unreachable by
            # construction: the generated Cypher already carried a terminal
            # LIMIT equal to the same constant, so `len(nodes) > max_results`
            # could never be true. Dead code shaped like a safety net is worse
            # than no net — it advertises a guarantee nothing was providing.
            self._disclose(disclosure)
            return nodes

        except Exception as e:
            raise AdapterError(f"Failed to find nodes: {e}", "neo4j", "find_nodes")
    
    def find_edges(self, filters: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Find edges matching filters using Cypher."""
        filters = self._validate_filters(filters, EDGE_SURFACE, "find_edges")
        try:
            records, disclosure = self._run_paged(
                lambda skip, limit: self._build_edge_query(filters, skip, limit)
            )

            edges = []
            for record in records:
                edge_info = {
                    "source": record["s"].id,
                    "target": record["e"].id,
                    "data": dict(record["r"]),
                    "type": "edge"
                }
                edges.append(edge_info)

            # Same unreachable post-fetch slice as find_nodes; same deletion.
            self._disclose(disclosure)
            return edges

        except Exception as e:
            raise AdapterError(f"Failed to find edges: {e}", "neo4j", "find_edges")
    
    def find_paths(self, filters: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Find paths matching filters using Cypher."""
        filters = self._validate_filters(filters, PATH_SURFACE, "find_paths")
        try:
            # `_max_results` is a caller-supplied probe size and nothing else.
            # It has no default: absent one, every matching path is delivered,
            # paged over the transport window like any other result set.
            emit_bound = int(filters.get("_max_results") or 0) or None
            records, disclosure = self._run_paged(
                lambda skip, limit: self._build_path_query(filters, skip, limit),
                emit_bound=emit_bound,
            )

            paths = []
            for record in records:
                path_info = {
                    "source": record["p"].start_node.id,
                    "target": record["p"].end_node.id,
                    "path": [node.id for node in record["p"].nodes],
                    "length": len(record["p"].relationships),
                    "type": "path",
                    "edge_types": [rel.type for rel in record["p"].relationships],
                    "source_entity_type": str(record["p"].start_node.get("entity_type") or "").strip('"').strip("'"),
                    "target_entity_type": str(record["p"].end_node.get("entity_type") or "").strip('"').strip("'"),
                }
                paths.append(path_info)

            # Same unreachable post-fetch slice as find_nodes/find_edges; the
            # generated Cypher already carried the LIMIT. Deleted.
            self._disclose(disclosure)
            return paths

        except Exception as e:
            raise AdapterError(f"Failed to find paths: {e}", "neo4j", "find_paths")
    
    @staticmethod
    def _page_clause(skip: int, limit: Optional[int]) -> str:
        """Render the paging tail for one page of a query.

        `limit` of None means "no window" and produces no tail at all, so the
        query returns its whole result set. A terminal LIMIT with no SKIP after
        it is what made the old queries silently answer a smaller question than
        the caller asked; the tail here is always part of a loop that keeps
        advancing SKIP until the server runs out of rows.
        """
        if limit is None:
            return "" if skip <= 0 else f" SKIP {int(skip)}"
        return f" SKIP {int(skip)} LIMIT {int(limit)}"

    def _build_node_query(
        self, filters: Dict[str, Any], skip: int = 0, limit: Optional[int] = None
    ) -> str:
        """Build Cypher query for finding nodes."""
        query = "MATCH (n)"
        conditions = []

        # Node identity, matching the identity find_nodes emits (`record["n"].id`).
        if "id_filter" in filters:
            conditions.append(f"id(n) = {int(filters['id_filter'])}")

        # Add entity_type filter
        if "entity_type" in filters:
            entity_type = filters["entity_type"]
            if isinstance(entity_type, (list, tuple, set)):
                joined = ", ".join(self._literal(value) for value in entity_type)
                conditions.append(f"n.entity_type IN [{joined}]")
            else:
                conditions.append(f"n.entity_type = {self._literal(entity_type)}")

        # Add description filter
        if "description_contains" in filters:
            description = filters["description_contains"]
            terms = description if isinstance(description, (list, tuple)) else [description]
            clause = " OR ".join(
                f"n.description CONTAINS {self._literal(term)}" for term in terms
            )
            conditions.append(f"({clause})")

        # Add raw criteria (simple property matching)
        if "raw_criteria" in filters:
            criteria = filters["raw_criteria"]
            # Simple keyword matching in description
            conditions.append(f"n.description CONTAINS {self._literal(criteria)}")

        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        
        # Deterministic ordering. SKIP/LIMIT paging over a query with no ORDER BY
        # is only as stable as the server's incidental row order, and an
        # unstable order across pages both duplicates and drops rows. Ordering
        # by the identity this adapter already emits (`record["n"].id`) makes the
        # pages a genuine partition.
        query += " RETURN n ORDER BY id(n)" + self._page_clause(skip, limit)

        return query

    def _build_edge_query(
        self, filters: Dict[str, Any], skip: int = 0, limit: Optional[int] = None
    ) -> str:
        """Build Cypher query for finding edges."""
        query = "MATCH (s)-[r]->(e)"
        conditions = []

        # Endpoint identity, matching what find_edges emits (`record["s"].id`).
        # Without these, SUBGRAPH / GRAPHPATTERN / GRAPHCONNECT cannot express an
        # incidence query at all on this backend.
        if "source" in filters:
            conditions.append(f"id(s) = {int(filters['source'])}")
        if "target" in filters:
            conditions.append(f"id(e) = {int(filters['target'])}")

        # Add relationship_name filter
        if "relationship_name" in filters:
            relationship_name = str(filters["relationship_name"]).strip('"').strip("'")
            conditions.append(
                f"(r.relationship_name = {self._literal(relationship_name)} "
                f"OR type(r) = {self._literal(relationship_name)})"
            )

        # Relation type may be encoded as a property or as the Cypher edge type;
        # accept either, the way the NetworkX adapter reads both spellings.
        if "relation_type" in filters:
            relation_type = str(filters["relation_type"]).strip('"').strip("'")
            conditions.append(
                f"(r.relation_type = {self._literal(relation_type)} "
                f"OR type(r) = {self._literal(relation_type)})"
            )

        # Add description filter
        if "description_contains" in filters:
            description = filters["description_contains"]
            terms = description if isinstance(description, (list, tuple)) else [description]
            clause = " OR ".join(
                f"r.description CONTAINS {self._literal(term)}" for term in terms
            )
            conditions.append(f"({clause})")

        # The parser sets raw_criteria on essentially every FIND, so an edge query
        # that cannot express it is an edge query that never runs.
        if "raw_criteria" in filters:
            conditions.append(
                f"r.description CONTAINS {self._literal(filters['raw_criteria'])}"
            )

        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        
        # Ordered for the same reason as the node query above: pages must
        # partition the result set, not resample an unstable order.
        query += " RETURN s, r, e ORDER BY id(r)" + self._page_clause(skip, limit)

        return query

    def _build_path_query(
        self, filters: Dict[str, Any], skip: int = 0, limit: Optional[int] = None
    ) -> str:
        """Build Cypher query for finding paths."""
        max_length = self.capabilities.max_path_length
        relation_type = filters.get("relation_type")
        relation_clause = f":{relation_type}" if relation_type else ""
        query = f"MATCH p = (start)-[*1..{max_length}{relation_clause}]->(end)"
        conditions = []
        
        # Add source filter
        if "source_filter" in filters:
            source_filter = filters["source_filter"]
            if "entity_type" in source_filter:
                entity_type = source_filter["entity_type"]
                conditions.append(f"start.entity_type = '{entity_type}'")
        
        # Add target filter
        if "target_filter" in filters:
            target_filter = filters["target_filter"]
            if "entity_type" in target_filter:
                entity_type = target_filter["entity_type"]
                conditions.append(f"end.entity_type = '{entity_type}'")
        
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        
        # No emit bound is rendered into the Cypher. A caller-supplied probe
        # size is applied by the paging loop, which can then disclose that it
        # fired; baked into the query it would be indistinguishable from the
        # result set genuinely ending here.
        query += " RETURN p ORDER BY length(p), id(startNode(p)), id(endNode(p))"
        query += self._page_clause(skip, limit)

        return query
    
    def _get_node_labels(self) -> List[str]:
        """Get available node labels."""
        try:
            result = self.graph.run("CALL db.labels()")
            return [record["label"] for record in result]
        except Exception:
            return []
    
    def _get_edge_types(self) -> List[str]:
        """Get available edge types."""
        try:
            result = self.graph.run("CALL db.relationshipTypes()")
            return [record["relationshipType"] for record in result]
        except Exception:
            return []
    
    def _get_node_properties(self) -> List[str]:
        """Get available node properties."""
        try:
            result = self.graph.run("CALL db.propertyKeys()")
            return [record["propertyKey"] for record in result]
        except Exception:
            return []
    
    def _get_edge_properties(self) -> List[str]:
        """Get available edge properties."""
        # For Neo4j, edge properties are the same as node properties
        return self._get_node_properties()
