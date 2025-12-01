"""
Firecrawl API Client
Modular functions for searching and downloading scientific papers
"""

import json
import uuid
import requests
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime


# Scientific publication domains to prioritize
SCIENTIFIC_DOMAINS = [
    'pubmed.ncbi.nlm.nih.gov',
    'ncbi.nlm.nih.gov/pmc',
    'biorxiv.org',
    'medrxiv.org',
    'nature.com',
    'science.org',
    'cell.com',
    'plos.org',
    'frontiersin.org',
    'springer.com',
    'wiley.com',
    'acs.org',
    'arxiv.org'
]

# Domains to exclude (news, blogs, general websites)
EXCLUDED_DOMAINS = [
    'wikipedia.org',
    'news.google.com',
    'sciencedaily.com',
    'medscape.com',
    'webmd.com',
    'healthline.com',
    'mayoclinic.org',
    'medium.com',
    'forbes.com',
    'cnn.com',
    'bbc.com',
    'reddit.com'
]


def search_papers(
    query: str,
    api_key: str,
    max_results: int = 10,
    format: str = 'markdown'
) -> List[Dict]:
    """
    Search for scientific papers using Firecrawl API.

    Args:
        query: Search query string
        api_key: Firecrawl API key
        max_results: Maximum number of results to return
        format: Content format ('markdown', 'html', 'text')

    Returns:
        List of search results with URLs and metadata
    """

    print(f"Searching for: '{query}'")

    # Firecrawl search endpoint
    search_url = "https://api.firecrawl.dev/v1/search"

    headers = {
        'Authorization': f'Bearer {api_key}',
        'Content-Type': 'application/json'
    }

    payload = {
        'query': query,
        'limit': max_results,
        'scrapeOptions': {
            'formats': [format]
        }
    }

    try:
        response = requests.post(search_url, headers=headers, json=payload, timeout=30)
        response.raise_for_status()

        data = response.json()
        results = data.get('data', [])

        # Filter for scientific publications only
        filtered_results = []
        for result in results:
            url = result.get('url', '')

            # Skip excluded domains
            if any(excluded in url.lower() for excluded in EXCLUDED_DOMAINS):
                continue

            # Prioritize scientific domains
            is_scientific = any(domain in url.lower() for domain in SCIENTIFIC_DOMAINS)

            if is_scientific:
                filtered_results.append(result)

        print(f"  Found {len(filtered_results)} scientific papers (filtered from {len(results)} total)")

        return filtered_results

    except requests.exceptions.RequestException as e:
        print(f"  ✗ Error searching: {e}")
        return []


def download_paper_content(
    url: str,
    api_key: str,
    format: str = 'markdown'
) -> Optional[Dict]:
    """
    Download full content of a paper from URL using Firecrawl.

    Args:
        url: Paper URL
        api_key: Firecrawl API key
        format: Content format ('markdown', 'html', 'text')

    Returns:
        Dict with content and metadata, or None if failed
    """

    scrape_url = "https://api.firecrawl.dev/v1/scrape"

    headers = {
        'Authorization': f'Bearer {api_key}',
        'Content-Type': 'application/json'
    }

    payload = {
        'url': url,
        'formats': [format]
    }

    try:
        response = requests.post(scrape_url, headers=headers, json=payload, timeout=60)
        response.raise_for_status()

        data = response.json()

        if data.get('success'):
            return data.get('data', {})
        else:
            print(f"  ✗ Failed to scrape {url}")
            return None

    except requests.exceptions.RequestException as e:
        print(f"  ✗ Error downloading {url}: {e}")
        return None


def save_paper_with_uuid(
    content: str,
    metadata: Dict,
    output_dir: Path,
    existing_metadata: Optional[Dict] = None
) -> str:
    """
    Save paper content with a UUID filename and update metadata.

    Args:
        content: Full text content of the paper
        metadata: Paper metadata (title, url, query, etc.)
        output_dir: Directory to save papers
        existing_metadata: Existing papers metadata dict (will be updated)

    Returns:
        UUID string assigned to this paper
    """

    # Generate UUID
    paper_uuid = str(uuid.uuid4())

    # Save content to {uuid}.txt
    content_file = output_dir / f"{paper_uuid}.txt"
    with open(content_file, 'w', encoding='utf-8') as f:
        f.write(content)

    # Prepare metadata entry
    metadata_entry = {
        'uuid': paper_uuid,
        'title': metadata.get('title', 'Unknown'),
        'url': metadata.get('url', ''),
        'source_query': metadata.get('source_query', ''),
        'query_type': metadata.get('query_type', ''),
        'downloaded_at': datetime.now().isoformat(),
        'content_file': str(content_file),
        'content_length': len(content)
    }

    # Add optional metadata fields
    for key in ['authors', 'publication_date', 'journal', 'doi']:
        if key in metadata:
            metadata_entry[key] = metadata[key]

    print(f"  ✓ Saved paper: {paper_uuid} - {metadata_entry['title'][:60]}")

    return paper_uuid, metadata_entry


def load_papers_metadata(metadata_file: Path) -> Dict:
    """
    Load existing papers metadata from JSON file.

    Args:
        metadata_file: Path to papers_metadata.json

    Returns:
        Dict mapping UUID to metadata, or empty dict if file doesn't exist
    """

    if metadata_file.exists():
        with open(metadata_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    else:
        return {}


def save_papers_metadata(metadata: Dict, metadata_file: Path):
    """
    Save papers metadata to JSON file.

    Args:
        metadata: Dict mapping UUID to metadata
        metadata_file: Path to papers_metadata.json
    """

    with open(metadata_file, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, indent=2)

    print(f"\n✓ Metadata saved: {metadata_file}")
    print(f"  Total papers: {len(metadata)}")


def extract_text_from_result(result: Dict, format: str = 'markdown') -> str:
    """
    Extract text content from Firecrawl search result.

    Args:
        result: Search result dict from Firecrawl
        format: Format to extract ('markdown', 'html', 'text')

    Returns:
        Extracted text content
    """

    if format == 'markdown':
        return result.get('markdown', result.get('content', ''))
    elif format == 'html':
        return result.get('html', result.get('content', ''))
    else:
        return result.get('content', '')


def deduplicate_by_url(results: List[Dict]) -> List[Dict]:
    """
    Remove duplicate results based on URL.

    Args:
        results: List of search results

    Returns:
        Deduplicated list
    """

    seen_urls = set()
    unique_results = []

    for result in results:
        url = result.get('url', '')
        if url and url not in seen_urls:
            seen_urls.add(url)
            unique_results.append(result)

    return unique_results
