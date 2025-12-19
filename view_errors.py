"""
View error logs from failed papers.
"""

import argparse
from pathlib import Path
from manifest_utils import load_manifest


def view_errors(manifest_file: Path, paper_id: str = None, tail_lines: int = 50):
    """View error logs for failed papers."""

    manifest = load_manifest(manifest_file)

    failed = [p for p in manifest['papers'] if p.get('status') == 'failed']

    if not failed:
        print("No failed papers found.")
        return

    if paper_id:
        # View specific paper
        paper = next((p for p in failed if p['id'] == paper_id), None)
        if not paper:
            print(f"Paper {paper_id} not found in failed papers.")
            return
        papers_to_show = [paper]
    else:
        # View all failed papers
        papers_to_show = failed[:10]  # Show first 10

    for paper in papers_to_show:
        paper_path = Path(paper['path'])
        log_file = paper_path.parent / ".qa_output" / paper['id'] / "logs" / "pipeline_error.log"

        print(f"\n{'='*70}")
        print(f"Paper: {paper['id']}")
        print(f"Error: {paper.get('error', 'Unknown')}")
        print(f"Log: {log_file}")
        print(f"{'='*70}")

        if log_file.exists():
            with open(log_file, 'r') as f:
                lines = f.readlines()

            if tail_lines and len(lines) > tail_lines:
                print(f"\n[... showing last {tail_lines} lines ...]")
                lines = lines[-tail_lines:]

            print(''.join(lines))
        else:
            print("Log file not found.")

    if not paper_id and len(failed) > 10:
        print(f"\n... and {len(failed) - 10} more failed papers")
        print(f"Use --paper-id to view a specific paper's log")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="View error logs from failed papers")

    parser.add_argument(
        "manifest",
        help="Manifest file"
    )

    parser.add_argument(
        "--paper-id",
        help="Specific paper ID to view (default: show all)"
    )

    parser.add_argument(
        "--tail",
        type=int,
        default=50,
        help="Number of lines to show from end of log (default: 50, 0=all)"
    )

    args = parser.parse_args()

    view_errors(Path(args.manifest), args.paper_id, args.tail)
