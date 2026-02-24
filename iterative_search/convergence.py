"""
Convergence Checker

Determines when the iterative search should stop based on
multiple criteria including paper limits, entity discovery rates,
and round limits.
"""

from typing import Tuple, List, Optional
import networkx as nx

from .search_state import IterativeSearchState
from .config import HAIQUPipelineConfig


class StopReason:
    """Enumeration of stopping reasons."""
    PAPER_LIMIT = "paper_limit"
    ROUND_LIMIT = "round_limit"
    NO_NEW_ENTITIES = "no_new_entities"
    NO_NEW_PAPERS = "no_new_papers"
    ALL_SEARCHED = "all_entities_searched"
    USER_STOPPED = "user_stopped"
    ERROR = "error"


class ConvergenceChecker:
    """
    Determines when the iterative search should stop.

    Criteria (stops when ANY is met):
    1. Paper limit reached (default: 50)
    2. Round limit reached (default: 10)
    3. New entities below threshold (convergence)
    4. New papers below threshold (search exhausted)
    5. All high-priority entities have been searched
    """

    def __init__(
        self,
        config: HAIQUPipelineConfig,
        state: IterativeSearchState,
        graph: Optional[nx.DiGraph] = None
    ):
        self.config = config
        self.state = state
        self.graph = graph

    def set_graph(self, graph: nx.DiGraph) -> None:
        """Update the graph reference."""
        self.graph = graph

    def should_stop(self) -> Tuple[bool, str, str]:
        """
        Check if pipeline should stop.

        Returns:
            Tuple of (should_stop: bool, reason_code: str, reason_message: str)
        """
        checks = [
            self._check_paper_limit,
            self._check_round_limit,
            self._check_new_entities,
            self._check_new_papers,
            self._check_entities_exhausted,
        ]

        for check in checks:
            should_stop, reason_code, message = check()
            if should_stop:
                return True, reason_code, message

        return False, "", "Continue searching"

    def _check_paper_limit(self) -> Tuple[bool, str, str]:
        """Check if paper limit has been reached."""
        if self.state.total_papers >= self.config.max_total_papers:
            return (
                True,
                StopReason.PAPER_LIMIT,
                f"Reached paper limit ({self.state.total_papers}/{self.config.max_total_papers})"
            )
        return False, "", ""

    def _check_round_limit(self) -> Tuple[bool, str, str]:
        """Check if round limit has been reached."""
        if self.state.current_round >= self.config.max_rounds:
            return (
                True,
                StopReason.ROUND_LIMIT,
                f"Reached max rounds ({self.state.current_round}/{self.config.max_rounds})"
            )
        return False, "", ""

    def _check_new_entities(self) -> Tuple[bool, str, str]:
        """Check if new entity discovery has dropped below threshold."""
        # Skip check for first round
        if self.state.current_round <= 1:
            return False, "", ""

        # Check the most recent completed round
        last_round = self.state.current_round - 1
        new_entities = self.state.count_new_entities_in_round(last_round)

        if new_entities < self.config.min_new_entities_per_round:
            return (
                True,
                StopReason.NO_NEW_ENTITIES,
                f"Convergence: only {new_entities} new entities in round {last_round} "
                f"(threshold: {self.config.min_new_entities_per_round})"
            )
        return False, "", ""

    def _check_new_papers(self) -> Tuple[bool, str, str]:
        """Check if paper discovery has dropped below threshold."""
        # Skip check for first round
        if self.state.current_round <= 1:
            return False, "", ""

        # Check the most recent completed round
        last_round = self.state.current_round - 1
        new_papers = self.state.count_papers_in_round(last_round)

        if new_papers < self.config.min_new_papers_per_round:
            return (
                True,
                StopReason.NO_NEW_PAPERS,
                f"Search exhausted: only {new_papers} new papers in round {last_round} "
                f"(threshold: {self.config.min_new_papers_per_round})"
            )
        return False, "", ""

    def _check_entities_exhausted(self) -> Tuple[bool, str, str]:
        """Check if all entities have been searched."""
        if self.graph is None:
            return False, "", ""

        unsearched = self.state.get_unsearched_entities(self.graph)

        if not unsearched:
            return (
                True,
                StopReason.ALL_SEARCHED,
                "All entities have been used for search queries"
            )
        return False, "", ""

    def get_progress_summary(self) -> dict:
        """Get a summary of current progress vs limits."""
        unsearched_count = 0
        if self.graph is not None:
            unsearched_count = len(self.state.get_unsearched_entities(self.graph))

        # Get last round stats
        last_round = max(0, self.state.current_round - 1)
        last_round_papers = self.state.count_papers_in_round(last_round)
        last_round_entities = self.state.count_new_entities_in_round(last_round)

        return {
            'current_round': self.state.current_round,
            'max_rounds': self.config.max_rounds,
            'rounds_remaining': self.config.max_rounds - self.state.current_round,

            'total_papers': self.state.total_papers,
            'max_papers': self.config.max_total_papers,
            'papers_remaining': self.config.max_total_papers - self.state.total_papers,

            'entities_searched': len(self.state.searched_entities),
            'entities_unsearched': unsearched_count,

            'last_round_papers': last_round_papers,
            'last_round_new_entities': last_round_entities,

            'paper_threshold': self.config.min_new_papers_per_round,
            'entity_threshold': self.config.min_new_entities_per_round,
        }

    def estimate_rounds_remaining(self) -> int:
        """Estimate how many more rounds until convergence."""
        progress = self.get_progress_summary()

        # Estimate based on papers
        if progress['papers_remaining'] <= 0:
            return 0

        avg_papers_per_round = (
            progress['total_papers'] / max(1, progress['current_round'])
        )
        papers_rounds = int(progress['papers_remaining'] / max(1, avg_papers_per_round))

        # Estimate based on rounds limit
        max_rounds = progress['rounds_remaining']

        return min(papers_rounds, max_rounds)

    def get_status_message(self) -> str:
        """Get a human-readable status message."""
        progress = self.get_progress_summary()

        return (
            f"Round {progress['current_round']}/{progress['max_rounds']} | "
            f"Papers: {progress['total_papers']}/{progress['max_papers']} | "
            f"Entities searched: {progress['entities_searched']} | "
            f"Last round: {progress['last_round_papers']} papers, "
            f"{progress['last_round_new_entities']} new entities"
        )

    def __repr__(self) -> str:
        progress = self.get_progress_summary()
        return (
            f"ConvergenceChecker(\n"
            f"  round={progress['current_round']}/{progress['max_rounds']},\n"
            f"  papers={progress['total_papers']}/{progress['max_papers']},\n"
            f"  entities_searched={progress['entities_searched']}\n"
            f")"
        )
