"""
Manifest utilities for managing batch paper processing.

Provides tools to:
- Generate manifests from directories
- Filter and subset manifests
- Track and update processing status
- Generate reports
"""

import json
import argparse
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional
import sys


def find_papers(directory: Path, recursive: bool = True) -> List[Dict]:
    """
    Find all .txt paper files in a directory.

    Args:
        directory: Directory to search
        recursive: Whether to search recursively

    Returns:
        List of dicts with paper info (path, paper_id)
    """
    directory = Path(directory).resolve()

    if not directory.exists():
        print(f"✗ ERROR: Directory not found: {directory}")
        sys.exit(1)

    if recursive:
        pattern = "**/*.txt"
    else:
        pattern = "*.txt"

    papers = []
    for txt_file in directory.glob(pattern):
        # Skip files in .qa_output directories (these are outputs, not inputs)
        if ".qa_output" in txt_file.parts:
            continue

        papers.append({
            "path": str(txt_file),
            "paper_id": txt_file.stem,
        })

    return sorted(papers, key=lambda p: p["path"])


def generate_manifest(
    directory: Path,
    domain: str,
    output_file: Optional[Path] = None,
    limit: Optional[int] = None,
    exclude_existing: bool = False
) -> Dict:
    """
    Generate a manifest file from a directory of papers.

    Args:
        directory: Directory containing papers
        domain: Domain for processing
        output_file: Where to save manifest (default: ASM_595_manifest.json)
        limit: Limit number of papers to include
        exclude_existing: Skip papers that already have .qa_output

    Returns:
        Manifest dict
    """
    papers = find_papers(directory, recursive=True)

    if exclude_existing:
        filtered = []
        for paper in papers:
            paper_path = Path(paper["path"])
            qa_output = paper_path.parent / ".qa_output" / paper_path.stem / domain
            if not qa_output.exists():
                filtered.append(paper)
            else:
                print(f"  ⊘ Skipping (already processed): {paper['paper_id']}")
        papers = filtered

    if limit:
        papers = papers[:limit]

    manifest = {
        "generated": datetime.now().isoformat(),
        "directory": str(directory.resolve()),
        "domain": domain,
        "total_papers": len(papers),
        "papers": [
            {
                "id": p["paper_id"],
                "path": p["path"],
                "domain": domain,
                "status": "pending",
                "attempts": 0,
                "last_error": None,
                "completed_at": None,
            }
            for p in papers
        ]
    }

    if not output_file:
        output_file = Path(f"manifest_{directory.name}_{domain}.json")
    else:
        output_file = Path(output_file)

    with open(output_file, "w") as f:
        json.dump(manifest, f, indent=2)

    print(f"\n✓ Manifest generated: {output_file}")
    print(f"  Total papers: {len(papers)}")
    print(f"  Domain: {domain}")

    return manifest


def load_manifest(manifest_file: Path) -> Dict:
    """Load a manifest file."""
    manifest_file = Path(manifest_file)

    if not manifest_file.exists():
        print(f"✗ ERROR: Manifest file not found: {manifest_file}")
        sys.exit(1)

    with open(manifest_file, "r") as f:
        return json.load(f)


def save_manifest(manifest: Dict, manifest_file: Path) -> None:
    """Save a manifest file."""
    with open(manifest_file, "w") as f:
        json.dump(manifest, f, indent=2)


def get_manifest_stats(manifest: Dict) -> Dict:
    """Get statistics about manifest processing."""
    papers = manifest.get("papers", [])

    stats = {
        "total": len(papers),
        "pending": sum(1 for p in papers if p["status"] == "pending"),
        "completed": sum(1 for p in papers if p["status"] == "completed"),
        "failed": sum(1 for p in papers if p["status"] == "failed"),
    }

    return stats


def print_manifest_stats(manifest: Dict) -> None:
    """Print statistics about a manifest."""
    stats = get_manifest_stats(manifest)

    print(f"\nManifest Statistics:")
    print(f"  Total papers: {stats['total']}")
    print(f"  Pending: {stats['pending']}")
    print(f"  Completed: {stats['completed']}")
    print(f"  Failed: {stats['failed']}")
    print(f"  Progress: {stats['completed']}/{stats['total']} ({100*stats['completed']/max(stats['total'], 1):.1f}%)")


def filter_manifest(
    manifest: Dict,
    status: Optional[str] = None,
    paper_ids: Optional[List[str]] = None,
    limit: Optional[int] = None
) -> Dict:
    """
    Filter manifest to subset of papers.

    Args:
        manifest: Original manifest
        status: Only include papers with this status (pending/completed/failed)
        paper_ids: Only include specific paper IDs
        limit: Limit to first N papers

    Returns:
        Filtered manifest
    """
    papers = manifest["papers"]

    if status:
        papers = [p for p in papers if p["status"] == status]

    if paper_ids:
        paper_id_set = set(paper_ids)
        papers = [p for p in papers if p["id"] in paper_id_set]

    if limit:
        papers = papers[:limit]

    filtered = manifest.copy()
    filtered["papers"] = papers
    filtered["total_papers"] = len(papers)

    return filtered


