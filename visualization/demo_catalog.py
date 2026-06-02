"""
Curated demo scenarios that highlight where GASL outperforms plain RAG.

Each scenario is grounded in a concrete graph pattern so the demo copy,
replay trace, and answer text can be generated from the actual graph.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy
from functools import lru_cache
import json
import logging
from pathlib import Path
from typing import Any, Dict, Iterable, List

import networkx as nx


REPO_ROOT = Path(__file__).resolve().parents[1]
logger = logging.getLogger(__name__)
TRACE_DEMO_RUN_PREFERENCES = [
    "corpus_20260521_view_balanced_72_rowshapefix_shim_v2",  # full 72-question corpus
    "corpus_20260522_finalanswer_v1",  # fallback when answer_views are missing in the full run
]
DEMO_SHORTLIST_12 = [
    "q001", "q007",
    "q019", "q022", "q032", "q033",
    "q037", "q040", "q049",
    "q058", "q063", "q067",
]
# Compatibility name retained for existing render scripts, but now intentionally a 12-question set.
DEMO_VIDEO_SHAREABLE_14 = [*DEMO_SHORTLIST_12]
PAPER_STYLE_DEMOS_6 = [
    "paper-symbolism-metaphor",
    "paper-camera-eye",
    "paper-creative-sound",
    "paper-big-bang",
    "paper-old-footage",
    "paper-ending-first",
]
PAPER_SYMBOLISM_SHORTLIST_12 = [f"paper-symbolism-{qid}" for qid in DEMO_SHORTLIST_12]


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
    candidates = [
        _repo_path("haiqu_graphs", "v1", graph_name, f"{graph_name}_graph.graphml"),
        _repo_path("enzyme_graphs", "multi_scale_gpt55_c400", graph_name, f"{graph_name}_graph.graphml"),
    ]
    for full in candidates:
        if full.exists():
            return (full, full)

    glob_matches = sorted(REPO_ROOT.glob(f"**/{graph_name}/{graph_name}_graph.graphml"))
    if glob_matches:
        return (glob_matches[0], glob_matches[0])

    full = candidates[0]
    return (full, full)


def _resolve_graph_paths(
    *,
    question_json: dict[str, Any],
    graph_path: str | None = None,
    full_graph_path: str | None = None,
) -> tuple[Path, Path]:
    if graph_path or full_graph_path:
        viz = Path(graph_path or full_graph_path or "")
        full = Path(full_graph_path or graph_path or "")
        return (viz, full)

    graph_name = question_json.get("graph")
    if graph_name:
        return _graph_paths(graph_name)

    question_graph = question_json.get("graph_path")
    if question_graph:
        full = Path(question_graph)
        return (full, full)

    raise FileNotFoundError("Unable to resolve graph path from question.json; pass graph_path/full_graph_path explicitly.")


def _load_trace_demo_payload(qid: str, run_ids: list[str] | None = None) -> dict[str, Any]:
    run_ids = run_ids or TRACE_DEMO_RUN_PREFERENCES
    last_error = None
    for run_id in run_ids:
        trace_path = _repo_path("benchmark_results", run_id, qid, "gasl_artifacts", "traces", f"{qid}.jsonl")
        if not trace_path.exists():
            last_error = f"missing trace {trace_path}"
            continue
        answer_views = None
        final_answer = None
        question = None
        trace_events: list[dict[str, Any]] = []
        for line in trace_path.open(encoding="utf-8"):
            row = json.loads(line)
            trace_events.append(row)
            if row["event"] == "answer_views":
                answer_views = row["payload"]
                question = answer_views.get("query")
            if row["event"] == "final_analysis_response":
                final_answer = row["payload"]["response"]
        if not final_answer:
            gasl_path = _repo_path("benchmark_results", run_id, qid, "gasl.json")
            if gasl_path.exists():
                gasl = json.loads(gasl_path.read_text(encoding="utf-8"))
                final_answer = gasl.get("answer") or gasl.get("result", {}).get("final_answer")
        if not question:
            question_path = _repo_path("benchmark_results", run_id, qid, "question.json")
            if question_path.exists():
                question = json.loads(question_path.read_text(encoding="utf-8")).get("question")
        if final_answer:
            return {
                "question": question,
                "answer_views": answer_views,
                "final_answer": final_answer,
                "run_id": run_id,
                "trace_events": trace_events,
            }
        last_error = f"Missing final answer for {qid} in {run_id}"
    raise ValueError(last_error or f"Could not load trace-backed payload for {qid}")


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


def _extract_view_nodes(payload: dict[str, Any], *, limit: int = 12) -> list[str]:
    node_ids: list[str] = []
    ranked = payload.get("ranked_subjects") or []
    for row in ranked[:limit]:
        if isinstance(row, dict):
            for key in ("subject", "outcome", "src_id", "tgt_id"):
                value = row.get(key)
                if isinstance(value, str):
                    node_ids.append(value)
    rows = payload.get("rows") or []
    for row in rows[:limit]:
        if not isinstance(row, dict):
            continue
        for key in ("subject", "outcome", "src_id", "tgt_id"):
            value = row.get(key)
            if isinstance(value, str):
                node_ids.append(value)
    return list(dict.fromkeys(node_ids))


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


def _chunk_list(items: list[Any], size: int) -> list[list[Any]]:
    return [items[i:i + size] for i in range(0, len(items), size)]


def estimate_demo_micro_actions(
    replay: list[dict[str, Any]],
    wave_size: int = 2,
    demo_subpasses: int = 6,
) -> int:
    import math

    score = 0
    for step in replay:
        event = step.get("event")
        payload = step.get("payload", {})
        if event == "gasl_highlight":
            n = len(payload.get("nodes", []))
            waves = max(1, math.ceil(max(1, n) / wave_size))
            score += waves * demo_subpasses
        elif event == "gasl_step":
            score += 4
        elif event == "answer_view":
            score += 6
        elif event == "query_complete":
            score += 1
    return score


def _replay_focus_nodes(replay: list[dict[str, Any]], limit: int = 18) -> list[str]:
    nodes: list[str] = []
    for step in replay:
        payload = step.get("payload", {})
        nodes.extend(payload.get("nodes", []))
    return list(dict.fromkeys(nodes))[:limit]


def _first_answer_view_event(replay: list[dict[str, Any]]) -> dict[str, Any] | None:
    for step in replay:
        if step.get("event") == "answer_view":
            return deepcopy(step)
    return None


def _paper_style_variant(
    base_demo: dict[str, Any],
    *,
    demo_id: str,
    visual_style: str,
    title: str,
    opener_events: list[dict[str, Any]],
    why_choice: str,
    style_pitch: str,
    delay_factor: float = 1.0,
) -> dict[str, Any]:
    demo = deepcopy(base_demo)
    replay = opener_events + deepcopy(base_demo["replay"])
    if delay_factor != 1.0:
        replay = _scale_replay_delays(replay, delay_factor)
    demo["id"] = demo_id
    demo["title"] = title
    demo["visual_style"] = visual_style
    demo["style_pitch"] = style_pitch
    demo["why_gasl_wins"] = why_choice
    demo["rag_blind_spot"] = (
        "This variant is intentionally about opening rhetoric and visual framing, "
        "not about changing the underlying graph answer."
    )
    demo["replay"] = replay
    demo["metrics"] = {
        **demo.get("metrics", {}),
        "opening_style": visual_style,
        "micro_actions_est": estimate_demo_micro_actions(replay),
    }
    return demo


def _trace_backed_engineering_demo(
    qid: str,
    title: str,
    why_gasl_wins: str,
    rag_blind_spot: str,
) -> Dict[str, Any]:
    return build_cinematic_demo_from_artifacts(
        qid=qid,
        title=title,
        why_gasl_wins=why_gasl_wins,
        rag_blind_spot=rag_blind_spot,
    )


def build_cinematic_demo_from_artifacts(
    *,
    qid: str,
    title: str | None = None,
    why_gasl_wins: str | None = None,
    rag_blind_spot: str | None = None,
    run_id: str | None = None,
    graph_path: str | None = None,
    full_graph_path: str | None = None,
    demo_id: str | None = None,
    target_seconds: int | None = None,
) -> Dict[str, Any]:
    payload = _load_trace_demo_payload(qid, run_ids=[run_id] if run_id else None)
    answer_views = payload["answer_views"]
    question_json = json.loads(_repo_path("benchmark_results", payload["run_id"], qid, "question.json").read_text())
    graph_name = question_json.get("graph", "unknown_graph")
    viz_path, full_path = _resolve_graph_paths(
        question_json=question_json,
        graph_path=graph_path,
        full_graph_path=full_graph_path,
    )
    G = _read_graph(str(full_path))
    viz = _read_graph(str(viz_path))

    if not answer_views:
        raise ValueError(
            f"{qid} in {payload['run_id']} has no answer_views artifact; refusing to build a static/non-cinematic replay."
        )

    selection = answer_views["selection"]
    selected_view = _lookup_selected_view(answer_views)
    selected_kind = selected_view["kind"]
    selected_payload = selected_view["payload"]
    selected_nodes = _filter_existing_nodes(viz, _extract_view_nodes(selected_payload))
    grouped = _lookup_first_view(answer_views, "grouped_summary")
    grouped_payload = grouped["payload"] if grouped else {"rows": []}
    grouped_nodes = _filter_existing_nodes(viz, _extract_view_nodes(grouped_payload))
    ranking = _lookup_first_view(answer_views, "ranking")
    ranking_nodes = _filter_existing_nodes(viz, _extract_view_nodes(ranking["payload"])) if ranking else []

    focus_nodes: List[str] = []
    context_nodes: List[str] = []
    if selected_kind == "ranking":
        focus_nodes = ranking_nodes[:6]
        context_nodes = grouped_nodes[:6]
    elif selected_kind == "distribution":
        focus_nodes = ranking_nodes[:8]
    else:
        focus_nodes = selected_nodes[:6]
        context_nodes = grouped_nodes[:6]

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
        ranking_candidates = list(dict.fromkeys(ranking_nodes + selected_nodes + grouped_nodes))[:10]
        exploratory_candidates = list(dict.fromkeys(
            [node for node in ranking_candidates if node not in focus_nodes][:3] + ranking_candidates[:2]
        ))

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
        generic_nodes = list(dict.fromkeys((ranking_subjects or focus_nodes or context_nodes)[:8]))
        intro_chunks = _chunk_list(generic_nodes, 2)
        replay.extend([
            _event(180, "gasl_highlight", {
                "nodes": intro_chunks[0] if len(intro_chunks) > 0 else [],
                "edges": [],
                "command_type": "FIND",
                "status": "success",
                "command": "Initial candidates surface from the graph search",
                "story_title": "Initial candidates surface",
                "story_body": "The search starts broad enough to avoid locking onto a single answer too early.",
            }),
            _event(180, "gasl_highlight", {
                "nodes": intro_chunks[1] if len(intro_chunks) > 1 else [],
                "edges": [],
                "command_type": "FIND",
                "status": "success",
                "command": "The working set expands before evidence is aggregated",
                "story_title": "The working set expands",
                "story_body": "More candidates come in before the system decides which local neighborhoods deserve deeper attention.",
            }),
            _event(180, "gasl_highlight", {
                "nodes": intro_chunks[2] if len(intro_chunks) > 2 else [],
                "edges": [],
                "command_type": "FIND",
                "status": "success",
                "command": "Keep several plausible branches open while evidence remains mixed",
                "story_title": "Keep the frontier open",
                "story_body": "The replay should still look undecided here. The system is keeping enough candidate branches alive that the answer does not look predetermined.",
            }),
            _event(180, "gasl_highlight", {
                "nodes": intro_chunks[3] if len(intro_chunks) > 3 else [],
                "edges": [],
                "command_type": "FIND",
                "status": "success",
                "command": "Sweep one more branch into the working frontier before committing to deeper walks",
                "story_title": "One more branch stays alive",
                "story_body": "This extra beat keeps the search from feeling like it already knows the answer. The frontier is still broad enough that the later evidence accumulation matters.",
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
        explored_controls = (generic_nodes or focus_nodes)[:5]
        for idx, control in enumerate(explored_controls, start=1):
            wave_nodes, wave_edges = _neighbor_wave(viz, control, max_neighbors=6)
            touched_nodes.extend(wave_nodes)
            node_chunks = _chunk_list(wave_nodes, 2)
            edge_chunks = _chunk_list(wave_edges, 2)
            for chunk_idx, node_chunk in enumerate(node_chunks, start=1):
                replay.append(_event(140, "gasl_highlight", {
                    "nodes": node_chunk,
                    "edges": edge_chunks[chunk_idx - 1] if chunk_idx - 1 < len(edge_chunks) else [],
                    "command_type": "GRAPHWALK",
                    "status": "success",
                    "command": f"Local evidence wave {idx}.{chunk_idx}: {control}",
                    "story_title": f"Local evidence wave {idx}.{chunk_idx}",
                    "story_body": f"{control} is explored locally before the evidence is pooled into a more legible answer view.",
                }))
            replay.append(_event(140, "answer_view", {
                "kicker": "Evidence accumulating",
                "title": f"Partial evidence after candidate {idx}",
                "view_kind": selected_kind,
                "view_payload": _partial_distribution_payload(selected_payload, min(2 + idx, 4)) if selected_kind == "distribution" else (_partial_ranking_payload(selected_payload, min(1 + idx, 3)) if selected_kind == "ranking" else (_partial_grouped_payload(selected_payload, min(1 + idx, 3)) if selected_kind == "grouped_summary" else selected_payload)),
                "selection_rationale": f"After candidate {idx}, the evidence view is still partial and the ordering is not final.",
                "nodes": node_chunks[0][:2] if node_chunks else [],
                "story_title": f"Evidence after candidate {idx}",
                "story_body": "The answer view keeps updating while the graph walk is still ongoing, so the viewer sees accumulation rather than a late reveal.",
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
            _event(180, "gasl_step", {
                "command_type": "PROCESS",
                "status": "running",
                "command": "PROCESS the pooled evidence into a more stable intermediate summary",
                "story_kicker": "Process",
                "story_title": "Stabilize the pooled evidence",
                "story_body": "This intermediate pass keeps the summary moving while the graph is still being searched, rather than waiting for one final reveal.",
            }),
            _event(180, "answer_view", {
                "kicker": "Evidence accumulating",
                "title": "Early evidence snapshot",
                "view_kind": selected_kind,
                "view_payload": _partial_distribution_payload(selected_payload, 2) if selected_kind == "distribution" else (_partial_ranking_payload(selected_payload, 2) if selected_kind == "ranking" else (_partial_grouped_payload(selected_payload, 2) if selected_kind == "grouped_summary" else selected_payload)),
                "selection_rationale": "The answer view starts partial, then settles as more graph evidence is pooled.",
                "nodes": generic_nodes[:2] or focus_nodes[:2],
            }),
            _event(180, "answer_view", {
                "kicker": "Evidence accumulating",
                "title": "Midway evidence snapshot",
                "view_kind": selected_kind,
                "view_payload": _partial_distribution_payload(selected_payload, 3) if selected_kind == "distribution" else (_partial_ranking_payload(selected_payload, 3) if selected_kind == "ranking" else (_partial_grouped_payload(selected_payload, 3) if selected_kind == "grouped_summary" else selected_payload)),
                "selection_rationale": "A second partial view gives the replay time to show evidence thickening before the final answer view lands.",
                "nodes": generic_nodes[:3] or focus_nodes[:3],
            }),
            _event(180, "answer_view", {
                "kicker": "Evidence accumulating",
                "title": "Late evidence snapshot",
                "view_kind": selected_kind,
                "view_payload": _partial_distribution_payload(selected_payload, 4) if selected_kind == "distribution" else (_partial_ranking_payload(selected_payload, 3) if selected_kind == "ranking" else (_partial_grouped_payload(selected_payload, 4) if selected_kind == "grouped_summary" else selected_payload)),
                "selection_rationale": "A late partial view makes the answer feel earned rather than appearing all at once.",
                "nodes": generic_nodes[:4] or focus_nodes[:4],
            }),
            _event(160, "gasl_step", {
                "command_type": "PROCESS",
                "status": "running",
                "command": "PROCESS the late evidence snapshot into a final, readable answer view",
                "story_kicker": "Process",
                "story_title": "Lock the evidence before the reveal",
                "story_body": "One last processing pass keeps the final answer from feeling like a sudden jump from subgraph to conclusion.",
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

    if target_seconds and target_seconds > 0:
        total_s = max(1.0, sum(step["delay_ms"] for step in replay) / 1000.0)
        replay = _scale_replay_delays(replay, target_seconds / total_s)
    elif qid == "q001":
        replay = _scale_replay_delays(replay, 8.5)
    elif qid == "q007":
        replay = _scale_replay_delays(replay, 7.0)
    elif qid in DEMO_SHORTLIST_12:
        replay = _scale_replay_delays(replay, 3.5)

    metrics = {
        "selected_view": selected_kind,
        "focus_nodes": len(focus_nodes),
        "rag_window": 15,
    }
    if selected_kind == "distribution":
        metrics["n"] = selected_payload.get("n", 0)
    if selected_kind == "ranking":
        metrics["row_count"] = selected_payload.get("row_count", 0)
    metrics["micro_actions_est"] = estimate_demo_micro_actions(replay)

    inferred_demo_id = f"engineering-{qid}" if graph_name == "haiqu_engineering_controls" else f"{graph_name.replace('haiqu_', '')}-{qid}"
    return {
        "id": demo_id or inferred_demo_id,
        "title": title or f"{qid.upper()} · Long-form cinematic",
        "graph_path": str(viz_path),
        "full_graph_path": str(full_path),
        "question": payload["question"],
        "why_gasl_wins": why_gasl_wins or "Replay synthesized directly from committed GASL answer-view artifacts, with node-focus beats derived from the answer views themselves.",
        "rag_blind_spot": rag_blind_spot or "This on-demand long-form path reconstructs the cinematic replay from committed answer views instead of relying on a hand-authored comparison script.",
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


SELECTED_TRACE_DEMO_CONFIG: dict[str, tuple[str, str, str]] = {
    "q001": (
        "Q001 · Validation Footprint Across Zones",
        "GASL can aggregate validation support across the full engineering-controls graph, then surface the selected ranking view before the final synthesis.",
        "RAG can retrieve relevant controls, but it does not guarantee graph-wide breadth across every hospital-zone validation path.",
    ),
    "q007": (
        "Q007 · Distribution of Validation Support",
        "GASL compiles a distribution answer view with n, mean, median, and a full histogram, which is hard to recover from a shallow retrieval slice.",
        "RAG can cite a few controls, but it is not naturally set up to compute whole-graph support distributions with a readable evidence summary.",
    ),
    "q019": (
        "Q019 · Zones with Broadest Air-Path / Pressure Mix",
        "GASL can walk hospital-environment edges across multiple relation families before ranking zones by the breadth of their connectivity.",
        "RAG can retrieve relevant zones, but it does not naturally compare them across multiple edge families in one answer view.",
    ),
    "q022": (
        "Q022 · Most-Connected Zones by Airflow Outcome",
        "GASL can organize zone-outcome support into grouped evidence rows so the final answer reflects many connected traces rather than one dominant passage.",
        "RAG can mention airflow outcomes, but it is weaker at synthesizing the most-connected zones from all available graph evidence.",
    ),
    "q032": (
        "Q032 · HVAC Frontier: Zones vs Pressure Evidence",
        "GASL can hold two evidence axes in view at once and expose a tradeoff frontier instead of flattening the question to one retrieved example.",
        "RAG can retrieve strong HVAC snippets, but it rarely computes the multi-criterion frontier itself.",
    ),
    "q033": (
        "Q033 · Air Distribution Frontier: Tracer vs Zone Breadth",
        "GASL can trace a frontier across competing evidence dimensions and keep the result grounded in graph-wide structure.",
        "RAG can surface examples from each side, but it does not naturally compute a frontier across the entire graph.",
    ),
    "q037": (
        "Q037 · Biosensor Platform Breadth",
        "GASL can evaluate breadth across pathogen targets, signal types, and validation evidence in one traversal.",
        "RAG can retrieve a few platforms, but it does not naturally synthesize a breadth ranking over all three dimensions.",
    ),
    "q040": (
        "Q040 · Biosensor Platforms by Pathogen Outcome",
        "GASL can organize platform-pathogen evidence into grouped rows before final synthesis.",
        "RAG may retrieve relevant pathogen mentions, but it is weaker at grouping them consistently by platform.",
    ),
    "q049": (
        "Q049 · Biosensor Platform Frontier",
        "GASL exposes a validation-vs-breadth frontier by organizing control-level evidence records before synthesis.",
        "RAG can retrieve strong individual platforms, but it does not naturally trace the frontier across them.",
    ),
    "q058": (
        "Q058 · Pathogens by Environmental Condition",
        "GASL can summarize environmental-condition support as grouped evidence rather than a loose list of pathogens.",
        "RAG can retrieve condition-specific passages, but it is weaker at whole-graph grouped summaries.",
    ),
    "q063": (
        "Q063 · Environmental-Condition Breadth Distribution",
        "GASL computes the full breadth distribution over pathogens rather than inferring it from a thin slice of text.",
        "RAG can cite examples, but it does not naturally compute graph-wide distribution statistics.",
    ),
    "q067": (
        "Q067 · Pathogen Frontier: Conditions vs Viability",
        "GASL can track a tradeoff frontier between environmental breadth and viability-state breadth using whole-graph structure.",
        "RAG can retrieve condition/viability examples, but it rarely computes the frontier itself.",
    ),
    "q004": (
        "Q004 · Best-Supported Controls by Outcome",
        "GASL can organize outcome-linked support into grouped evidence rows and then synthesize the strongest control-outcome patterns.",
        "RAG may surface a few supporting passages, but it is not naturally aligned to grouped control-outcome summaries across the whole graph.",
    ),
    "q009": (
        "Q009 · Pathogen-Coverage Distribution",
        "GASL computes a whole-graph pathogen-coverage distribution instead of inferring it from a thin slice of retrieved text.",
        "RAG may cite a few controls or pathogens, but it does not guarantee a graph-wide coverage profile.",
    ),
    "q013": (
        "Q013 · Tradeoff Frontier: Validation vs Burden",
        "GASL can expose a tradeoff frontier by organizing the evidence into comparable control-level records before synthesis.",
        "RAG can retrieve strong individual controls, but it does not naturally trace a frontier across competing evidence dimensions.",
    ),
}


def _trace_demo_from_qid(qid: str) -> Dict[str, Any]:
    title, why_gasl_wins, rag_blind_spot = SELECTED_TRACE_DEMO_CONFIG[qid]
    return _trace_backed_engineering_demo(qid, title, why_gasl_wins, rag_blind_spot)


@lru_cache(maxsize=1)
def get_demo_catalog() -> List[Dict[str, Any]]:
    trace_demos = []
    for qid in DEMO_SHORTLIST_12:
        try:
            trace_demos.append(_trace_demo_from_qid(qid))
        except Exception as exc:
            logger.warning("Skipping demo %s from curated catalog: %s", qid, exc)
    return trace_demos + [
        _domain_frequency_demo(),
        _confounder_span_demo(),
        _control_breadth_demo(),
    ]


@lru_cache(maxsize=1)
def get_paper_style_demo_catalog() -> List[Dict[str, Any]]:
    needed = ["q001", "q004", "q007", "q009", "q013", "q019"]
    base = { _trace_demo_from_qid(qid)["id"]: _trace_demo_from_qid(qid) for qid in needed }

    def focus(base_id: str, limit: int = 12) -> list[str]:
        return _replay_focus_nodes(base[base_id]["replay"], limit)

    q001_view = _first_answer_view_event(base["engineering-q001"]["replay"])
    q007_view = _first_answer_view_event(base["engineering-q007"]["replay"])
    q004_view = _first_answer_view_event(base["engineering-q004"]["replay"])
    q009_view = _first_answer_view_event(base["engineering-q009"]["replay"])

    symbolism_nodes = focus("engineering-q001", 14)
    camera_nodes = focus("engineering-q013", 18)
    sound_nodes = focus("engineering-q007", 15)
    bang_nodes = focus("engineering-q004", 20)
    archive_nodes = focus("hospital_environment-q019", 15)
    ending_nodes = focus("engineering-q009", 14)

    demos = [
        _paper_style_variant(
            base["engineering-q001"],
            demo_id="paper-symbolism-metaphor",
            visual_style="symbolism",
            title="Paper Style · Symbolism & Metaphor",
            why_choice="The opening treats the hospital as a breathing organism, so the graph first pulses through zones before it names the winning controls.",
            style_pitch="Metaphorical opener: breathe the graph in and out before the explicit evidence work begins.",
            opener_events=[
                _event(400, "gasl_step", {
                    "command_type": "INIT",
                    "status": "running",
                    "command": "Open with a metaphorical frame: hospital zones breathe as evidence gathers",
                    "story_kicker": "Symbolism",
                    "story_title": "A hospital breathes through its zones",
                    "story_body": "Before the system names any control, the opening frames the hospital as a living space whose zones expand and contract under different interventions.",
                }),
                _event(520, "gasl_highlight", {
                    "nodes": symbolism_nodes[:6],
                    "edges": [],
                    "command_type": "FIND",
                    "status": "success",
                    "command": "Pulse the first set of zone-linked control neighborhoods",
                    "story_title": "The graph inhales",
                    "story_body": "This pass is about atmosphere and theme rather than answer order. The opening suggests breadth before it quantifies it.",
                }),
                _event(540, "gasl_highlight", {
                    "nodes": symbolism_nodes[6:12],
                    "edges": [],
                    "command_type": "FIND",
                    "status": "success",
                    "command": "Counter-pulse a second ring of neighborhoods",
                    "story_title": "The graph exhales",
                    "story_body": "A second pulse makes the graph feel alive and sets up the later notion of a validation footprint stretching across many zones.",
                }),
            ],
            delay_factor=1.0,
        ),
        _paper_style_variant(
            base["engineering-q013"],
            demo_id="paper-camera-eye",
            visual_style="camera-eye",
            title="Paper Style · Camera Eye",
            why_choice="The opening is camera-led instead of text-led: the viewer learns the tradeoff landscape by being flown across it before the labels settle.",
            style_pitch="Camera-led opener: a guided tour across frontier candidates before the evidence widgets fully appear.",
            opener_events=[
                _event(300, "gasl_step", {
                    "command_type": "INIT",
                    "status": "running",
                    "command": "Use the camera itself as the narrator",
                    "story_kicker": "Camera eye",
                    "story_title": "Show the terrain before the text explains it",
                    "story_body": "Instead of starting with a dense panel, the opener lets the camera reveal the frontier through motion, scale, and proximity.",
                }),
                _event(900, "gasl_highlight", {
                    "nodes": camera_nodes[:7],
                    "edges": [],
                    "command_type": "GRAPHWALK",
                    "status": "success",
                    "command": "Long-take sweep across one side of the frontier",
                    "story_title": "First sweep",
                    "story_body": "The camera gives one long look before the interface starts naming what matters.",
                }),
                _event(900, "gasl_highlight", {
                    "nodes": camera_nodes[7:14],
                    "edges": [],
                    "command_type": "GRAPHWALK",
                    "status": "success",
                    "command": "Continue the same take across a second frontier region",
                    "story_title": "Second sweep",
                    "story_body": "A second slow sweep establishes spatial context, so the later ranking feels discovered rather than merely announced.",
                }),
            ],
            delay_factor=0.92,
        ),
        _paper_style_variant(
            base["engineering-q007"],
            demo_id="paper-creative-sound",
            visual_style="creative-sound",
            title="Paper Style · Creative Sound",
            why_choice="This variant turns support-count accumulation into a rhythmic opener, so the distribution feels like it is being scored into shape rather than simply filled.",
            style_pitch="Rhythmic opener: a visual equalizer and beat-like pulses build the distribution before the final statistics settle.",
            opener_events=[
                _event(320, "gasl_step", {
                    "command_type": "INIT",
                    "status": "running",
                    "command": "Open rhythmically: count pulses stand in for a soundtrack",
                    "story_kicker": "Creative sound",
                    "story_title": "Let counting feel musical",
                    "story_body": "The opening uses rhythm, repetition, and beat-like pulses so the viewer feels a distribution being constructed instead of merely reading a histogram.",
                }),
                _event(420, "gasl_highlight", {
                    "nodes": sound_nodes[:5],
                    "edges": [],
                    "command_type": "FIND",
                    "status": "success",
                    "command": "Beat 1 · first count cluster enters",
                    "story_title": "Beat one",
                    "story_body": "The first cluster sets the tempo: count, pause, count, pause.",
                }),
                _event(420, "gasl_highlight", {
                    "nodes": sound_nodes[5:10],
                    "edges": [],
                    "command_type": "FIND",
                    "status": "success",
                    "command": "Beat 2 · a second cluster syncs with the first",
                    "story_title": "Beat two",
                    "story_body": "A second cluster reinforces the rhythm so later aggregation feels like a scored progression rather than a static tally.",
                }),
                _event(320, "answer_view", {
                    **(q007_view["payload"] if q007_view else {"kicker": "Early histogram", "title": "Histogram onset", "view_kind": "distribution", "view_payload": {}, "selection_rationale": ""}),
                    "story_title": "The first bars land on the beat",
                    "story_body": "The equalizer-like opener gives the histogram a cadence before the full statistics appear.",
                }),
            ],
            delay_factor=0.96,
        ),
        _paper_style_variant(
            base["engineering-q004"],
            demo_id="paper-big-bang",
            visual_style="big-bang",
            title="Paper Style · Big Bang",
            why_choice="The opening uses abrupt contrast and a sudden evidence burst, so the viewer gets surprise first and structured explanation second.",
            style_pitch="Shock opener: a sudden subgraph burst and fast contrast snap before the grouped evidence organizes itself.",
            opener_events=[
                _event(220, "gasl_step", {
                    "command_type": "INIT",
                    "status": "running",
                    "command": "Open with a sharp contrast change and evidence burst",
                    "story_kicker": "Big bang",
                    "story_title": "Start with impact, then explain it",
                    "story_body": "A rapid visual burst creates curiosity first. The opening withholds the tidy summary until after the surprise has landed.",
                }),
                _event(180, "gasl_highlight", {
                    "nodes": bang_nodes[:10],
                    "edges": [],
                    "command_type": "FIND",
                    "status": "success",
                    "command": "Burst one · a wide answer-bearing subgraph flashes in",
                    "story_title": "Impact frame",
                    "story_body": "The opener hits hard: a lot of evidence arrives at once so the graph feels larger than the eventual grouped rows.",
                }),
                _event(180, "gasl_highlight", {
                    "nodes": bang_nodes[10:20],
                    "edges": [],
                    "command_type": "GRAPHWALK",
                    "status": "success",
                    "command": "Burst two · a second ring reinforces the surprise",
                    "story_title": "Aftershock",
                    "story_body": "A second burst makes the opener feel explosive rather than merely quick.",
                }),
                _event(320, "answer_view", {
                    **(q004_view["payload"] if q004_view else {"kicker": "Outcome burst", "title": "Outcome rows appear", "view_kind": "grouped_summary", "view_payload": {}, "selection_rationale": ""}),
                    "story_title": "Now the evidence starts to sort itself",
                    "story_body": "Only after the shock does the opener let the grouped evidence rows become readable.",
                }),
            ],
            delay_factor=0.94,
        ),
        _paper_style_variant(
            base["hospital_environment-q019"],
            demo_id="paper-old-footage",
            visual_style="old-footage",
            title="Paper Style · Old Footage",
            why_choice="This variant frames the airflow/pressure story like an archival systems reel, using patina and title cards before the graph modernizes into computation.",
            style_pitch="Archival opener: monochrome grain, title-card pacing, then a fade into modern graph calculation.",
            opener_events=[
                _event(500, "gasl_step", {
                    "command_type": "INIT",
                    "status": "running",
                    "command": "Open like an archival systems reel",
                    "story_kicker": "Old footage",
                    "story_title": "Archive the problem first",
                    "story_body": "The opener implies institutional memory and system history before it switches to present-tense analysis.",
                }),
                _event(600, "gasl_highlight", {
                    "nodes": archive_nodes[:7],
                    "edges": [],
                    "command_type": "FIND",
                    "status": "success",
                    "command": "Title-card pass · the first archival cluster appears",
                    "story_title": "Frame one",
                    "story_body": "A slower title-card rhythm lets the viewer absorb the setting before the interface fully wakes up.",
                }),
                _event(650, "gasl_highlight", {
                    "nodes": archive_nodes[7:14],
                    "edges": [],
                    "command_type": "GRAPHWALK",
                    "status": "success",
                    "command": "Archival sweep · the system map broadens",
                    "story_title": "Frame two",
                    "story_body": "This second pass keeps the pace measured, like old footage being advanced through a projector.",
                }),
            ],
            delay_factor=0.98,
        ),
        _paper_style_variant(
            base["engineering-q009"],
            demo_id="paper-ending-first",
            visual_style="ending-first",
            title="Paper Style · Ending First",
            why_choice="This variant gives away the destination immediately, then rewinds into the graph work so the viewer watches the answer earn itself.",
            style_pitch="Answer-first opener: reveal the destination immediately, then rewind into the evidence that justifies it.",
            opener_events=[
                _event(260, "gasl_step", {
                    "command_type": "INIT",
                    "status": "running",
                    "command": "Open by revealing the destination before the route",
                    "story_kicker": "Ending first",
                    "story_title": "Show the destination, then rewind",
                    "story_body": "The viewer sees the eventual shape of the answer first, then spends the rest of the clip learning how the graph earned it.",
                }),
                _event(360, "answer_view", {
                    **(q009_view["payload"] if q009_view else {"kicker": "Destination first", "title": "Final distribution preview", "view_kind": "distribution", "view_payload": {}, "selection_rationale": ""}),
                    "story_title": "The ending is shown up front",
                    "story_body": "The opening reveals the final form of the answer before it rewinds into the actual traversal that justifies it.",
                }),
                _event(460, "gasl_highlight", {
                    "nodes": ending_nodes[:8],
                    "edges": [],
                    "command_type": "GRAPHWALK",
                    "status": "success",
                    "command": "Rewind into the first evidence region",
                    "story_title": "Now go back and earn it",
                    "story_body": "After revealing the endpoint, the opener drops back into the graph so the answer can be earned rather than simply stated.",
                }),
            ],
            delay_factor=0.96,
        ),
    ]
    return demos


@lru_cache(maxsize=1)
def get_symbolism_shortlist_demo_catalog() -> List[Dict[str, Any]]:
    base = {demo["id"]: demo for demo in get_demo_catalog()}
    demos: list[Dict[str, Any]] = []
    for qid in DEMO_SHORTLIST_12:
        base_id = {
            "haiqu_engineering_controls": f"engineering-{qid}",
            "haiqu_hospital_environment": f"hospital_environment-{qid}",
            "haiqu_biosensor_detection": f"biosensor_detection-{qid}",
            "haiqu_aerosol_exposure": f"aerosol_exposure-{qid}",
        }
        candidate = None
        for demo in base.values():
            if demo["id"].endswith(qid):
                candidate = demo
                break
        if candidate is None:
            continue
        focus_nodes = _replay_focus_nodes(candidate["replay"], 14)
        demos.append(_paper_style_variant(
            candidate,
            demo_id=f"paper-symbolism-{qid}",
            visual_style="symbolism",
            title=f"Symbolism Variant · {candidate['title']}",
            why_choice="This opener leans on atmosphere and metaphor first, then lets the explicit evidence work catch up.",
            style_pitch="A metaphor-first opening: zone- and control-neighborhoods pulse into view before the quantitative evidence fully settles.",
            opener_events=[
                _event(400, "gasl_step", {
                    "command_type": "INIT",
                    "status": "running",
                    "command": "Open with a metaphorical frame: neighborhoods expand and contract as evidence gathers",
                    "story_kicker": "Question",
                    "story_title": "The graph breathes before it counts",
                    "story_body": "The opening frames the problem as a living system first, then lets the explicit evidence accumulation explain what that system means.",
                }),
                _event(520, "gasl_highlight", {
                    "nodes": focus_nodes[:6],
                    "edges": [],
                    "command_type": "FIND",
                    "status": "success",
                    "command": "First metaphorical pulse across the active neighborhoods",
                    "story_title": "The graph inhales",
                    "story_body": "The first pass is about atmosphere and thematic shape rather than immediate answer order.",
                }),
                _event(540, "gasl_highlight", {
                    "nodes": focus_nodes[6:12],
                    "edges": [],
                    "command_type": "FIND",
                    "status": "success",
                    "command": "Second pulse extends the same frame into a wider ring of evidence",
                    "story_title": "The graph exhales",
                    "story_body": "A second pulse widens the metaphor so the later evidence views feel discovered rather than abruptly introduced.",
                }),
            ],
            delay_factor=1.0,
        ))
    return demos


def get_demo(demo_id: str) -> Dict[str, Any] | None:
    for demo in get_demo_catalog():
        if demo["id"] == demo_id:
            return demo
    for demo in get_paper_style_demo_catalog():
        if demo["id"] == demo_id:
            return demo
    for demo in get_symbolism_shortlist_demo_catalog():
        if demo["id"] == demo_id:
            return demo
    return None
