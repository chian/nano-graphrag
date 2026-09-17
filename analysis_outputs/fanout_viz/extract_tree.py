"""Extract the nested rollout tree from a question_runs directory.

Reads answers/acquisition_page_detail.jsonl (one record per page unit, in
processing order) plus the checkpoint_state frontier records (search queries
and provider hit counts), and emits one compact JSON tree per run:

    run -> strategy -> search -> page -> {lexical_probe | source_table} -> chunk

Every node carries the numbers the controller actually saw at that point:
observed / rarefied / expected / remaining results and the verdict outcome.
"""

import glob
import json
import os
import sys


def band(b):
    """Flatten a numeric band to (value, lower, upper) or None when insufficient."""
    if not isinstance(b, dict):
        return None
    if b.get("status_code", -1) != 0:
        return None
    return [b.get("value"), b.get("lower"), b.get("upper")]


def queries_for(run_dir):
    """task_id -> {query, op, hits, accepted} from every frontier checkpoint."""
    out = {}
    for path in sorted(glob.glob(os.path.join(run_dir, "checkpoint_state", "*", "frontier.json"))):
        try:
            frontier = json.load(open(path))["search_frontier"]
        except (ValueError, KeyError, OSError):
            continue
        for rec in frontier.get("completed_task_records", []) + frontier.get("pending_task_records", []):
            tid = rec.get("task_id")
            if not tid or tid in out:
                continue
            out[tid] = {
                "query": rec.get("query", ""),
                "op": rec.get("expansion_op", ""),
                "hits": rec.get("firecrawl_hits", 0),
                "accepted": len(rec.get("accepted_source_ids", []) or []),
                "gap": rec.get("gap", ""),
            }
    return out


def episode_ends(run_dir):
    """scope path tuple -> {units_consumed, ended_by} from completed episodes."""
    out = {}
    for path in sorted(glob.glob(os.path.join(run_dir, "checkpoint_state", "*", "completed_episode.json"))):
        try:
            doc = json.load(open(path))
        except (ValueError, OSError):
            continue
        rec = doc.get("episode_record", doc)
        stack = [rec]
        while stack:
            node = stack.pop()
            key = tuple(tuple(p) for p in node.get("path", []))
            if key:
                out[key] = {
                    "units": node.get("units_consumed", 0),
                    "ended_by": node.get("ended_by", ""),
                    "end_reason": node.get("end_reason", ""),
                }
            for unit in node.get("units", []):
                child = unit.get("child")
                if child:
                    stack.append(child)
    return out


def page_fate(fate):
    return fate.get("extraction") or fate.get("mechanical") or "unknown"


