#!/usr/bin/env python3
"""
Monitor progress of question regeneration.

Run this in a separate terminal while regenerate_questions_from_graphs.py is running.

Usage:
    python monitor_regeneration.py /path/to/ASM_595/mSystems ecology
    python monitor_regeneration.py /path/to/ASM_595/mSystems ecology --watch  # Auto-refresh
    python monitor_regeneration.py /path/to/ASM_595/mSystems ecology --sample  # Show sample question
"""

import argparse
import json
import time
from pathlib import Path
from datetime import datetime


def find_output_files(base_dir: Path, domain: str, suffix: str = "_v2") -> list:
    """Find all regenerated question files."""
    results = []

    for paper_dir in base_dir.iterdir():
        if not paper_dir.is_dir():
            continue

        qa_output_dir = paper_dir / "source_files" / ".qa_output"
        if not qa_output_dir.exists():
            continue

        for paper_id_dir in qa_output_dir.iterdir():
            if not paper_id_dir.is_dir():
                continue

            domain_dir = paper_id_dir / domain
            output_file = domain_dir / f"contrastive_qa{suffix}.json"

            if output_file.exists():
                try:
                    with open(output_file) as f:
                        data = json.load(f)

                    results.append({
                        "paper_id": paper_id_dir.name,
                        "path": output_file,
                        "num_questions": data.get("num_questions", 0),
                        "settings": data.get("settings", {}),
                        "regenerated_at": data.get("regenerated_at", "unknown"),
                        "questions": data.get("questions", [])
                    })
                except (json.JSONDecodeError, IOError) as e:
                    results.append({
                        "paper_id": paper_id_dir.name,
                        "path": output_file,
                        "error": str(e)
                    })

    return results


def find_total_graphs(base_dir: Path, domain: str) -> int:
    """Count total available graphs for comparison."""
    count = 0

    for paper_dir in base_dir.iterdir():
        if not paper_dir.is_dir():
            continue

        qa_output_dir = paper_dir / "source_files" / ".qa_output"
        if not qa_output_dir.exists():
            continue

        for paper_id_dir in qa_output_dir.iterdir():
            if not paper_id_dir.is_dir():
                continue

            domain_dir = paper_id_dir / domain
            enriched = domain_dir / "enriched_graphs" / f"{domain}_enriched_graph.graphml"
            regular = domain_dir / "graphs" / f"{domain}_graph.graphml"

            if enriched.exists() or regular.exists():
                count += 1

    return count


def display_progress(base_dir: Path, domain: str, suffix: str = "_v2", show_sample: bool = False):
    """Display current progress."""
    outputs = find_output_files(base_dir, domain, suffix)
    total_graphs = find_total_graphs(base_dir, domain)

    print(f"\n{'='*60}")
    print(f"Question Regeneration Progress - {datetime.now().strftime('%H:%M:%S')}")
    print(f"{'='*60}")
    print(f"Base directory: {base_dir}")
    print(f"Domain: {domain}")
    print(f"Output suffix: {suffix}")
    print(f"{'='*60}\n")

    # Summary
    successful = [o for o in outputs if "error" not in o]
    failed = [o for o in outputs if "error" in o]
    total_questions = sum(o.get("num_questions", 0) for o in successful)

    print(f"Progress: {len(outputs)}/{total_graphs} papers processed")
    print(f"  - Successful: {len(successful)}")
    print(f"  - Failed: {len(failed)}")
    print(f"  - Remaining: {total_graphs - len(outputs)}")
    print(f"\nTotal questions generated: {total_questions}")

    if successful:
        avg_questions = total_questions / len(successful)
        print(f"Average questions per paper: {avg_questions:.1f}")

        # Show settings from latest
        latest = max(successful, key=lambda x: x.get("regenerated_at", ""))
        settings = latest.get("settings", {})
        print(f"\nSettings used:")
        print(f"  - Distractors: {settings.get('enrich_info_pieces', 'N/A')}")
        print(f"  - Graph depth: {settings.get('enrich_graph_depth', 'N/A')}")
        print(f"  - Max questions: {settings.get('max_questions', 'N/A')}")

    # Recent papers
    print(f"\n{'='*60}")
    print("Recent papers processed:")
    print(f"{'='*60}")

    # Sort by timestamp
    successful.sort(key=lambda x: x.get("regenerated_at", ""), reverse=True)

    for output in successful[:10]:
        timestamp = output.get("regenerated_at", "unknown")
        if timestamp != "unknown":
            try:
                dt = datetime.fromisoformat(timestamp)
                timestamp = dt.strftime("%H:%M:%S")
            except:
                pass

        print(f"  [{timestamp}] {output['paper_id']}: {output['num_questions']} questions")

    # Show sample question if requested
    if show_sample and successful:
        print(f"\n{'='*60}")
        print("Sample question from latest paper:")
        print(f"{'='*60}")

        latest = successful[0]
        questions = latest.get("questions", [])

        if questions:
            q = questions[0]
            print(f"\nPaper: {latest['paper_id']}")
            print(f"\nQuestion (truncated to 500 chars):")
            question_text = q.get("question", q.get("enriched_question", "N/A"))
            print(f"  {question_text[:500]}...")
            print(f"\nAnswer: {q.get('correct_answer', 'N/A')}")
            print(f"Enrichment pieces: {len(q.get('enrichment_pieces', []))}")
            print(f"Enrichment entities: {q.get('enrichment_entities', [])}")

    if failed:
        print(f"\n{'='*60}")
        print("Failed papers:")
        print(f"{'='*60}")
        for output in failed[:5]:
            print(f"  {output['paper_id']}: {output.get('error', 'unknown error')}")

    print()


def main():
    parser = argparse.ArgumentParser(description="Monitor question regeneration progress")
    parser.add_argument("base_directory", help="Base directory (e.g., ASM_595/mSystems)")
    parser.add_argument("domain", help="Domain (e.g., ecology)")
    parser.add_argument("--suffix", default="_v2", help="Output file suffix (default: _v2)")
    parser.add_argument("--watch", action="store_true", help="Auto-refresh every 30 seconds")
    parser.add_argument("--sample", action="store_true", help="Show sample question")
    parser.add_argument("--interval", type=int, default=30, help="Refresh interval in seconds (default: 30)")

    args = parser.parse_args()
    base_dir = Path(args.base_directory)

    if not base_dir.exists():
        print(f"Error: Directory not found: {base_dir}")
        return

    if args.watch:
        try:
            while True:
                # Clear screen
                print("\033[2J\033[H", end="")
                display_progress(base_dir, args.domain, args.suffix, args.sample)
                print(f"Auto-refreshing every {args.interval}s. Press Ctrl+C to stop.")
                time.sleep(args.interval)
        except KeyboardInterrupt:
            print("\nStopped.")
    else:
        display_progress(base_dir, args.domain, args.suffix, args.sample)


if __name__ == "__main__":
    main()
