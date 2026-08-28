"""4B live runner: scripted GRAPHWALK sessions over a real graph.

Disposable per experiments/README.md. Three conditions from the registered
spec: broad (verdict should cut), narrow (< min_observations, never cut by
yield), capped (node budget binds first). Broad and narrow run through the
full executor path (parser -> handler -> adapter -> state). The capped
condition drives the production `_walk` directly with a manipulated
`max_nodes`, because that number is an inline constant upstream and the
manipulation IS the condition; this route is disclosed in the results.

Analysis reads only what these sessions emit.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import networkx as nx  # noqa: E402

from experiments.registry import assert_registered  # noqa: E402
from gasl import GASLExecutor, NetworkXAdapter  # noqa: E402
from gasl.contracts import make_contract  # noqa: E402

SPEC_PATH = ROOT / "experiments/runs/4b-walk-yield/spec.json"
LOG_PATH = ROOT / "experiments/log/4B-walk-yield.md"
OUT_DIR = ROOT / "experiments/runs/4b-walk-yield/out"


def loud_llm_stub(*args, **kwargs):
    raise RuntimeError(
        "4B walk sessions must not consult a model; an LLM call was attempted"
    )


def build_executor(graph, state_file: Path) -> GASLExecutor:
    adapter = NetworkXAdapter(graph, graph_metadata={"experiment": "4B-walk-yield"})
    return GASLExecutor(adapter, loud_llm_stub, str(state_file), job_id="4b-walk")


def seed_nodes_for(graph) -> tuple[list[dict], list[dict]]:
    """Broad: a dense hub plus neighbors (>= 24 seeds). Narrow: 5 of them."""
    degrees = sorted(graph.degree, key=lambda kv: kv[1], reverse=True)
    hub = degrees[0][0]
    neighborhood = [hub] + list(graph.neighbors(hub))
    for node, _ in degrees[1:]:
        if len(neighborhood) >= 40:
            break
        if node not in neighborhood:
            neighborhood.append(node)
    broad = neighborhood[:40]
    if len(broad) < 24:
        raise SystemExit(f"graph too small for the broad condition: {len(broad)} seeds")

    def node_dict(node_id):
        data = dict(graph.nodes[node_id])
        return {"id": node_id, "data": {**data, "id": node_id}}

    broad_nodes = [node_dict(n) for n in broad]
    return broad_nodes, broad_nodes[:5]


def store_seeds(executor: GASLExecutor, nodes: list[dict]) -> None:
    contract = make_contract(
        payload_kind="nodes",
        data=nodes,
        label_field="data.entity_name",
        scope="current_rows_only",
        usable_by=["PROCESS", "GRAPHWALK", "SHOW", "SELECT"],
        grain_type="node",
        grain_keys=["id"],
        multiplicity_preserved=True,
    )
    executor.state_manager.store_variable_data(
        "seed_nodes",
        nodes,
        store_in_state=True,
        store_in_context=True,
        description="4B experiment seeds",
        contract=contract,
    )


def run_condition(graph, name: str, nodes: list[dict]) -> dict:
    state_file = OUT_DIR / f"state_{name}.json"
    executor = build_executor(graph, state_file)
    store_seeds(executor, nodes)
    plan = {
        "plan_id": f"4b-{name}",
        "why": "registered 4B walk-yield experiment; scripted, no model",
        "query": "4B walk yield experiment",
        "config": {"stop_on_error": True},
        "commands": [
            "GRAPHWALK from seed_nodes follow * depth 1 AS walk_rows",
        ],
    }
    result = executor.execute_plan(plan)
    return {
        "condition": name,
        "seeds_supplied": len(nodes),
        "route": "executor.execute_plan",
        "plan_result_status": result.get("status"),
        "results": [
            {
                "command": r.command,
                "status": r.status,
                "count": r.count,
                "completeness": (r.contract or {}).get("completeness"),
            }
            for r in result.get("results", [])
        ],
        "raw_result_keys": sorted(result.keys()),
    }


def run_capped(graph, nodes: list[dict]) -> dict:
    """Manipulated node budget through the production _walk."""
    from gasl.commands.graph_nav import GraphNavHandler

    adapter = NetworkXAdapter(graph, graph_metadata={"experiment": "4B-walk-yield"})
    handler = GraphNavHandler(
        state_store=None, context_store=None, adapter=adapter, llm_func=loud_llm_stub
    )
    walked, disclosure = handler._walk(
        nodes,
        [],
        1,
        source_cap=100,
        max_nodes=8,
        edge_cap=50,
    )
    return {
        "condition": "capped",
        "seeds_supplied": len(nodes),
        "route": "GraphNavHandler._walk direct (max_nodes manipulated; inline constant upstream)",
        "returned_rows": len(walked),
        "completeness": disclosure,
    }


def main() -> None:
    spec = json.loads(SPEC_PATH.read_text())
    assert_registered(LOG_PATH, spec)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    graph_path = ROOT / spec["runtime"]["graph"]
    graph = nx.read_graphml(graph_path)
    if graph.is_directed():
        pass
    broad, narrow = seed_nodes_for(graph)

    out = {
        "spec_fingerprint_source": str(SPEC_PATH),
        "graph": str(graph_path),
        "graph_nodes": graph.number_of_nodes(),
        "graph_edges": graph.number_of_edges(),
        "conditions": {},
    }
    out["conditions"]["broad"] = run_condition(graph, "broad", broad)
    out["conditions"]["narrow"] = run_condition(graph, "narrow", narrow)
    out["conditions"]["capped"] = run_capped(graph, broad)

    result_path = OUT_DIR / "results.json"
    result_path.write_text(json.dumps(out, indent=2, default=str))
    print(json.dumps({k: v for k, v in out.items() if k != "conditions"}, indent=2))
    for name, cond in out["conditions"].items():
        print(f"--- {name}: written")


if __name__ == "__main__":
    main()
