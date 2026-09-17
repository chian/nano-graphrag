"""Reusable language for turning source tables into grounded entity mentions."""

from .executor import execute_program
from .program import language_reference, parse_program
from .resolution import apply_resolution, candidate_components, resolution_view
from .source import TableWorkspace, discover_table_regions, text_without_table_regions
from .types import (
    AdmissionRule,
    CandidateConnection,
    FieldAssertion,
    LanguageResult,
    Mention,
    RuleResult,
    SourceCell,
    SourceLine,
    SourceRow,
    SourceSpan,
    TableProgram,
    TableRegion,
    TargetEntity,
    TargetField,
)

__all__ = (
    "AdmissionRule",
    "CandidateConnection",
    "FieldAssertion",
    "LanguageResult",
    "Mention",
    "RuleResult",
    "SourceCell",
    "SourceLine",
    "SourceRow",
    "SourceSpan",
    "TableProgram",
    "TableRegion",
    "TableWorkspace",
    "TargetEntity",
    "TargetField",
    "apply_resolution",
    "candidate_components",
    "discover_table_regions",
    "execute_program",
    "language_reference",
    "parse_program",
    "resolution_view",
    "text_without_table_regions",
)
