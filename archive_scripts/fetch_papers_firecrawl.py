"""
Stage 4: Fetch Papers with Firecrawl
Takes search queries from Stage 3, uses Firecrawl to find and download scientific papers
"""

import argparse
import json
import sys
import os
from pathlib import Path
from typing import List, Dict

sys.path.insert(0, str(Path(__file__).parent.absolute()))

from paper_fetching.firecrawl_client import (
    search_papers,
    download_paper_content,
    save_paper_with_uuid,
    load_papers_metadata,
    save_papers_metadata,
    extract_text_from_result,
    deduplicate_by_url
)


def load_query_files(query_files: List[str]) -> List[Dict]:
    """
    Load queries from one or more JSON files from Stage 3.

    Args:
        query_files: List of paths to query JSON files

    Returns:
        Combined list of queries with metadata
    """

    all_queries = []

    for query_file in query_files:
        query_path = Path(query_file)

        if not query_path.exists():
            print(f"⚠ Warning: Query file not found: {query_file}")
            continue

        with open(query_path, 'r') as f:
            data = json.load(f)

        queries = data.get('queries', [])
        query_type = data.get('query_type', 'unknown')

        # Add query type to each query
        for q in queries:
            q['query_type'] = query_type

        all_queries.extend(queries)
        print(f"✓ Loaded {len(queries)} queries from {query_path.name} (type: {query_type})")

    return all_queries


def fetch_papers_for_queries(
    queries: List[Dict],
    api_key: str,
    output_dir: Path,
    papers_per_query: int = 5,
    max_total_papers: int = 50,
    format: str = 'markdown'
) -> Dict:
    """
    Fetch papers for a list of queries using Firecrawl.

    Args:
        queries: List of query dicts from Stage 3
        api_key: Firecrawl API key
        output_dir: Directory to save papers
        papers_per_query: Max papers to fetch per query
        max_total_papers: Max total papers to fetch across all queries
        format: Content format for papers

    Returns:
        Dict of papers metadata
    """

    output_dir.mkdir(parents=True, exist_ok=True)

    # Load existing metadata if available
    metadata_file = output_dir / "papers_metadata.json"
    papers_metadata = load_papers_metadata(metadata_file)

    existing_urls = {meta['url'] for meta in papers_metadata.values()}

    total_fetched = 0
    all_results = []

    print(f"\n{'='*60}")
    print(f"Fetching papers for {len(queries)} queries")
    print(f"{'='*60}\n")

    for i, query_dict in enumerate(queries):
        if total_fetched >= max_total_papers:
            print(f"\n⚠ Reached max total papers ({max_total_papers}), stopping early")
            break

        query_text = query_dict.get('query', '')
        query_type = query_dict.get('query_type', 'unknown')

        print(f"\n[{i+1}/{len(queries)}] Query: '{query_text}' (type: {query_type})")

        # Search for papers
        results = search_papers(
            query=query_text,
            api_key=api_key,
            max_results=papers_per_query,
            format=format
        )

        # Filter out already downloaded papers
        new_results = [r for r in results if r.get('url') not in existing_urls]

        if not new_results:
            print(f"  No new papers found (all already downloaded)")
            continue

        print(f"  Processing {len(new_results)} new papers")

        # Download and save each paper
        for j, result in enumerate(new_results):
            if total_fetched >= max_total_papers:
                break

            url = result.get('url', '')
            title = result.get('title', 'Unknown Title')

            print(f"    [{j+1}/{len(new_results)}] Downloading: {title[:50]}...")

            # Extract content from search result
            content = extract_text_from_result(result, format)

            # If content is empty or too short, try to scrape the URL directly
            if not content or len(content) < 500:
                print(f"      Content too short, attempting direct scrape...")
                scraped = download_paper_content(url, api_key, format)
                if scraped:
                    content = extract_text_from_result(scraped, format)

            # Skip if still no content
            if not content or len(content) < 200:
                print(f"      ✗ Skipping: insufficient content ({len(content)} chars)")
                continue

            # Prepare metadata
            paper_metadata = {
                'title': title,
                'url': url,
                'source_query': query_text,
                'query_type': query_type
            }

            # Add optional fields if available
            for key in ['authors', 'publication_date', 'journal', 'doi']:
                if key in result:
                    paper_metadata[key] = result[key]

            # Save paper with UUID
            paper_uuid, metadata_entry = save_paper_with_uuid(
                content=content,
                metadata=paper_metadata,
                output_dir=output_dir
            )

            # Update metadata dict
            papers_metadata[paper_uuid] = metadata_entry
            existing_urls.add(url)

            total_fetched += 1

    # Save metadata
    save_papers_metadata(papers_metadata, metadata_file)

    print(f"\n{'='*60}")
    print(f"Paper fetching complete")
    print(f"{'='*60}")
    print(f"Total papers downloaded: {total_fetched}")
    print(f"Total papers in collection: {len(papers_metadata)}")
    print(f"\n")

    return papers_metadata


