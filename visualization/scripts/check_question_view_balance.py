#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize question-file balance by graph and target view.")
    parser.add_argument("question_file", help="Path to question-set JSON")
    args = parser.parse_args()

    payload = json.loads(Path(args.question_file).read_text(encoding="utf-8"))
    rows = payload.get("questions", [])
    by_graph: dict[str, Counter] = defaultdict(Counter)
    total = Counter()

    for row in rows:
        graph = row.get("graph", "UNKNOWN")
        target_view = row.get("metadata", {}).get("target_view", "UNSPECIFIED")
        by_graph[graph][target_view] += 1
        total[target_view] += 1

    print(f"Question file: {args.question_file}")
    print(f"Total questions: {len(rows)}\n")
    for graph, counts in sorted(by_graph.items()):
        print(graph)
        for view, n in sorted(counts.items()):
            print(f"  {view:16} {n}")
        print()
    print("TOTAL")
    for view, n in sorted(total.items()):
        print(f"  {view:16} {n}")


if __name__ == "__main__":
    main()
