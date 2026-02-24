"""
Configuration for the HAIQU Iterative GraphRAG Pipeline
"""

from dataclasses import dataclass, field, asdict
from typing import Optional, List
from pathlib import Path
import yaml
import json


@dataclass
class HAIQUPipelineConfig:
    """
    Configuration for HAIQU iterative pipeline.

    Controls paper limits, search parameters, convergence criteria,
    and QA generation settings.
    """

    # Paths
    seed_document: str = ""
    output_dir: str = "./haiqu_output"
    domain_schema: str = "respiratory_disease_cognition"

    # Paper collection limits
    max_total_papers: int = 50
    papers_per_round: int = 10
    max_rounds: int = 10

    # Search parameters
    entities_per_round: int = 5      # How many entities to search per round
    queries_per_entity: int = 3      # Queries generated per entity
    papers_per_query: int = 3        # Max papers fetched per query

    # Convergence thresholds
    min_new_entities_per_round: int = 3
    min_new_papers_per_round: int = 2

    # QA generation settings
    num_questions: int = 30
    enrich_info_pieces: int = 3
    enrich_graph_depth: int = 2
    enrich_max_candidates: int = 50

    # API settings
    firecrawl_api_key: Optional[str] = None

    # Text processing
    chunk_size: int = 2000
    chunk_overlap: int = 200
    min_paper_length: int = 500  # Minimum characters for a valid paper

    # Entity merging
    similarity_threshold: float = 0.85
    auto_merge_entities: bool = True

    # Priority entity types (searched first)
    priority_entity_types: List[str] = field(default_factory=lambda: [
        "RESPIRATORY_DISEASE",
        "COGNITIVE_FUNCTION",
        "NEUROPSYCH_TEST",
        "CLAIM",
        "KNOWLEDGE_GAP",
        "COHORT",
        "EFFECT_ESTIMATE",
        "STUDY"
    ])

    # Domain-specific search context terms
    domain_context_terms: List[str] = field(default_factory=lambda: [
        "cognitive impairment",
        "neuropsychological",
        "respiratory infection",
        "healthcare workers",
        "brain fog",
        "long COVID",
        "processing speed",
        "working memory",
        "executive function",
        "attention deficit"
    ])

    def __post_init__(self):
        """Validate configuration after initialization."""
        if self.max_total_papers < self.papers_per_round:
            raise ValueError("max_total_papers must be >= papers_per_round")
        if self.entities_per_round < 1:
            raise ValueError("entities_per_round must be >= 1")
        if self.similarity_threshold < 0 or self.similarity_threshold > 1:
            raise ValueError("similarity_threshold must be between 0 and 1")

    @classmethod
    def from_yaml(cls, path: str) -> 'HAIQUPipelineConfig':
        """Load configuration from YAML file."""
        with open(path, 'r') as f:
            data = yaml.safe_load(f)
        return cls(**data)

    @classmethod
    def from_json(cls, path: str) -> 'HAIQUPipelineConfig':
        """Load configuration from JSON file."""
        with open(path, 'r') as f:
            data = json.load(f)
        return cls(**data)

    def to_dict(self) -> dict:
        """Convert configuration to dictionary."""
        return asdict(self)

    def to_yaml(self, path: str) -> None:
        """Save configuration to YAML file."""
        with open(path, 'w') as f:
            yaml.dump(self.to_dict(), f, default_flow_style=False)

    def to_json(self, path: str) -> None:
        """Save configuration to JSON file."""
        with open(path, 'w') as f:
            json.dump(self.to_dict(), f, indent=2)

    def get_output_path(self, *parts: str) -> Path:
        """Get a path within the output directory."""
        return Path(self.output_dir).joinpath(*parts)

    def papers_remaining(self, current_total: int) -> int:
        """Calculate how many more papers can be fetched."""
        return max(0, self.max_total_papers - current_total)

    def __repr__(self) -> str:
        return (
            f"HAIQUPipelineConfig(\n"
            f"  seed_document='{self.seed_document}',\n"
            f"  output_dir='{self.output_dir}',\n"
            f"  domain_schema='{self.domain_schema}',\n"
            f"  max_total_papers={self.max_total_papers},\n"
            f"  papers_per_round={self.papers_per_round},\n"
            f"  max_rounds={self.max_rounds},\n"
            f"  entities_per_round={self.entities_per_round},\n"
            f"  num_questions={self.num_questions}\n"
            f")"
        )
