"""
Batch runner for contrastive QA generation pipeline.

Reads a manifest file and processes papers sequentially with progress tracking.
Handles interruptions gracefully - manifest is updated after each paper.
"""

import json
import argparse
import subprocess
import sys
import signal
from pathlib import Path
from datetime import datetime
from typing import Optional

from manifest_utils import load_manifest, save_manifest, print_manifest_stats, get_manifest_stats


class BatchRunner:
    def __init__(self, manifest_file: Path, skip_flags: dict = None):
        """
        Initialize batch runner.

        Args:
            manifest_file: Path to manifest JSON file
            skip_flags: Dict of skip flags to pass to pipeline (e.g., {'skip_paper_fetching': True})
        """
        self.manifest_file = Path(manifest_file)
        self.manifest = load_manifest(self.manifest_file)
        self.skip_flags = skip_flags or {}
        self.interrupted = False

        # Handle Ctrl+C gracefully
        signal.signal(signal.SIGINT, self._handle_interrupt)

    def _handle_interrupt(self, signum, frame):
        """Handle interrupt signal."""
        print("\n\n⚠ Pipeline interrupted by user")
        self.interrupted = True

    def run(self, start_from: Optional[str] = None, limit: Optional[int] = None) -> None:
        """
        Run pipeline on papers in manifest.

        Args:
            start_from: Paper ID to resume from (skip earlier papers)
            limit: Maximum number of papers to process
        """
        papers = self.manifest["papers"]

        if start_from:
            # Find starting index
            start_idx = None
            for i, paper in enumerate(papers):
                if paper["id"] == start_from:
                    start_idx = i
                    break

            if start_idx is None:
                print(f"✗ ERROR: Paper not found: {start_from}")
                sys.exit(1)

            papers = papers[start_idx:]

        if limit:
            papers = papers[:limit]

        stats_start = get_manifest_stats(self.manifest)

        print(f"\n{'#'*70}")
        print(f"# BATCH PIPELINE RUNNER")
        print(f"{'#'*70}\n")

        print(f"Manifest: {self.manifest_file}")
        print(f"Domain: {self.manifest['domain']}")
        print(f"Papers to process: {len(papers)}\n")

        print(f"Pipeline settings:")
        for flag, value in self.skip_flags.items():
            if value:
                print(f"  --{flag.replace('_', '-')}")

        print(f"\n{'='*70}\n")

        processed = 0
        for i, paper in enumerate(papers, 1):
            if self.interrupted:
                print("\nSaving manifest before exit...")
                save_manifest(self.manifest, self.manifest_file)
                print("✓ Manifest saved")
                sys.exit(0)

            paper_id = paper["id"]
            paper_path = paper["path"]

            print(f"\n[{i}/{len(papers)}] Processing: {paper_id}")
            print(f"Path: {paper_path}")

            try:
                self._run_paper_pipeline(paper_path, paper)
                processed += 1
                print(f"✓ Completed")

            except subprocess.CalledProcessError as e:
                error_msg = f"Pipeline failed with exit code {e.returncode}"
                print(f"✗ {error_msg}")
                from manifest_utils import update_paper_status
                update_paper_status(self.manifest, paper_id, "failed", error_msg)

            except Exception as e:
                error_msg = f"{type(e).__name__}: {str(e)}"
                print(f"✗ {error_msg}")
                from manifest_utils import update_paper_status
                update_paper_status(self.manifest, paper_id, "failed", error_msg)

            # Save manifest after each paper
            save_manifest(self.manifest, self.manifest_file)

        print(f"\n{'='*70}")
        print(f"\nBatch processing complete!")
        print_manifest_stats(self.manifest)

    def _run_paper_pipeline(self, paper_path: str, paper: dict) -> None:
        """
        Run pipeline on a single paper.

        Args:
            paper_path: Path to paper file
            paper: Paper dict from manifest
        """
        cmd = [
            "python", "run_contrastive_pipeline.py",
            paper_path,
            "--domain", self.manifest["domain"],
            "--num-questions", "10",
        ]

        # Add skip flags
        if self.skip_flags.get("skip_assessment"):
            cmd.append("--skip-assessment")
        if self.skip_flags.get("skip_graph_creation"):
            cmd.append("--skip-graph-creation")
        if self.skip_flags.get("skip_query_generation"):
            cmd.append("--skip-query-generation")
        if self.skip_flags.get("skip_paper_fetching"):
            cmd.append("--skip-paper-fetching")
        if self.skip_flags.get("skip_graph_enrichment"):
            cmd.append("--skip-graph-enrichment")

        # Run pipeline
        result = subprocess.run(cmd, check=True)

        # Update manifest
        from manifest_utils import update_paper_status
        update_paper_status(self.manifest, paper["id"], "completed")


def main():
    parser = argparse.ArgumentParser(
        description="Batch runner for contrastive QA generation pipeline"
    )

    parser.add_argument(
        "manifest",
        help="Manifest JSON file"
    )

    parser.add_argument(
        "--start-from",
        help="Resume from specific paper ID"
    )

    parser.add_argument(
        "--limit",
        type=int,
        help="Process maximum N papers"
    )

    parser.add_argument(
        "--skip-assessment",
        action="store_true",
        help="Skip paper suitability assessment"
    )

    parser.add_argument(
        "--skip-graph-creation",
        action="store_true",
        help="Skip graph creation (use existing)"
    )

    parser.add_argument(
        "--skip-query-generation",
        action="store_true",
        help="Skip query generation"
    )

    parser.add_argument(
        "--skip-paper-fetching",
        action="store_true",
        help="Skip paper fetching with Firecrawl"
    )

    parser.add_argument(
        "--skip-graph-enrichment",
        action="store_true",
        help="Skip graph enrichment"
    )

    args = parser.parse_args()

    skip_flags = {
        "skip_assessment": args.skip_assessment,
        "skip_graph_creation": args.skip_graph_creation,
        "skip_query_generation": args.skip_query_generation,
        "skip_paper_fetching": args.skip_paper_fetching,
        "skip_graph_enrichment": args.skip_graph_enrichment,
    }

    runner = BatchRunner(Path(args.manifest), skip_flags)
    runner.run(start_from=args.start_from, limit=args.limit)


if __name__ == "__main__":
    main()
