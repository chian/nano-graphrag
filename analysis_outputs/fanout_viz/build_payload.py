"""Reduce the extracted rollout trees to one compact payload the slides can load.

Keeps the tree exact down to the probe / source-table grain and folds the chunk
layer into per-parent counts, so an icicle stays readable and the file stays
small. Also emits the per-page controller trace and the yield Pareto.
"""

import json
import os
import collections

RUNS = [
    ("amr_mic_incremental_argo_20260916_v01", "AMR / MIC", "isolate_antimicrobial_susceptibility"),
    ("earthquake_firecrawl_live_20260904_v22_learning", "Quake v22 learning", "earthquake_impacts"),
    ("earthquake_firecrawl_live_20260906_v25_relaxed_volume", "Quake v25 relaxed", "earthquake_impacts"),
    ("earthquake_firecrawl_live_20260902_v17_fast_continue", "Quake v17 continue", "earthquake_impacts"),
    ("earthquake_firecrawl_argo_20260913_v01", "Quake argo v01", "earthquake_impacts"),
    ("earthquake_firecrawl_live_20260901_v15", "Quake v15", "earthquake_impacts"),
]

SHORT = {
    "llm_initial": "initial",
    "catalog_source_shift": "catalog shift",
    "target_source_shift": "target shift",
    "catalog_broad_review": "broad review",
    "catalog_terminology_swap": "term swap",
}


CODE = {
    "run": "R",
    "strategy": "S",
    "search": "Q",
    "page": "P",
    "lexical_probe": "L",
    "source_table": "T",
    "chunk": "C",
}


def fold(node):
    """Return a slim node; chunk children collapse into counts on the parent."""
    kids = node.get("children", [])
    chunks = [c for c in kids if c["level"] == "chunk"]
    rest = [c for c in kids if c["level"] != "chunk"]

    out = {"l": CODE[node["level"]], "k": node["key"]}
    if chunks:
        out["c"] = len(chunks)
        out["cc"] = sum(c["credits"] for c in chunks)
        out["cf"] = sum(1 for c in chunks if c["failed"])
    if node["level"] == "page":
        out["f"] = node["fate"]
        out["o"] = node["order"]
        out["r"] = node["rank"]
        out["a"] = node["attributions"]
        out["g"] = node["guesses"]
    if node["level"] == "search":
        out["q"] = node["query"]
        out["h"] = node["provider_hits"]
        out["s"] = node["accepted_sources"]
        out["e"] = node["ended_by"]
    if node["level"] == "strategy":
        out["fam"] = SHORT.get(node.get("family", ""), node.get("family", ""))
    if node["level"] in ("lexical_probe", "source_table"):
        out["q"] = (node.get("query") or "")[:110]
        out["n"] = node.get("findings", 0)
    if rest:
        out["ch"] = [fold(c) for c in rest]
    return out


def build(run):
    tree = json.load(open(os.path.join("data", run + ".json")))

    levels = collections.Counter()
    fates = collections.Counter()
    chunk_credits = 0
    chunk_n = 0
    trace = []
    pages = []

    def walk(n):
        nonlocal chunk_credits, chunk_n
        levels[n["level"]] += 1
        if n["level"] == "chunk":
            chunk_n += 1
            chunk_credits += n["credits"]
        if n["level"] == "page":
            fates[n["fate"]] += 1
            pages.append(n)
        for c in n.get("children", []):
            walk(c)

    walk(tree)

    strat_of = {}
    for s in tree["children"]:
        for se in s["children"]:
            strat_of[se["key"]] = s["key"]
            for p in se["children"]:
                num = p["num"]
                trace.append({
                    "o": p["order"],
                    "s": s["key"],
                    "t": se["key"],
                    "n": num["samples"],
                    "ob": (num["observed"] or [None])[0],
                    "ra": (num["rarefied"] or [None])[0],
                    "ex": (num["expected"] or [None])[0],
                    "re": (num["remaining"] or [None])[0],
                    "v": num["outcome"],
                    "a": p["attributions"],
                    "f": p["fate"],
                })

    yields = sorted((p["attributions"] for p in pages), reverse=True)
    total_attr = sum(yields) or 1
    cum = 0
    pareto = []
    for i, y in enumerate(yields, start=1):
        cum += y
        pareto.append([round(100 * i / len(yields), 2), round(100 * cum / total_attr, 2)])

    searches = []
    for s in tree["children"]:
        for se in s["children"]:
            searches.append({
                "strategy": s["key"],
                "fam": SHORT.get(s.get("family", ""), s.get("family", "")),
                "task": se["key"],
                "query": se["query"],
                "hits": se["provider_hits"],
                "accepted": se["accepted_sources"],
                "pages": se["totals"]["pages"],
                "attrs": se["totals"]["attributions"],
                "credits": se["totals"]["credits"],
                "ended_by": se["ended_by"],
            })

    return {
        "run": run,
        "levels": dict(levels),
        "fates": dict(fates),
        "depth": tree["totals"]["depth"],
        "nodes": tree["totals"]["nodes"],
        "chunks": chunk_n,
        "chunk_credits": chunk_credits,
        "attrs": tree["totals"]["attributions"],
        "searches": searches,
        "trace": trace,
        "pareto": pareto[:: max(1, len(pareto) // 220)],
        "tree": fold(tree),
    }


payload = {"runs": []}
for run, label, table in RUNS:
    if not os.path.exists(os.path.join("data", run + ".json")):
        continue
    d = build(run)
    d["label"] = label
    d["table"] = table
    payload["runs"].append(d)

dest = "payload.json"
json.dump(payload, open(dest, "w"), separators=(",", ":"))
print("%.2f MB" % (os.path.getsize(dest) / 1e6))
for d in payload["runs"]:
    print("%-52s depth=%d nodes=%d chunks=%d credits=%d attrs=%d searches=%d"
          % (d["run"], d["depth"], d["nodes"], d["chunks"], d["chunk_credits"], d["attrs"], len(d["searches"])))
