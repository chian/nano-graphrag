"""
Curated demo scenarios that highlight where GASL outperforms plain RAG.

Each scenario is grounded in a concrete graph pattern so the demo copy,
replay trace, and answer text can be generated from the actual graph.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List

import networkx as nx


REPO_ROOT = Path(__file__).resolve().parents[1]


def _repo_path(*parts: str) -> Path:
    return REPO_ROOT.joinpath(*parts)


@lru_cache(maxsize=None)
def _read_graph(path: str) -> nx.Graph:
    return nx.read_graphml(path)


def _filter_existing_nodes(graph: nx.Graph, node_ids: Iterable[str]) -> List[str]:
    return [node_id for node_id in node_ids if node_id in graph]


def _event(delay_ms: int, event: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "delay_ms": delay_ms,
        "event": event,
        "payload": payload,
    }


def _domain_frequency_demo() -> Dict[str, Any]:
    viz_path = _repo_path(
        "haiqu_graphs", "v1", "haiqu_cognitive_impact",
        "haiqu_cognitive_impact_graph_deg10.graphml",
    )
    full_path = _repo_path(
        "haiqu_graphs", "v1", "haiqu_cognitive_impact",
        "haiqu_cognitive_impact_graph.graphml",
    )
    G = _read_graph(str(full_path))
    viz = _read_graph(str(viz_path))

    counts: Counter[str] = Counter()
    examples: defaultdict[str, List[str]] = defaultdict(list)
    for src, dst, data in G.edges(data=True):
        if data.get("relation_type") != "AFFECTS":
            continue
        if G.nodes[src].get("entity_type") != "RESPIRATORY_INFECTION":
            continue
        if G.nodes[dst].get("entity_type") != "COGNITIVE_DOMAIN":
            continue
        counts[dst] += 1
        if len(examples[dst]) < 3:
            examples[dst].append(src)

    top = counts.most_common(5)
    domain_nodes = [name for name, _ in top]
    infection_nodes: List[str] = []
    for name, _count in top:
        infection_nodes.extend(examples[name])
    infection_nodes = list(dict.fromkeys(infection_nodes))[:5]

    viz_domain_nodes = _filter_existing_nodes(viz, domain_nodes)
    viz_infection_nodes = _filter_existing_nodes(viz, infection_nodes)
    total_edges = sum(counts.values())

    top_line = ", ".join(f"{name} ({count})" for name, count in top[:3])
    answer = (
        "Across respiratory-infection findings in the cognitive-impact graph, the "
        f"most connected cognitive domains are {top_line}. GASL wins here because "
        f"it can traverse all {total_edges} AFFECTS edges and aggregate over "
        f"{len(counts)} distinct domains instead of relying on a 15-node retrieval window."
    )

    replay = [
        _event(250, "gasl_step", {
            "command_type": "INIT",
            "status": "running",
            "command": "Starting GASL traversal...",
        }),
        _event(650, "gasl_step", {
            "command_type": "FIND",
            "status": "running",
            "command": "FIND nodes with entity_type='RESPIRATORY_INFECTION' AS infections",
        }),
        _event(750, "gasl_highlight", {
            "nodes": viz_infection_nodes,
            "edges": [],
            "command_type": "FIND",
            "status": "success",
        }),
        _event(700, "gasl_step", {
            "command_type": "GRAPHWALK",
            "status": "running",
            "command": "GRAPHWALK from infections follow AFFECTS depth 1",
        }),
        _event(800, "gasl_highlight", {
            "nodes": viz_domain_nodes,
            "edges": [],
            "command_type": "GRAPHWALK",
            "status": "success",
        }),
        _event(550, "gasl_step", {
            "command_type": "AGGREGATE",
            "status": "running",
            "command": "AGGREGATE affected_domains by id with count",
        }),
        _event(600, "query_complete", {
            "answer": answer,
            "nodes": list(dict.fromkeys(viz_infection_nodes + viz_domain_nodes)),
            "edges": [],
            "iterations": 4,
            "query_answered": True,
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "calls": 0},
        }),
    ]

    return {
        "id": "cognitive-domain-frequency",
        "title": "Rank Affected Cognitive Domains",
        "graph_path": str(viz_path),
        "full_graph_path": str(full_path),
        "question": "Across the cognitive-impact graph, which cognitive domains are most frequently affected by respiratory infection findings?",
        "why_gasl_wins": "The answer depends on traversing every respiratory-infection -> AFFECTS -> cognitive-domain edge and tallying the full graph-wide frequency distribution.",
        "rag_blind_spot": "Top-k retrieval can surface relevant domains, but it cannot guarantee graph-wide counts or coverage across the full evidence set.",
        "metrics": {
            "graph_edges_traversed": total_edges,
            "distinct_domains": len(counts),
            "rag_window": 15,
        },
        "replay": replay,
    }


def _confounder_span_demo() -> Dict[str, Any]:
    viz_path = _repo_path(
        "haiqu_graphs", "v1", "haiqu_cognitive_impact",
        "haiqu_cognitive_impact_graph_deg10.graphml",
    )
    full_path = _repo_path(
        "haiqu_graphs", "v1", "haiqu_cognitive_impact",
        "haiqu_cognitive_impact_graph.graphml",
    )
    G = _read_graph(str(full_path))
    viz = _read_graph(str(viz_path))

    rows: List[Dict[str, Any]] = []
    for conf in [n for n, d in G.nodes(data=True) if d.get("entity_type") == "CONFOUNDING_FACTOR"]:
        domains = set()
        times = set()
        for src, _dst, data in G.in_edges(conf, data=True):
            if data.get("relation_type") == "CONFOUNDED_BY" and G.nodes[src].get("entity_type") == "COGNITIVE_DOMAIN":
                domains.add(src)
        for _src, dst, data in G.out_edges(conf, data=True):
            if data.get("relation_type") == "OBSERVED_AT" and G.nodes[dst].get("entity_type") == "FOLLOW_UP_TIMEPOINT":
                times.add(dst)
        if domains and times:
            rows.append({
                "node": conf,
                "domain_count": len(domains),
                "time_count": len(times),
                "score": len(domains) * len(times),
                "sample_domains": sorted(domains)[:2],
                "sample_times": sorted(times)[:2],
            })

    rows.sort(key=lambda item: (-item["score"], -item["domain_count"], -item["time_count"], item["node"]))
    top = rows[:4]

    conf_nodes = _filter_existing_nodes(viz, [row["node"] for row in top])
    sample_nodes = []
    for row in top[:2]:
        sample_nodes.extend(row["sample_domains"])
        sample_nodes.extend(row["sample_times"])
    sample_nodes = _filter_existing_nodes(viz, sample_nodes)

    top_line = ", ".join(
        f"{row['node']} ({row['domain_count']} domains x {row['time_count']} timepoints)"
        for row in top[:3]
    )
    answer = (
        "The confounders spanning the broadest cross-section of the cognitive-impact graph are "
        f"{top_line}. GASL can traverse both CONFOUNDED_BY and OBSERVED_AT relationships and "
        "combine the results; plain retrieval does not naturally compose those two axes."
    )

    replay = [
        _event(250, "gasl_step", {
            "command_type": "INIT",
            "status": "running",
            "command": "Starting GASL traversal...",
        }),
        _event(600, "gasl_step", {
            "command_type": "FIND",
            "status": "running",
            "command": "FIND nodes with entity_type='CONFOUNDING_FACTOR' AS confounders",
        }),
        _event(700, "gasl_highlight", {
            "nodes": conf_nodes,
            "edges": [],
            "command_type": "FIND",
            "status": "success",
        }),
        _event(700, "gasl_step", {
            "command_type": "GRAPHWALK",
            "status": "running",
            "command": "GRAPHWALK from confounders follow CONFOUNDED_BY, OBSERVED_AT depth 1",
        }),
        _event(800, "gasl_highlight", {
            "nodes": sample_nodes,
            "edges": [],
            "command_type": "GRAPHWALK",
            "status": "success",
        }),
        _event(650, "gasl_step", {
            "command_type": "PROCESS",
            "status": "running",
            "command": "PROCESS confounders with rank by breadth across domains and timepoints",
        }),
        _event(600, "query_complete", {
            "answer": answer,
            "nodes": list(dict.fromkeys(conf_nodes + sample_nodes)),
            "edges": [],
            "iterations": 4,
            "query_answered": True,
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "calls": 0},
        }),
    ]

    return {
        "id": "confounder-breadth",
        "title": "Find Broad Cross-Cutting Confounders",
        "graph_path": str(viz_path),
        "full_graph_path": str(full_path),
        "question": "Which confounding factors span the widest range of cognitive domains and follow-up windows?",
        "why_gasl_wins": "The query is intrinsically two-dimensional: breadth across domains and breadth across follow-up windows. GASL can walk both relation families and compose them.",
        "rag_blind_spot": "Similarity retrieval is good at surfacing a few confounder mentions, but it does not compute breadth across two relation sets.",
        "metrics": {
            "candidate_confounders": len(rows),
            "top_score": top[0]["score"] if top else 0,
            "rag_window": 15,
        },
        "replay": replay,
    }


def _control_breadth_demo() -> Dict[str, Any]:
    graph_path = _repo_path(
        "haiqu_graphs", "v1", "haiqu_engineering_controls",
        "haiqu_engineering_controls_graph.graphml",
    )
    G = _read_graph(str(graph_path))

    rows = []
    for control in [n for n, d in G.nodes(data=True) if d.get("entity_type") == "ENGINEERING_CONTROL"]:
        zones = set()
        studies = set()
        reductions = 0
        for _src, dst, data in G.out_edges(control, data=True):
            rel = data.get("relation_type")
            dst_type = G.nodes[dst].get("entity_type")
            if rel == "APPLIED_TO" and dst_type == "HOSPITAL_ZONE":
                zones.add(dst)
            if rel == "VALIDATED_BY" and dst_type == "VALIDATION_STUDY":
                studies.add(dst)
            if rel == "REDUCES" and dst_type == "EFFECTIVENESS_MEASURE":
                reductions += 1
        if zones or studies:
            rows.append({
                "node": control,
                "zones": len(zones),
                "studies": len(studies),
                "reductions": reductions,
                "sample_zones": sorted(zones)[:2],
            })
    rows.sort(key=lambda item: (-item["zones"], -item["studies"], -item["reductions"], item["node"]))
    top = rows[:5]

    control_nodes = [row["node"] for row in top[:4]]
    zone_nodes = []
    for row in top[:2]:
        zone_nodes.extend(row["sample_zones"])

    top_line = ", ".join(
        f"{row['node']} ({row['zones']} zones, {row['studies']} studies)"
        for row in top[:3]
    )
    answer = (
        "Across the engineering-controls graph, the broadest evidence footprints belong to "
        f"{top_line}. GASL is a better fit because the claim depends on aggregating both "
        "unique hospital zones and unique validation studies per control."
    )

    replay = [
        _event(250, "gasl_step", {
            "command_type": "INIT",
            "status": "running",
            "command": "Starting GASL traversal...",
        }),
        _event(650, "gasl_step", {
            "command_type": "FIND",
            "status": "running",
            "command": "FIND nodes with entity_type='ENGINEERING_CONTROL' AS controls",
        }),
        _event(800, "gasl_highlight", {
            "nodes": control_nodes,
            "edges": [],
            "command_type": "FIND",
            "status": "success",
        }),
        _event(700, "gasl_step", {
            "command_type": "GRAPHWALK",
            "status": "running",
            "command": "GRAPHWALK from controls follow APPLIED_TO, VALIDATED_BY depth 1",
        }),
        _event(800, "gasl_highlight", {
            "nodes": zone_nodes,
            "edges": [],
            "command_type": "GRAPHWALK",
            "status": "success",
        }),
        _event(650, "gasl_step", {
            "command_type": "AGGREGATE",
            "status": "running",
            "command": "AGGREGATE controls by id with count",
        }),
        _event(600, "query_complete", {
            "answer": answer,
            "nodes": list(dict.fromkeys(control_nodes + zone_nodes)),
            "edges": [],
            "iterations": 4,
            "query_answered": True,
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "calls": 0},
        }),
    ]

    return {
        "id": "engineering-control-breadth",
        "title": "Compare Controls by Evidence Breadth",
        "graph_path": str(graph_path),
        "full_graph_path": str(graph_path),
        "question": "Which engineering controls are validated across the widest range of hospital zones, and by how many validation studies?",
        "why_gasl_wins": "The answer requires grouped counts over two relationship families per control: APPLIED_TO hospital zones and VALIDATED_BY studies.",
        "rag_blind_spot": "Top-k retrieval can surface strong controls, but it will not guarantee global breadth counts across every control node.",
        "metrics": {
            "controls_considered": len(rows),
            "top_zone_count": top[0]["zones"] if top else 0,
            "rag_window": 15,
        },
        "replay": replay,
    }


@lru_cache(maxsize=1)
def get_demo_catalog() -> List[Dict[str, Any]]:
    return [
        _domain_frequency_demo(),
        _confounder_span_demo(),
        _control_breadth_demo(),
    ]


def get_demo(demo_id: str) -> Dict[str, Any] | None:
    for demo in get_demo_catalog():
        if demo["id"] == demo_id:
            return demo
    return None
