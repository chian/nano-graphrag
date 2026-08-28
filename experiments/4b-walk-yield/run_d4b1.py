"""D4B-1 runner: redundant-seed conditions through the executor path.

Disposable per experiments/README.md. Reads spec_d4b1.json, asserts
registration, runs three live executor sessions, writes results.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import networkx as nx  # noqa: E402

from experiments.registry import assert_registered  # noqa: E402

sys.path.insert(0, str(ROOT / "experiments" / "4b-walk-yield"))
from run_walks import run_condition  # noqa: E402  (reuses the executor route)

SPEC_PATH = ROOT / "experiments/runs/4b-walk-yield/spec_d4b1.json"
LOG_PATH = ROOT / "experiments/log/4B-D4B1-redundant-seeds.md"
OUT_DIR = ROOT / "experiments/runs/4b-walk-yield/out"


def node_dict(graph, node_id):
    data = dict(graph.nodes[node_id])
    return {"id": node_id, "data": {**data, "id": node_id}}


def neighbors(graph, n):
    return set(nx.all_neighbors(graph, n)) if graph.is_directed() else set(graph.neighbors(n))


def main() -> None:
    spec = json.loads(SPEC_PATH.read_text())
    assert_registered(LOG_PATH, spec)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    dense = nx.read_graphml(ROOT / "haiqu_graphs/v1/haiqu_aerosol_exposure/haiqu_aerosol_exposure_graph.graphml")
    sparse = nx.read_graphml(ROOT / "question_runs/earthquake_twograin_20260823_030001_r4/graphs/round_2.graphml")

    # D4B-1a: 40 degree-1 neighbors of the max-degree hub.
    hub = max(dense.degree, key=lambda kv: kv[1])[0]
    spokes = sorted(m for m in neighbors(dense, hub) if dense.degree(m) == 1)[:40]
    if len(spokes) < 40:
        raise SystemExit(f"dense hub has only {len(spokes)} degree-1 spokes")
    d1a_seeds = [node_dict(dense, n) for n in spokes]

    # D4B-1b: sparse hub + its 13 leaves twice.
    s_hub = "THE GLOBAL SIGNIFICANT EARTHQUAKE DATABASE"
    leaves = sorted(m for m in neighbors(sparse, s_hub) if sparse.degree(m) == 1)
    d1b_seeds = [node_dict(sparse, s_hub)] + [node_dict(sparse, n) for n in leaves] * 2

    # D4B-1c control: 40 distinct high-degree hubs' neighbors (one each).
    hubs = [n for n, d in sorted(dense.degree, key=lambda kv: kv[1], reverse=True)]
    control = []
    for h in hubs:
        if h == hub or h in spokes:
            continue
        control.append(h)
        if len(control) >= 40:
            break
    d1c_seeds = [node_dict(dense, n) for n in control]

    out = {"conditions": {}}
    out["conditions"]["d4b1a"] = run_condition(dense, "d4b1a", d1a_seeds)
    out["conditions"]["d4b1b"] = run_condition(sparse, "d4b1b", d1b_seeds)
    out["conditions"]["d4b1c"] = run_condition(dense, "d4b1c", d1c_seeds)

    (OUT_DIR / "results_d4b1.json").write_text(json.dumps(out, indent=2, default=str))
    for name, cond in out["conditions"].items():
        comp = (cond["results"][0] or {}).get("completeness") or {}
        wy = comp.get("walk_yield") or {}
        print(name, "| ended_by:", wy.get("ended_by"),
              "| units:", (wy.get("units") or {}).get("count"),
              "| bound_kind:", comp.get("bound_kind"),
              "| residual:", comp.get("residual"))


if __name__ == "__main__":
    main()