def update_paper_status(
    manifest: Dict,
    paper_id: str,
    status: str,
    error: Optional[str] = None
) -> bool:
    """
    Update status of a single paper in manifest.

    Args:
        manifest: Manifest dict
        paper_id: Paper ID to update
        status: New status (pending/completed/failed)
        error: Error message if failed

    Returns:
        True if updated, False if paper not found
    """
    for paper in manifest["papers"]:
        if paper["id"] == paper_id:
            paper["status"] = status
            paper["attempts"] += 1
            if status == "completed":
                paper["completed_at"] = datetime.now().isoformat()
            if error:
                paper["last_error"] = error
            return True

    return False


def cleanup_manifest(
    manifest: Dict,
    remove_completed: bool = False
) -> Dict:
    """
    Clean up manifest - e.g., remove papers that were already processed.

    Args:
        manifest: Original manifest
        remove_completed: Remove papers with 'completed' status

    Returns:
        Cleaned manifest
    """
    papers = manifest["papers"]

    if remove_completed:
        papers = [p for p in papers if p["status"] != "completed"]

    cleaned = manifest.copy()
    cleaned["papers"] = papers
    cleaned["total_papers"] = len(papers)

    return cleaned


def main():
    parser = argparse.ArgumentParser(
        description="Manifest utilities for batch paper processing"
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # Generate command
    gen_parser = subparsers.add_parser("generate", help="Generate manifest from directory")
    gen_parser.add_argument("directory", help="Directory containing papers")
    gen_parser.add_argument("--domain", required=True, help="Domain for processing")
    gen_parser.add_argument("--output", help="Output manifest file")
    gen_parser.add_argument("--limit", type=int, help="Limit number of papers")
    gen_parser.add_argument("--exclude-existing", action="store_true",
                          help="Skip papers that already have .qa_output")

    # Stats command
    stats_parser = subparsers.add_parser("stats", help="Show manifest statistics")
    stats_parser.add_argument("manifest", help="Manifest file")

    # Filter command
    filter_parser = subparsers.add_parser("filter", help="Filter manifest and save subset")
    filter_parser.add_argument("manifest", help="Manifest file")
    filter_parser.add_argument("--output", required=True, help="Output manifest file")
    filter_parser.add_argument("--status", choices=["pending", "completed", "failed"],
                             help="Only include papers with this status")
    filter_parser.add_argument("--limit", type=int, help="Limit to first N papers")

    # List command
    list_parser = subparsers.add_parser("list", help="List papers in manifest")
    list_parser.add_argument("manifest", help="Manifest file")
    list_parser.add_argument("--status", choices=["pending", "completed", "failed"],
                           help="Only show papers with this status")
    list_parser.add_argument("--limit", type=int, help="Limit output to N papers")

    # Cleanup command
    cleanup_parser = subparsers.add_parser("cleanup", help="Clean up manifest")
    cleanup_parser.add_argument("manifest", help="Manifest file")
    cleanup_parser.add_argument("--output", required=True, help="Output manifest file")
    cleanup_parser.add_argument("--remove-completed", action="store_true",
                              help="Remove completed papers")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "generate":
        generate_manifest(
            Path(args.directory),
            args.domain,
            Path(args.output) if args.output else None,
            args.limit,
            args.exclude_existing
        )

    elif args.command == "stats":
        manifest = load_manifest(Path(args.manifest))
        print_manifest_stats(manifest)

    elif args.command == "filter":
        manifest = load_manifest(Path(args.manifest))
        filtered = filter_manifest(
            manifest,
            status=args.status,
            limit=args.limit
        )
        save_manifest(filtered, Path(args.output))
        print(f"\n✓ Filtered manifest saved: {args.output}")
        print(f"  Papers: {filtered['total_papers']}")

    elif args.command == "list":
        manifest = load_manifest(Path(args.manifest))
        filtered = filter_manifest(
            manifest,
            status=args.status,
            limit=args.limit
        )

        papers = filtered["papers"]
        print(f"\nPapers in manifest ({len(papers)} total):\n")
        for paper in papers:
            status_icon = "⊙" if paper["status"] == "pending" else "✓" if paper["status"] == "completed" else "✗"
            print(f"  {status_icon} {paper['id']}")
            print(f"     Status: {paper['status']}, Attempts: {paper['attempts']}")
            if paper["last_error"]:
                print(f"     Error: {paper['last_error']}")

    elif args.command == "cleanup":
        manifest = load_manifest(Path(args.manifest))
        cleaned = cleanup_manifest(manifest, args.remove_completed)
        save_manifest(cleaned, Path(args.output))
        print(f"\n✓ Cleaned manifest saved: {args.output}")
        print(f"  Papers: {cleaned['total_papers']}")


if __name__ == "__main__":
    main()
