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
    def __init__(self, manifest_file: Path, skip_flags: dict = None, enrich_info_pieces: int = 3, enrich_graph_depth: int = 1):
        """
        Initialize batch runner.

        Args:
            manifest_file: Path to manifest JSON file
            skip_flags: Dict of skip flags to pass to pipeline (e.g., {'skip_paper_fetching': True})
            enrich_info_pieces: Number of distracting facts to add per question (default: 3)
            enrich_graph_depth: Graph traversal depth for enrichment (default: 1)
        """
        self.manifest_file = Path(manifest_file)
        self.manifest = load_manifest(self.manifest_file)
        self.skip_flags = skip_flags or {}
        self.enrich_info_pieces = enrich_info_pieces
        self.enrich_graph_depth = enrich_graph_depth
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
        skipped = 0
        for i, paper in enumerate(papers, 1):
            if self.interrupted:
                print("\nSaving manifest before exit...")
                save_manifest(self.manifest, self.manifest_file)
                print("✓ Manifest saved")
                sys.exit(0)

            paper_id = paper["id"]
            paper_path = paper["path"]
            status = paper.get("status", "pending")

            # Skip already completed, failed, or unsuitable papers
            if status in ("completed", "failed", "unsuitable"):
                skipped += 1
                print(f"\n[{i}/{len(papers)}] Skipping ({status}): {paper_id}")
                continue

            # Skip papers that already failed suitability assessment for this domain
            suitability_file = Path(paper_path).parent / f"suitability_{self.manifest['domain']}.json"
            if suitability_file.exists():
                try:
                    with open(suitability_file) as f:
                        suitability = json.load(f)
                    if not suitability.get("suitable", True):
                        skipped += 1
                        print(f"\n[{i}/{len(papers)}] Skipping (unsuitable for {self.manifest['domain']}): {paper_id}")
                        # Update status to reflect this
                        from manifest_utils import update_paper_status
                        update_paper_status(self.manifest, paper_id, "unsuitable", suitability.get("reasoning", "Not suitable for domain"))
                        save_manifest(self.manifest, self.manifest_file)
                        continue
                except (json.JSONDecodeError, IOError):
                    pass  # If we can't read the file, proceed with processing

            print(f"\n[{i}/{len(papers)}] Processing: {paper_id}")
            print(f"Path: {paper_path}")

            try:
                self._run_paper_pipeline(paper_path, paper)
                processed += 1
                print(f"✓ Completed")

            except ConnectionError as e:
                # Fatal: LLM connection error detected
                print("\n" + "="*70)
                print("✗ FATAL: LLM connection error detected")
                print("="*70)
                print("This is likely a transient network/API issue.")
                print("Stopping batch processing to avoid wasting time.")
                print("Fix the connection issue and restart from this paper:")
                print(f"  python run_batch_pipeline.py {self.manifest_file} --start-from {paper_id}")
                print("="*70 + "\n")

                from manifest_utils import update_paper_status
                update_paper_status(self.manifest, paper_id, "pending", "Connection error - not attempted")
                save_manifest(self.manifest, self.manifest_file)
                sys.exit(1)

            except subprocess.CalledProcessError as e:
                # Extract error info if available
                if e.output:
                    try:
                        error_info = json.loads(e.output)
                        error_msg = error_info.get('message', f"Pipeline failed with exit code {e.returncode}")
                        log_file = error_info.get('log_file', 'unknown')
                        print(f"✗ {error_msg}")
                        print(f"   Error log saved to: {log_file}")
                    except:
                        error_msg = f"Pipeline failed with exit code {e.returncode}"
                        print(f"✗ {error_msg}")
                else:
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
        print(f"  Processed: {processed}")
        print(f"  Skipped (already completed): {skipped}")
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
            "--enrich-info-pieces", str(self.enrich_info_pieces),
            "--enrich-graph-depth", str(self.enrich_graph_depth)
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

        # Create error log directory
        paper_dir = Path(paper_path).parent
        error_log_dir = paper_dir / ".qa_output" / paper["id"] / "logs"
        error_log_dir.mkdir(parents=True, exist_ok=True)
        error_log_file = error_log_dir / "pipeline_error.log"

        # Run pipeline with real-time output streaming
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )

        # Capture output while streaming it to console
        output_lines = []
        for line in process.stdout:
            print(line, end='')  # Print in real-time
            output_lines.append(line)

        process.wait()

        # Save full output to log file
        full_output = ''.join(output_lines)
        with open(error_log_file, 'w') as f:
            f.write(f"Command: {' '.join(cmd)}\n")
            f.write(f"Exit Code: {process.returncode}\n")
            f.write(f"{'='*60}\n")
            f.write(full_output)

        if process.returncode != 0:
            # Check captured output for connection errors
            if "Connection error" in full_output or "LLMError" in full_output:
                raise ConnectionError("LLM connection error detected")
            else:
                # Save error details to manifest
                error_msg = f"Pipeline failed with exit code {process.returncode}"

                # Try to extract last error from output
                error_lines = [line for line in output_lines if 'error' in line.lower() or 'traceback' in line.lower()]
                if error_lines:
                    error_msg += f" - Last error: {error_lines[-1].strip()}"

                error_info = {
                    'message': error_msg,
                    'log_file': str(error_log_file),
                    'exit_code': process.returncode
                }

                raise subprocess.CalledProcessError(process.returncode, cmd, output=json.dumps(error_info))

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

    parser.add_argument(
        "--enrich-info-pieces",
        type=int,
        default=3,
        help="Number of distracting facts to add per question (0=disabled, default: 3)"
    )

    parser.add_argument(
        "--enrich-graph-depth",
        type=int,
        default=1,
        help="Graph traversal depth for finding enrichment candidates (1-3, default: 1)"
    )

    args = parser.parse_args()

    skip_flags = {
        "skip_assessment": args.skip_assessment,
        "skip_graph_creation": args.skip_graph_creation,
        "skip_query_generation": args.skip_query_generation,
        "skip_paper_fetching": args.skip_paper_fetching,
        "skip_graph_enrichment": args.skip_graph_enrichment,
    }

    runner = BatchRunner(
        Path(args.manifest),
        skip_flags,
        enrich_info_pieces=args.enrich_info_pieces,
        enrich_graph_depth=args.enrich_graph_depth
    )
    runner.run(start_from=args.start_from, limit=args.limit)


if __name__ == "__main__":
    main()
