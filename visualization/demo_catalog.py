"""
Curated demo scenarios that highlight where GASL outperforms plain RAG.

Each scenario is grounded in a concrete graph pattern so the demo copy,
replay trace, and answer text can be generated from the actual graph.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from functools import lru_cache
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List

import networkx as nx


REPO_ROOT = Path(__file__).resolve().parents[1]
DEMO_SHORTLIST_12 = [
    "q003", "q004", "q005", "q008", "q009", "q010",
    "q012", "q013", "q014", "q019", "q022", "q026",
]
DEMO_VIDEO_SHAREABLE_14 = [
    "q001",
    *DEMO_SHORTLIST_12,
    "q007",
]


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


def _scale_replay_delays(replay: list[dict[str, Any]], factor: float) -> list[dict[str, Any]]:
    scaled: list[dict[str, Any]] = []
    for step in replay:
        scaled.append({
            **step,
            "delay_ms": max(140, int(round(step["delay_ms"] * factor))),
        })
    return scaled


def _engineering_demo_paths() -> tuple[Path, Path]:
    return (
        _repo_path(".viz_cache", "graphs", "haiqu_engineering_controls_topdeg1500.graphml"),
        _repo_path("haiqu_graphs", "v1", "haiqu_engineering_controls", "haiqu_engineering_controls_graph.graphml"),
    )


def _graph_paths(graph_name: str) -> tuple[Path, Path]:
    if graph_name == "haiqu_engineering_controls":
        return _engineering_demo_paths()
    full = _repo_path("haiqu_graphs", "v1", graph_name, f"{graph_name}_graph.graphml")
    return (full, full)


def _load_trace_demo_payload(run_id: str, qid: str) -> dict[str, Any]:
    trace_path = _repo_path("benchmark_results", run_id, qid, "gasl_artifacts", "traces", f"{qid}.jsonl")
    answer_views = None
    final_answer = None
    question = None
    for line in trace_path.open(encoding="utf-8"):
        row = json.loads(line)
        if row["event"] == "answer_views":
            answer_views = row["payload"]
            question = answer_views.get("query")
        if row["event"] == "final_analysis_response":
            final_answer = row["payload"]["response"]
    if not answer_views or not final_answer:
        raise ValueError(f"Missing answer view or final answer for {qid} in {run_id}")
    return {"question": question, "answer_views": answer_views, "final_answer": final_answer}


def _lookup_selected_view(answer_views_payload: dict[str, Any]) -> dict[str, Any]:
    selection = answer_views_payload.get("selection") or {}
    selected_id = selection.get("view_id")
    for view in answer_views_payload.get("views", []):
        if view.get("view_id") == selected_id:
            return view
    raise ValueError(f"Selected view {selected_id!r} not found")


def _lookup_first_view(answer_views_payload: dict[str, Any], kind: str) -> dict[str, Any] | None:
    for view in answer_views_payload.get("views", []):
        if view.get("kind") == kind and view.get("payload"):
            return view
    return None


def _partial_ranking_payload(payload: dict[str, Any], limit: int) -> dict[str, Any]:
    return {
        **payload,
        "ranked_subjects": list(payload.get("ranked_subjects", [])[:limit]),
    }


def _partial_grouped_payload(payload: dict[str, Any], limit: int) -> dict[str, Any]:
    return {
        **payload,
        "rows": list(payload.get("rows", [])[:limit]),
    }


def _partial_distribution_payload(payload: dict[str, Any], bin_limit: int) -> dict[str, Any]:
    return {
        **payload,
        "histogram": list(payload.get("histogram", [])[:bin_limit]),
    }


def _neighbor_wave(
    graph: nx.Graph,
    seed: str,
    *,
    max_neighbors: int = 8,
    extra_nodes: Iterable[str] = (),
) -> tuple[list[str], list[list[str]]]:
    if seed not in graph:
        return [], []
    neighbors = list(graph.neighbors(seed))[:max_neighbors]
    nodes = list(dict.fromkeys([seed, *neighbors, *extra_nodes]))
    edges = []
    for nbr in neighbors:
        if graph.has_edge(seed, nbr) or graph.has_edge(nbr, seed):
            edges.append([seed, nbr])
    return nodes, edges


def _trace_backed_engineering_demo(
    qid: str,
    title: str,
    why_gasl_wins: str,
    rag_blind_spot: str,
) -> Dict[str, Any]:
    run_id = "corpus_20260522_finalanswer_v1"
    payload = _load_trace_demo_payload(run_id, qid)
    answer_views = payload["answer_views"]
    selection = answer_views["selection"]
    selected_view = _lookup_selected_view(answer_views)
    selected_kind = selected_view["kind"]
    selected_payload = selected_view["payload"]
    question_json = json.loads(_repo_path("benchmark_results", run_id, qid, "question.json").read_text())
    graph_name = question_json.get("graph", "haiqu_engineering_controls")
    viz_path, full_path = _graph_paths(graph_name)
    G = _read_graph(str(full_path))
    viz = _read_graph(str(viz_path))

    focus_nodes: List[str] = []
    context_nodes: List[str] = []
    if selected_kind == "ranking":
        focus_nodes = [row["subject"] for row in selected_payload.get("ranked_subjects", [])[:3]]
        grouped = _lookup_first_view(answer_views, "grouped_summary")
        if grouped:
            context_nodes = [row.get("outcome") for row in grouped["payload"].get("rows", [])[:6] if row.get("outcome")]
    elif selected_kind == "distribution":
        ranking = _lookup_first_view(answer_views, "ranking")
        if ranking:
            focus_nodes = [row["subject"] for row in ranking["payload"].get("ranked_subjects", [])[:5]]

    focus_nodes = _filter_existing_nodes(viz, focus_nodes)
    context_nodes = _filter_existing_nodes(viz, context_nodes)
    all_nodes = list(dict.fromkeys(focus_nodes + context_nodes))
    touched_nodes: list[str] = list(all_nodes)
    replay: list[dict[str, Any]] = [
        _event(250, "gasl_step", {
            "command_type": "INIT",
            "status": "running",
            "command": "Starting GASL traversal...",
            "story_kicker": "Setup",
            "story_title": "Frame the question",
            "story_body": payload["question"],
            "story_meta": "GASL will search the graph, accumulate evidence, then synthesize an answer.",
        }),
        _event(460, "gasl_step", {
            "command_type": "FIND",
            "status": "running",
            "command": "FIND nodes with entity_type='ENGINEERING_CONTROL' AS engineering_controls",
            "story_kicker": "Search",
            "story_title": "Pull candidate controls into working memory",
            "story_body": "Start broad. The system is not trying to guess the winner yet; it is collecting plausible controls that might explain the question.",
        }),
    ]

    if qid == "q001":
        ranking_candidates = _filter_existing_nodes(
            viz,
            [row["subject"] for row in selected_payload.get("ranked_subjects", [])[:10]],
        )
        exploratory_candidates = list(dict.fromkeys(
            [node for node in ranking_candidates if node not in focus_nodes][:3] + ranking_candidates[:2]
        ))
        grouped = _lookup_first_view(answer_views, "grouped_summary")
        grouped_payload = grouped["payload"] if grouped else {"rows": []}

        replay.extend([
            _event(220, "gasl_highlight", {
                "nodes": ranking_candidates[:4],
                "edges": [],
                "command_type": "FIND",
                "status": "success",
                "command": "Seed an initial working set of plausible controls",
                "story_title": "First candidates enter",
                "story_body": "A few plausible controls come into view first. This is only a working set, not the answer.",
            }),
            _event(220, "gasl_highlight", {
                "nodes": ranking_candidates[4:8],
                "edges": [],
                "command_type": "FIND",
                "status": "success",
                "command": "Broaden the frontier before deciding which controls deserve deeper walks",
                "story_title": "Keep the frontier open",
                "story_body": "More controls are added so the search does not collapse too early onto a single explanation.",
            }),
            _event(320, "gasl_step", {
                "command_type": "GRAPHWALK",
                "status": "running",
                "command": "GRAPHWALK across validation and zone relations for multiple candidate controls",
                "story_kicker": "Walk",
                "story_title": "Trace validation paths across hospital zones",
                "story_body": "Now the search follows evidence-bearing relations. The goal is to see which controls connect to the broadest zone-linked validation footprint.",
            }),
        ])
        touched_nodes.extend(ranking_candidates[:8])

        for idx, control in enumerate(exploratory_candidates, start=1):
            wave_nodes, wave_edges = _neighbor_wave(viz, control, max_neighbors=9)
            touched_nodes.extend(wave_nodes)
            replay.extend([
                _event(220, "gasl_highlight", {
                    "nodes": wave_nodes,
                    "edges": wave_edges,
                    "command_type": "GRAPHWALK",
                    "status": "success",
                    "command": f"Probe candidate {idx}: follow validation and zone evidence around {control}",
                    "story_title": f"Probe candidate {idx}",
                    "story_body": f"{control} is explored as one possible explanation. The graph walk fans out through linked evidence and hospital-zone context.",
                }),
            ])

        replay.extend([
            _event(220, "answer_view", {
                "kicker": "Early evidence",
                "title": "Candidate evidence is still mixed",
                "view_kind": "grouped_summary",
                "view_payload": _partial_grouped_payload(grouped_payload, 2),
                "selection_rationale": "At this stage the search has touched several plausible controls, but the ranking is not settled.",
                "nodes": exploratory_candidates[:2],
                "meta": grouped.get("source_variable") if grouped else "",
                "story_title": "Evidence is starting to organize",
                "story_body": "This panel is not the answer. It is a partial evidence view showing how support is beginning to accumulate while the field is still mixed.",
            }),
            _event(300, "gasl_step", {
                "command_type": "GRAPHWALK",
                "status": "running",
                "command": "Revisit the strongest candidates and add more zone-linked validation evidence",
                "story_kicker": "Refine",
                "story_title": "Return to the strongest candidates",
                "story_body": "After the first pass, the search narrows. The system goes back for more evidence around the candidates that still look viable.",
            }),
        ])

        for idx, control in enumerate(focus_nodes[:3], start=1):
            wave_nodes, wave_edges = _neighbor_wave(viz, control, max_neighbors=8)
            touched_nodes.extend(wave_nodes)
            replay.extend([
                _event(220, "gasl_highlight", {
                    "nodes": wave_nodes,
                    "edges": wave_edges,
                    "command_type": "GRAPHWALK",
                    "status": "success",
                    "command": f"Deepen evidence for finalist {idx}: {control}",
                    "story_title": f"Deepen finalist {idx}",
                    "story_body": f"{control} survives the first pass, so the search spends more graph budget validating its breadth rather than merely touching it once.",
                }),
            ])

        replay.extend([
            _event(320, "gasl_step", {
                "command_type": "AGGREGATE",
                "status": "running",
                "command": "AGGREGATE per-control evidence across hospital zones",
                "story_kicker": "Aggregate",
                "story_title": "Convert scattered traces into comparable evidence",
                "story_body": "This is the turning point: graph walks become counts. Evidence from many local neighborhoods is pooled so controls can be compared on the same footing.",
            }),
            _event(220, "answer_view", {
                "kicker": "Evidence accumulating",
                "title": "First evidence rows land",
                "view_kind": "grouped_summary",
                "view_payload": _partial_grouped_payload(grouped_payload, 1),
                "selection_rationale": "The grouped panel starts to fill as soon as the first zone-level counts settle.",
                "nodes": focus_nodes[:1],
                "meta": grouped.get("source_variable") if grouped else "",
                "story_title": "The first stable evidence rows appear",
                "story_body": "As aggregation finishes, evidence stops looking like disconnected paths and starts looking like a readable summary.",
            }),
            _event(220, "answer_view", {
                "kicker": "Evidence accumulating",
                "title": "Early grouped evidence",
                "view_kind": "grouped_summary",
                "view_payload": _partial_grouped_payload(grouped_payload, 3),
                "selection_rationale": "Each pass pools zone-level evidence before the final ranking is produced.",
                "nodes": focus_nodes[:2],
                "meta": grouped.get("source_variable") if grouped else "",
                "story_title": "Evidence thickens before ranking",
                "story_body": "The panel fills in before any ranking is finalized, so the viewer can see the evidence basis rather than only the final ordering.",
            }),
            _event(300, "gasl_step", {
                "command_type": "RANK",
                "status": "running",
                "command": "RANK controls by validation footprint breadth",
                "story_kicker": "Rank",
                "story_title": "Only now does ordering begin",
                "story_body": "After search and accumulation, the system can finally order the candidates by the breadth of their zone-linked validation support.",
            }),
            _event(220, "answer_view", {
                "kicker": "Ranking stabilizes",
                "title": "Top control emerges",
                "view_kind": "ranking",
                "view_payload": _partial_ranking_payload(selected_payload, 1),
                "selection_rationale": selection.get("rationale") or "",
                "nodes": focus_nodes[:1],
                "meta": selected_view.get("source_variable") or "",
                "story_title": "A leader appears",
                "story_body": "One control starts to separate from the pack, but the full ordering is still developing.",
            }),
            _event(220, "answer_view", {
                "kicker": "Ranking stabilizes",
                "title": "Top two controls emerge",
                "view_kind": "ranking",
                "view_payload": _partial_ranking_payload(selected_payload, 2),
                "selection_rationale": selection.get("rationale") or "",
                "nodes": focus_nodes[:2],
                "meta": selected_view.get("source_variable") or "",
                "story_title": "The shortlist stabilizes",
                "story_body": "The leading pair is now visible, with enough evidence to compare them directly.",
            }),
            _event(220, "answer_view", {
                "kicker": "Ranking stabilizes",
                "title": "Top controls emerge",
                "view_kind": "ranking",
                "view_payload": _partial_ranking_payload(selected_payload, 3),
                "selection_rationale": selection.get("rationale") or "",
                "nodes": focus_nodes,
                "meta": selected_view.get("source_variable") or "",
                "story_title": "The final evidence ranking settles",
                "story_body": "The ranking view now reflects the accumulated graph evidence rather than an early guess.",
            }),
        ])
    elif qid == "q007":
        ranking = _lookup_first_view(answer_views, "ranking")
        ranked_subjects = _filter_existing_nodes(
            viz,
            [row["subject"] for row in (ranking["payload"].get("ranked_subjects", []) if ranking else [])[:15]],
        )
        if len(ranked_subjects) < 15:
            filler = [
                node
                for node, attrs in viz.nodes(data=True)
                if attrs.get("entity_type") == "ENGINEERING_CONTROL" and node not in ranked_subjects
            ]
            ranked_subjects.extend(filler[: 15 - len(ranked_subjects)])
        replay.extend([
            _event(180, "gasl_highlight", {
                "nodes": ranked_subjects[:5],
                "edges": [],
                "command_type": "FIND",
                "status": "success",
                "command": "Start with a wide control sample rather than a single best node",
                "story_title": "Sample broadly before computing a distribution",
                "story_body": "A distribution should not be inferred from a single control, so the search starts with a deliberately wide sample.",
            }),
            _event(180, "gasl_highlight", {
                "nodes": ranked_subjects[5:10],
                "edges": [],
                "command_type": "FIND",
                "status": "success",
                "command": "Sweep more controls into the working frontier",
            }),
            _event(180, "gasl_highlight", {
                "nodes": ranked_subjects[10:15],
                "edges": [],
                "command_type": "FIND",
                "status": "success",
                "command": "Keep expanding candidate coverage before aggregation",
            }),
            _event(300, "gasl_step", {
                "command_type": "GRAPHWALK",
                "status": "running",
                "command": "GRAPHWALK validation links to collect support counts per control",
                "story_kicker": "Walk",
                "story_title": "Collect support counts from many controls",
                "story_body": "The graph walk now gathers validation-linked support so that the eventual histogram reflects whole-graph structure, not a thin retrieval slice.",
            }),
        ])
        touched_nodes.extend(ranked_subjects[:15])
        for control in ranked_subjects[:4]:
            wave_nodes, wave_edges = _neighbor_wave(viz, control, max_neighbors=7)
            touched_nodes.extend(wave_nodes)
            replay.append(_event(180, "gasl_highlight", {
                "nodes": wave_nodes,
                "edges": wave_edges,
                "command_type": "GRAPHWALK",
                "status": "success",
                "command": f"Follow support evidence around {control}",
                "story_title": f"Track support around {control}",
                "story_body": "This local pass follows a specific control through its nearby validation evidence before the counts are merged into the global distribution.",
            }))
        replay.extend([
            _event(300, "gasl_step", {
                "command_type": "AGGREGATE",
                "status": "running",
                "command": "AGGREGATE support counts into a whole-graph distribution",
                "story_kicker": "Aggregate",
                "story_title": "Turn many local counts into one distribution",
                "story_body": "The search is no longer asking which single node matters most. It is building a shape: how support counts distribute across all controls.",
            }),
            _event(180, "answer_view", {
                "kicker": "Distribution building",
                "title": "Histogram starts to populate",
                "view_kind": "distribution",
                "view_payload": _partial_distribution_payload(selected_payload, 1),
                "selection_rationale": "The first bin fills as the earliest controls are counted.",
                "nodes": ranked_subjects[:5],
                "meta": selected_view.get("source_variable") or "",
                "story_title": "The histogram begins to form",
                "story_body": "As early counts land, the left side of the histogram appears first. Later bins fill in as more controls are counted.",
            }),
            _event(180, "answer_view", {
                "kicker": "Distribution building",
                "title": "Support-count statistics",
                "view_kind": "distribution",
                "view_payload": _partial_distribution_payload(selected_payload, 2),
                "selection_rationale": "As the aggregation completes, the histogram bins populate from left to right.",
                "nodes": ranked_subjects[:8],
                "meta": selected_view.get("source_variable") or "",
                "story_title": "Statistics become legible",
                "story_body": "With more counts pooled, summary statistics like n, mean, and median start to stabilize.",
            }),
            _event(180, "answer_view", {
                "kicker": "Distribution building",
                "title": "More of the distribution becomes visible",
                "view_kind": "distribution",
                "view_payload": _partial_distribution_payload(selected_payload, 4),
                "selection_rationale": "Additional bins appear as more control support counts enter the aggregate.",
                "nodes": ranked_subjects[:10],
                "meta": selected_view.get("source_variable") or "",
                "story_title": "The full distribution emerges",
                "story_body": "By this point the graph-wide shape is readable: not just a few examples, but the overall support profile across controls.",
            }),
            _event(260, "gasl_step", {
                "command_type": "PROCESS",
                "status": "running",
                "command": "PROCESS the aggregate into final distribution and summary text",
            }),
            _event(200, "answer_view", {
                "kicker": "Distribution settles",
                "title": "Full validation-support distribution",
                "view_kind": "distribution",
                "view_payload": selected_payload,
                "selection_rationale": selection.get("rationale") or "",
                "nodes": ranked_subjects[:10],
                "meta": selected_view.get("source_variable") or "",
            }),
        ])
    else:
        ranking = _lookup_first_view(answer_views, "ranking")
        ranking_subjects = _filter_existing_nodes(
            viz,
            [row["subject"] for row in (ranking["payload"].get("ranked_subjects", []) if ranking else [])[:8]],
        )
        grouped = _lookup_first_view(answer_views, "grouped_summary")
        generic_nodes = list(dict.fromkeys((ranking_subjects or focus_nodes or context_nodes)[:6]))
        replay.extend([
            _event(220, "gasl_highlight", {
                "nodes": generic_nodes[:3],
                "edges": [],
                "command_type": "FIND",
                "status": "success",
                "command": "Initial candidates surface from the graph search",
                "story_title": "Initial candidates surface",
                "story_body": "The search starts broad enough to avoid locking onto a single answer too early.",
            }),
            _event(220, "gasl_highlight", {
                "nodes": generic_nodes[3:6],
                "edges": [],
                "command_type": "FIND",
                "status": "success",
                "command": "The working set expands before evidence is aggregated",
                "story_title": "The working set expands",
                "story_body": "More candidates come in before the system decides which local neighborhoods deserve deeper attention.",
            }),
            _event(300, "gasl_step", {
                "command_type": "GRAPHWALK",
                "status": "running",
                "command": "GRAPHWALK across validation, support, and zone relations to accumulate evidence",
                "story_kicker": "Walk",
                "story_title": "Trace evidence-bearing relations",
                "story_body": "The system follows graph relations around the working set so the eventual answer view reflects accumulated evidence rather than a single passage.",
            }),
        ])
        for idx, control in enumerate((generic_nodes or focus_nodes)[:3], start=1):
            wave_nodes, wave_edges = _neighbor_wave(viz, control, max_neighbors=6)
            touched_nodes.extend(wave_nodes)
            replay.append(_event(180, "gasl_highlight", {
                "nodes": wave_nodes,
                "edges": wave_edges,
                "command_type": "GRAPHWALK",
                "status": "success",
                "command": f"Local evidence wave {idx}: {control}",
                "story_title": f"Local evidence wave {idx}",
                "story_body": f"{control} is explored locally before the evidence is pooled into a more legible answer view.",
            }))
        replay.extend([
            _event(260, "gasl_step", {
                "command_type": "AGGREGATE",
                "status": "running",
                "command": "AGGREGATE the local traces into a readable evidence view",
                "story_kicker": "Aggregate",
                "story_title": "Turn local traces into evidence",
                "story_body": "At this point the graph walks stop looking like isolated neighborhoods and start becoming a summary the viewer can read.",
            }),
            _event(180, "answer_view", {
                "kicker": "Evidence accumulating",
                "title": "Early evidence snapshot",
                "view_kind": selected_kind,
                "view_payload": _partial_distribution_payload(selected_payload, 2) if selected_kind == "distribution" else (_partial_ranking_payload(selected_payload, 2) if selected_kind == "ranking" else (_partial_grouped_payload(selected_payload, 2) if selected_kind == "grouped_summary" else selected_payload)),
                "selection_rationale": "The answer view starts partial, then settles as more graph evidence is pooled.",
                "nodes": generic_nodes[:2] or focus_nodes[:2],
            }),
        ])

    replay.extend([
        _event(300, "gasl_step", {
            "command_type": "PROCESS",
            "status": "running",
            "command": "Compile answer views from the traversed evidence",
        }),
        _event(320, "answer_view", {
            "kicker": "Answer view",
            "title": f"Selected {selected_kind} evidence",
            "view_kind": selected_kind,
            "view_payload": selected_payload,
            "selection_rationale": selection.get("rationale") or "",
            "nodes": focus_nodes,
            "meta": selected_view.get("source_variable") or "",
        }),
        _event(650, "query_complete", {
            "answer": payload["final_answer"],
            "nodes": list(dict.fromkeys(touched_nodes + focus_nodes)),
            "edges": [],
            "iterations": 7 if qid in {"q001", "q007"} else 5,
            "query_answered": True,
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "calls": 0},
        }),
    ])

    if qid == "q001":
        replay = _scale_replay_delays(replay, 8.5)
    elif qid == "q007":
        replay = _scale_replay_delays(replay, 7.0)
    elif qid in DEMO_SHORTLIST_12:
        replay = _scale_replay_delays(replay, 5.0)

    metrics = {
        "selected_view": selected_kind,
        "focus_nodes": len(focus_nodes),
        "rag_window": 15,
    }
    if selected_kind == "distribution":
        metrics["n"] = selected_payload.get("n", 0)
    if selected_kind == "ranking":
        metrics["row_count"] = selected_payload.get("row_count", 0)

    demo_id = f"engineering-{qid}" if graph_name == "haiqu_engineering_controls" else f"{graph_name.replace('haiqu_', '')}-{qid}"
    return {
        "id": demo_id,
        "title": title,
        "graph_path": str(viz_path),
        "full_graph_path": str(full_path),
        "question": payload["question"],
        "why_gasl_wins": why_gasl_wins,
        "rag_blind_spot": rag_blind_spot,
        "metrics": metrics,
        "replay": replay,
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
        _trace_backed_engineering_demo(
            "q001",
            "Q001 · Validation Footprint Across Zones",
            "GASL can aggregate validation support across the full engineering-controls graph, then surface the selected ranking view before the final synthesis.",
            "RAG can retrieve relevant controls, but it does not guarantee graph-wide breadth across every hospital-zone validation path.",
        ),
        _trace_backed_engineering_demo(
            "q007",
            "Q007 · Distribution of Validation Support",
            "GASL compiles a distribution answer view with n, mean, median, and a full histogram, which is hard to recover from a shallow retrieval slice.",
            "RAG can cite a few controls, but it is not naturally set up to compute whole-graph support distributions with a readable evidence summary.",
        ),
        _trace_backed_engineering_demo(
            "q003",
            "Q003 · Compliance-Linked Controls",
            "GASL can search broadly, accumulate practical compliance evidence, and then rank controls from the resulting evidence view instead of guessing from a few retrieved passages.",
            "RAG can retrieve relevant controls, but it cannot reliably show how compliance evidence accumulates across the graph before the ranking settles.",
        ),
        _trace_backed_engineering_demo(
            "q004",
            "Q004 · Best-Supported Controls by Outcome",
            "GASL can organize outcome-linked support into grouped evidence rows and then synthesize the strongest control-outcome patterns.",
            "RAG may surface a few supporting passages, but it is not naturally aligned to grouped control-outcome summaries across the whole graph.",
        ),
        _trace_backed_engineering_demo(
            "q005",
            "Q005 · Adverse Outcomes by Control",
            "GASL can trace adverse-effect and safety outcomes back to controls and organize them into readable grouped evidence before answering.",
            "RAG often retrieves isolated adverse mentions without the same structured link back to control-specific support counts.",
        ),
        _trace_backed_engineering_demo(
            "q008",
            "Q008 · Adverse-Effect Support Distribution",
            "GASL can turn many control-level support counts into a distribution view with explicit summary statistics.",
            "RAG can mention examples, but it does not naturally compute a global distribution over control-level adverse-effect evidence.",
        ),
        _trace_backed_engineering_demo(
            "q009",
            "Q009 · Pathogen-Coverage Distribution",
            "GASL computes a whole-graph pathogen-coverage distribution instead of inferring it from a thin slice of retrieved text.",
            "RAG may cite a few controls or pathogens, but it does not guarantee a graph-wide coverage profile.",
        ),
        _trace_backed_engineering_demo(
            "q010",
            "Q010 · Top Controls: Validation vs Burden",
            "GASL can accumulate support and burden evidence separately, then compare the leading controls on a shared footing.",
            "RAG can summarize a couple of controls, but it is less suited to side-by-side comparison grounded in accumulated graph evidence.",
        ),
        _trace_backed_engineering_demo(
            "q012",
            "Q012 · Top Controls: Studies vs Zones",
            "GASL can compare validation-study count and linked-zone reach in one pass because both signals are already represented in the graph.",
            "RAG can retrieve studies and zones, but it does not naturally combine them into a single comparative answer view.",
        ),
        _trace_backed_engineering_demo(
            "q013",
            "Q013 · Tradeoff Frontier: Validation vs Burden",
            "GASL can expose a tradeoff frontier by organizing the evidence into comparable control-level records before synthesis.",
            "RAG can retrieve strong individual controls, but it does not naturally trace a frontier across competing evidence dimensions.",
        ),
        _trace_backed_engineering_demo(
            "q014",
            "Q014 · Tradeoff Frontier: Compliance vs Pathogen Breadth",
            "GASL can search across both compliance evidence and pathogen-target breadth, then visualize which controls survive the tradeoff frontier.",
            "RAG can retrieve examples from each side, but it rarely computes the multi-criterion frontier itself.",
        ),
        _trace_backed_engineering_demo(
            "q019",
            "Q019 · Zones with Broadest Air-Path / Pressure Mix",
            "GASL can walk hospital-environment edges across multiple relation families before ranking zones by the breadth of their connectivity.",
            "RAG can retrieve relevant zones, but it does not naturally compare them across multiple edge families in one answer view.",
        ),
        _trace_backed_engineering_demo(
            "q022",
            "Q022 · Most-Connected Zones by Airflow Outcome",
            "GASL can organize zone-outcome support into grouped evidence rows so the final answer reflects many connected traces rather than one dominant passage.",
            "RAG can mention airflow outcomes, but it is weaker at synthesizing the most-connected zones from all available graph evidence.",
        ),
        _trace_backed_engineering_demo(
            "q026",
            "Q026 · Air-Path Connectivity Distribution",
            "GASL can compute a full connectivity-count distribution across hospital zones and expose it as a distribution answer view.",
            "RAG can cite example zones, but it is not naturally set up to derive a graph-wide connectivity distribution.",
        ),
        _domain_frequency_demo(),
        _confounder_span_demo(),
        _control_breadth_demo(),
    ]


def get_demo(demo_id: str) -> Dict[str, Any] | None:
    for demo in get_demo_catalog():
        if demo["id"] == demo_id:
            return demo
    return None
