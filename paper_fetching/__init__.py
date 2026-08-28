"""
Paper Fetching Module
Utilities for fetching scientific papers using Firecrawl API
"""

from .firecrawl_client import (
    FIRECRAWL_SEARCH_API_VERSION,
    FIRECRAWL_SEARCH_ENDPOINT,
    FIRECRAWL_SEARCH_MAX_BATCH_SIZE,
    FIRECRAWL_SEARCH_PROVIDER,
    firecrawl_search_batch_metadata,
    search_papers,
    download_paper_content,
    save_paper_with_uuid,
    load_papers_metadata,
    save_papers_metadata
)

__all__ = [
    'FIRECRAWL_SEARCH_API_VERSION',
    'FIRECRAWL_SEARCH_ENDPOINT',
    'FIRECRAWL_SEARCH_MAX_BATCH_SIZE',
    'FIRECRAWL_SEARCH_PROVIDER',
    'firecrawl_search_batch_metadata',
    'search_papers',
    'download_paper_content',
    'save_paper_with_uuid',
    'load_papers_metadata',
    'save_papers_metadata'
]
