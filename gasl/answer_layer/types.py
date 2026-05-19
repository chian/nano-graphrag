from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


AnswerViewKind = Literal[
    "ranked_subjects",
    "subject_measure",
    "distribution",
    "comparison",
    "evidence_lookup",
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
    rationale: str = ""
