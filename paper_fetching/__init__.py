"""
Paper Fetching Module
Utilities for fetching scientific papers using Firecrawl API
"""

from .firecrawl_client import (
    search_papers,
    download_paper_content,
    save_paper_with_uuid,
    load_papers_metadata,
    save_papers_metadata
)

__all__ = [
    'search_papers',
    'download_paper_content',
    'save_paper_with_uuid',
    'load_papers_metadata',
    'save_papers_metadata'
]
