"""
Iterative Search State Management

Tracks entity search history, paper fetching progress, and enables
pipeline resumability by persisting state to disk.
"""

from dataclasses import dataclass, field, asdict
from typing import Dict, Set, List, Optional, Any
from datetime import datetime
from pathlib import Path
import json
import networkx as nx


@dataclass
class EntitySearchRecord:
    """Record of an entity used for search."""
    entity_name: str
    entity_type: str
    round_used: int
    queries_generated: List[str]
    papers_found: int
    timestamp: str

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> 'EntitySearchRecord':
        return cls(**data)


@dataclass
class PaperRecord:
    """Record of a fetched paper."""
    uuid: str
    url: str
    title: str
    round_fetched: int
    source_query: str
    source_entity: str
    timestamp: str

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> 'PaperRecord':
        return cls(**data)


class IterativeSearchState:
    """
    Manages state across iterative search rounds.

    Tracks:
    - Which entities have been used for search
    - Which papers have been fetched (by URL)
    - Entity discovery timeline by round
    - Paper fetching progress

    Supports save/load for pipeline resumability.
    """

    def __init__(self):
        # Entity search tracking
        self.searched_entities: Dict[str, EntitySearchRecord] = {}

        # Paper tracking
        self.fetched_paper_urls: Set[str] = set()
        self.papers: Dict[str, PaperRecord] = {}  # uuid -> PaperRecord

        # Round tracking
        self.entities_by_round: Dict[int, Set[str]] = {}
        self.papers_by_round: Dict[int, List[str]] = {}  # round -> list of paper uuids

        # Progress counters
        self.current_round: int = 0
        self.total_papers: int = 0

        # Metadata
        self.started_at: Optional[str] = None
        self.last_updated: Optional[str] = None
        self.seed_document: Optional[str] = None

    def start_session(self, seed_document: str) -> None:
        """Initialize a new pipeline session."""
        self.started_at = datetime.now().isoformat()
        self.last_updated = self.started_at
        self.seed_document = seed_document

    def mark_entity_searched(
        self,
        entity_name: str,
        entity_type: str,
        queries: List[str],
        papers_found: int
    ) -> None:
        """Record that an entity has been used for search."""
        record = EntitySearchRecord(
            entity_name=entity_name,
            entity_type=entity_type,
            round_used=self.current_round,
            queries_generated=queries,
            papers_found=papers_found,
            timestamp=datetime.now().isoformat()
        )
        self.searched_entities[entity_name] = record
        self._update_timestamp()

    def is_entity_searched(self, entity_name: str) -> bool:
        """Check if entity has already been used for search."""
        return entity_name in self.searched_entities

    def get_unsearched_entities(self, graph: nx.DiGraph) -> List[str]:
        """Get entities from graph not yet used for search queries."""
        unsearched = []
        for node in graph.nodes():
            if node not in self.searched_entities:
                unsearched.append(node)
        return unsearched

    def add_fetched_paper(
        self,
        uuid: str,
        url: str,
        title: str,
        source_query: str,
        source_entity: str
    ) -> None:
        """Record a fetched paper."""
        record = PaperRecord(
            uuid=uuid,
            url=url,
            title=title,
            round_fetched=self.current_round,
            source_query=source_query,
            source_entity=source_entity,
            timestamp=datetime.now().isoformat()
        )

        self.papers[uuid] = record
        self.fetched_paper_urls.add(url)
        self.total_papers += 1

        # Track by round
        if self.current_round not in self.papers_by_round:
            self.papers_by_round[self.current_round] = []
        self.papers_by_round[self.current_round].append(uuid)

        self._update_timestamp()

    def is_paper_fetched(self, url: str) -> bool:
        """Check if paper has already been fetched by URL."""
        return url in self.fetched_paper_urls

    def add_entities_for_round(self, round_num: int, entities: Set[str]) -> None:
        """Record entities discovered in a round."""
        self.entities_by_round[round_num] = entities
        self._update_timestamp()

    def get_new_entities_in_round(self, round_num: int) -> Set[str]:
        """Get entities that were first discovered in a specific round."""
        if round_num not in self.entities_by_round:
            return set()

        current_entities = self.entities_by_round[round_num]

        # Subtract entities from all previous rounds
        previous_entities = set()
        for r in range(round_num):
            if r in self.entities_by_round:
                previous_entities.update(self.entities_by_round[r])

        return current_entities - previous_entities

    def count_new_entities_in_round(self, round_num: int) -> int:
        """Count entities first discovered in a specific round."""
        return len(self.get_new_entities_in_round(round_num))

    def count_papers_in_round(self, round_num: int) -> int:
        """Count papers fetched in a specific round."""
        return len(self.papers_by_round.get(round_num, []))

    def advance_round(self) -> None:
        """Move to the next round."""
        self.current_round += 1
        self._update_timestamp()

    def get_round_summary(self, round_num: int) -> dict:
        """Get summary statistics for a round."""
        return {
            'round': round_num,
            'papers_fetched': self.count_papers_in_round(round_num),
            'new_entities': self.count_new_entities_in_round(round_num),
            'total_entities': len(self.entities_by_round.get(round_num, set())),
            'entities_searched': sum(
                1 for e in self.searched_entities.values()
                if e.round_used == round_num
            )
        }

    def get_overall_summary(self) -> dict:
        """Get overall pipeline summary."""
        return {
            'started_at': self.started_at,
            'last_updated': self.last_updated,
            'seed_document': self.seed_document,
            'current_round': self.current_round,
            'total_papers': self.total_papers,
            'total_entities_searched': len(self.searched_entities),
            'total_unique_entities': len(set().union(
                *[s for s in self.entities_by_round.values()]
            )) if self.entities_by_round else 0,
            'papers_by_round': {
                r: len(p) for r, p in self.papers_by_round.items()
            }
        }

    def _update_timestamp(self) -> None:
        """Update last_updated timestamp."""
        self.last_updated = datetime.now().isoformat()

    def save_state(self, output_path: Path) -> None:
        """Persist state to JSON for resumability."""
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        state_dict = {
            'searched_entities': {
                k: v.to_dict() for k, v in self.searched_entities.items()
            },
            'fetched_paper_urls': list(self.fetched_paper_urls),
            'papers': {
                k: v.to_dict() for k, v in self.papers.items()
            },
            'entities_by_round': {
                str(k): list(v) for k, v in self.entities_by_round.items()
            },
            'papers_by_round': {
                str(k): v for k, v in self.papers_by_round.items()
            },
            'current_round': self.current_round,
            'total_papers': self.total_papers,
            'started_at': self.started_at,
            'last_updated': self.last_updated,
            'seed_document': self.seed_document
        }

        with open(output_path, 'w') as f:
            json.dump(state_dict, f, indent=2)

    @classmethod
    def load_state(cls, state_path: Path) -> 'IterativeSearchState':
        """Load state from JSON file."""
        with open(state_path, 'r') as f:
            data = json.load(f)

        state = cls()

        # Load searched entities
        state.searched_entities = {
            k: EntitySearchRecord.from_dict(v)
            for k, v in data.get('searched_entities', {}).items()
        }

        # Load fetched papers
        state.fetched_paper_urls = set(data.get('fetched_paper_urls', []))
        state.papers = {
            k: PaperRecord.from_dict(v)
            for k, v in data.get('papers', {}).items()
        }

        # Load round tracking
        state.entities_by_round = {
            int(k): set(v)
            for k, v in data.get('entities_by_round', {}).items()
        }
        state.papers_by_round = {
            int(k): v
            for k, v in data.get('papers_by_round', {}).items()
        }

        # Load counters
        state.current_round = data.get('current_round', 0)
        state.total_papers = data.get('total_papers', 0)

        # Load metadata
        state.started_at = data.get('started_at')
        state.last_updated = data.get('last_updated')
        state.seed_document = data.get('seed_document')

        return state

    def __repr__(self) -> str:
        return (
            f"IterativeSearchState(\n"
            f"  current_round={self.current_round},\n"
            f"  total_papers={self.total_papers},\n"
            f"  entities_searched={len(self.searched_entities)},\n"
            f"  unique_urls={len(self.fetched_paper_urls)}\n"
            f")"
        )