def main(args):
    """Main function"""

    print(f"\n{'='*60}")
    print(f"Stage 4: Fetch Papers with Firecrawl")
    print(f"{'='*60}\n")

    # Check for API key
    api_key = args.api_key or os.getenv('FIRECRAWL_API_KEY')

    if not api_key:
        print("✗ ERROR: Firecrawl API key not provided")
        print("  Provide via --api-key argument or FIRECRAWL_API_KEY environment variable")
        sys.exit(1)

    # Load queries
    print(f"Loading query files...")
    queries = load_query_files(args.query_files)

    if not queries:
        print("\n✗ ERROR: No queries loaded")
        sys.exit(1)

    print(f"\n✓ Total queries loaded: {len(queries)}\n")

    # Limit queries if specified
    if args.max_queries and len(queries) > args.max_queries:
        print(f"⚠ Limiting to first {args.max_queries} queries")
        queries = queries[:args.max_queries]

    # Fetch papers
    output_dir = Path(args.output_dir)
    papers_metadata = fetch_papers_for_queries(
        queries=queries,
        api_key=api_key,
        output_dir=output_dir,
        papers_per_query=args.papers_per_query,
        max_total_papers=args.max_total_papers,
        format=args.format
    )

    # Summary statistics
    print("\nSummary by query type:")
    query_type_counts = {}
    for paper_meta in papers_metadata.values():
        query_type = paper_meta.get('query_type', 'unknown')
        query_type_counts[query_type] = query_type_counts.get(query_type, 0) + 1

    for query_type, count in sorted(query_type_counts.items()):
        print(f"  {query_type}: {count} papers")

    print(f"\nOutput directory: {output_dir}")
    print(f"Metadata file: {output_dir / 'papers_metadata.json'}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Fetch scientific papers using Firecrawl based on generated queries"
    )
    parser.add_argument(
        "query_files",
        nargs='+',
        type=str,
        help="Path(s) to query JSON file(s) from Stage 3"
    )
    parser.add_argument(
        "--api-key",
        type=str,
        help="Firecrawl API key (or set FIRECRAWL_API_KEY environment variable)"
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="./fetched_papers",
        help="Directory to save papers (default: ./fetched_papers)"
    )
    parser.add_argument(
        "--papers-per-query",
        type=int,
        default=5,
        help="Maximum papers to fetch per query (default: 5)"
    )
    parser.add_argument(
        "--max-total-papers",
        type=int,
        default=50,
        help="Maximum total papers to fetch (default: 50)"
    )
    parser.add_argument(
        "--max-queries",
        type=int,
        help="Maximum number of queries to process (default: all)"
    )
    parser.add_argument(
        "--format",
        type=str,
        default="markdown",
        choices=["markdown", "html", "text"],
        help="Content format (default: markdown)"
    )

    args = parser.parse_args()
    main(args)
