"""
Separate loader for non-graph schema profiles.
These profiles contain prompt/suitability metadata and are intentionally
kept out of the graph schema contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

import yaml


@dataclass
class SchemaProfile:
    domain_name: str
    suitability_criteria: Dict
    contrastive_patterns: List[str]
    question_generation_focus: List[str]


def load_schema_profile(schema_name: str, profiles_dir: Path | None = None) -> SchemaProfile:
    if profiles_dir is None:
        profiles_dir = Path(__file__).parent
    profile_path = profiles_dir / f"{schema_name}.yaml"
    if not profile_path.exists():
        return SchemaProfile(
            domain_name=schema_name,
            suitability_criteria={},
            contrastive_patterns=[],
            question_generation_focus=[],
        )
    data = yaml.safe_load(profile_path.read_text()) or {}
    return SchemaProfile(
        domain_name=data.get("domain_name", schema_name),
        suitability_criteria=data.get("suitability_criteria", {}),
        contrastive_patterns=data.get("contrastive_patterns", []),
        question_generation_focus=data.get("question_generation_focus", []),
    )