def build(run_dir):
    run_id = os.path.basename(run_dir.rstrip("/"))
    detail = os.path.join(run_dir, "answers", "acquisition_page_detail.jsonl")
    queries = queries_for(run_dir)
    ends = episode_ends(run_dir)

    root = {"level": "run", "key": run_id, "children": []}
    strategies = {}
    searches = {}
    page_index = 0

    for line in open(detail):
        rec = json.loads(line)
        page_index += 1
        skey = rec["strategy_key"]
        tid = rec["task_id"]

        if skey not in strategies:
            node = {
                "level": "strategy",
                "key": skey,
                "family": rec["strategy_family"],
                "children": [],
            }
            strategies[skey] = node
            root["children"].append(node)

        if (skey, tid) not in searches:
            meta = queries.get(tid, {})
            path_key = (("run", run_id), ("strategy", skey), ("search", tid))
            end = ends.get(path_key, {})
            node = {
                "level": "search",
                "key": tid,
                "query": meta.get("query", ""),
                "op": meta.get("op", rec["strategy_family"]),
                "provider_hits": meta.get("hits", 0),
                "accepted_sources": meta.get("accepted", 0),
                "ended_by": end.get("ended_by", ""),
                "children": [],
            }
            searches[(skey, tid)] = node
            strategies[skey]["children"].append(node)

        snap = rec.get("numerical_snapshot_after", {}) or {}
        est = snap.get("incidence_estimate", {}) or {}
        verdict = snap.get("controller_verdict", {}) or {}

        page = {
            "level": "page",
            "key": rec["unit_label"],
            "order": page_index,
            "rank": rec.get("rank", 0),
            "fate": page_fate(rec.get("fate", {})),
            "counts": bool(rec.get("counts_toward_verdict")),
            "chars": rec.get("text_chars", 0),
            "attributions": len(rec.get("attributions") or []),
            "guesses": rec.get("guess_count", 0),
            "num": {
                "samples": est.get("incidence_samples", 0),
                "q1": est.get("q1"),
                "q2": est.get("q2"),
                "observed": band(est.get("observed_results")),
                "rarefied": band(est.get("rarefied_results")),
                "expected": band(est.get("expected_results")),
                "remaining": band(est.get("remaining_results")),
                "outcome": verdict.get("outcome", ""),
                "stop": bool(verdict.get("stop")),
                "flat_streak": verdict.get("flat_streak", 0),
            },
            "children": [],
        }

        chunks_by_probe = {}
        loose_chunks = []
        for ch in rec.get("chunk_encounters", []) or []:
            slim = {
                "level": "chunk",
                "key": ch.get("chunk_id", "")[-8:],
                "credits": ch.get("credits_minted", 0),
                "new": ch.get("new_within_page", 0),
                "repeats": ch.get("repeats_within_page", 0),
                "failed": bool(ch.get("failed")),
                "chars": (ch.get("end_offset", 0) - ch.get("start_offset", 0)),
            }
            pk = ch.get("probe_key")
            if pk:
                chunks_by_probe.setdefault(pk, []).append(slim)
            else:
                loose_chunks.append(slim)

        for probe in rec.get("lexical_probes", []) or []:
            pk = probe.get("probe_key", "")
            page["children"].append({
                "level": "lexical_probe",
                "key": pk,
                "query": probe.get("query", ""),
                "chunks_processed": probe.get("chunks_processed", 0),
                "findings": probe.get("distinct_findings", 0),
                "ended_by": probe.get("ended_by", ""),
                "children": chunks_by_probe.get(pk, []),
            })

        for i, stq in enumerate(rec.get("source_table_queries") or [], start=1):
            q = stq.get("query", {}) or {}
            page["children"].append({
                "level": "source_table",
                "key": "tq-%04d" % i,
                "query": ", ".join(q.get("required_columns", []) or []),
                "entities": stq.get("entities_selected", 0),
                "findings": stq.get("distinct_findings", 0),
                "new": stq.get("new_findings_within_page", 0),
                "repeats": stq.get("repeat_findings_within_page", 0),
                "remaining_entities": stq.get("remaining_entities", 0),
                "children": [],
            })

        if loose_chunks:
            page["children"].extend(loose_chunks)

        searches[(skey, tid)]["children"].append(page)

    return root


def rollup(node):
    """Attach subtree totals to every node, bottom up."""
    pages = 1 if node["level"] == "page" else 0
    credits = node.get("credits", 0) if node["level"] == "chunk" else 0
    attrs = node.get("attributions", 0) if node["level"] == "page" else 0
    leaves = 0 if node.get("children") else 1
    for child in node.get("children", []):
        sub = rollup(child)
        pages += sub["pages"]
        credits += sub["credits"]
        attrs += sub["attributions"]
        leaves += sub["leaves"]
    node["totals"] = {
        "pages": pages,
        "credits": credits,
        "attributions": attrs,
        "leaves": leaves,
        "nodes": 1 + sum(c["totals"]["nodes"] for c in node.get("children", [])),
        "depth": 1 + max([c["totals"]["depth"] for c in node.get("children", [])] or [0]),
    }
    return node["totals"]


if __name__ == "__main__":
    base = "/home/chia/repos/nano-graphrag/question_runs"
    out_dir = "/home/chia/repos/nano-graphrag/analysis_outputs/fanout_viz/data"
    os.makedirs(out_dir, exist_ok=True)
    for run in sys.argv[1:]:
        tree = build(os.path.join(base, run))
        rollup(tree)
        dest = os.path.join(out_dir, run + ".json")
        json.dump(tree, open(dest, "w"), separators=(",", ":"))
        t = tree["totals"]
        print("%-52s depth=%d nodes=%-6d pages=%-5d chunk-credits=%-6d attrs=%d  %.1f MB"
              % (run, t["depth"], t["nodes"], t["pages"], t["credits"], t["attributions"],
                 os.path.getsize(dest) / 1e6))
