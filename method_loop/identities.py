"""Canonical structural identities for the generic Episode method tree.

Identity inputs are deliberately smaller than the records they identify.
Human-readable unit labels and output-directory names are not accepted here,
so neither can accidentally become identity material.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Mapping

__all__ = [
    "IDENTITY_VERSION",
    "EpisodeRef",
    "normalize_structural_path",
    "StructuralPath",
    "UnitRef",
]

IDENTITY_VERSION = "runtime_identity_v1"
StructuralPath = tuple[tuple[str, str], ...]


def normalize_structural_path(value: object) -> StructuralPath:
    """Validate a structural path without coercing any segment."""

    if not isinstance(value, (tuple, list)) or not value:
        raise ValueError("identity path must be a non-empty sequence")
    out: list[tuple[str, str]] = []
    for segment in value:
        if not isinstance(segment, (tuple, list)) or len(segment) != 2:
            raise ValueError("identity path segments must be two-item sequences")
        grain, key = segment
        if not isinstance(grain, str) or not grain:
            raise ValueError("identity path grain names must be non-empty strings")
        if not isinstance(key, str) or not key:
            raise ValueError("identity path keys must be non-empty strings")
        out.append((grain, key))
    return tuple(out)


def _text(name: str, value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _index(name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a zero-based non-negative integer")
    return value


def _identifier(kind: str, material: Mapping[str, object]) -> str:
    payload = {
        "identity_version": IDENTITY_VERSION,
        "kind": kind,
        **material,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"{kind}_{hashlib.sha256(encoded).hexdigest()}"


@dataclass(frozen=True)
class EpisodeRef:
    """One episode: the run identity plus its complete structural path."""

    run_id: str
    path: StructuralPath
    episode_id: str = field(init=False)

    def __post_init__(self) -> None:
        run_id = _text("run_id", self.run_id)
        path = normalize_structural_path(self.path)
        object.__setattr__(self, "run_id", run_id)
        object.__setattr__(self, "path", path)
        object.__setattr__(
            self,
            "episode_id",
            _identifier(
                "episode",
                {"run_id": run_id, "path": [list(segment) for segment in path]},
            ),
        )

    def as_record(self) -> dict:
        return {
            "identity_version": IDENTITY_VERSION,
            "run_id": self.run_id,
            "path": [list(segment) for segment in self.path],
            "episode_id": self.episode_id,
        }

    @classmethod
    def from_record(cls, record: Mapping[str, object]) -> "EpisodeRef":
        if not isinstance(record, Mapping):
            raise TypeError("EpisodeRef state must be a mapping")
        expected = {"identity_version", "run_id", "path", "episode_id"}
        if set(record) != expected or record["identity_version"] != IDENTITY_VERSION:
            raise ValueError("malformed or unsupported EpisodeRef state")
        ref = cls(run_id=record["run_id"], path=record["path"])
        if record["episode_id"] != ref.episode_id:
            raise ValueError("EpisodeRef episode_id does not match run_id and path")
        return ref


@dataclass(frozen=True)
class UnitRef:
    """One unit position inside an episode; labels are intentionally absent."""

    episode_id: str
    unit_index: int
    unit_id: str = field(init=False)

    def __post_init__(self) -> None:
        episode_id = _text("episode_id", self.episode_id)
        unit_index = _index("unit_index", self.unit_index)
        object.__setattr__(self, "episode_id", episode_id)
        object.__setattr__(self, "unit_index", unit_index)
        object.__setattr__(
            self,
            "unit_id",
            _identifier(
                "unit",
                {"episode_id": episode_id, "unit_index": unit_index},
            ),
        )

    def as_record(self) -> dict:
        return {
            "identity_version": IDENTITY_VERSION,
            "episode_id": self.episode_id,
            "unit_index": self.unit_index,
            "unit_id": self.unit_id,
        }

    @classmethod
    def from_record(cls, record: Mapping[str, object]) -> "UnitRef":
        if not isinstance(record, Mapping):
            raise TypeError("UnitRef state must be a mapping")
        expected = {"identity_version", "episode_id", "unit_index", "unit_id"}
        if set(record) != expected or record["identity_version"] != IDENTITY_VERSION:
            raise ValueError("malformed or unsupported UnitRef state")
        ref = cls(record["episode_id"], record["unit_index"])
        if record["unit_id"] != ref.unit_id:
            raise ValueError("UnitRef unit_id does not match episode_id and unit_index")
        return ref
