from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


AnswerViewKind = Literal[
    "answer_bundle",
    "evidence_table",
    "grouped_summary",
    "distribution",
    "comparison",
    "frontier",
    "ranking",
    "provenance",
    "ranked_subjects",
    "subject_measure",
]


@dataclass
class AnswerView:
    view_id: str
    kind: AnswerViewKind
    source_variable: str
    sufficient: bool
    payload: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AnswerSelection:
    view: AnswerView | None
    supporting_views: list[AnswerView] = field(default_factory=list)
    rationale: str = ""
