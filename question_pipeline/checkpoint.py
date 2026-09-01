"""Episode-boundary continuation checkpoint.

The checkpoint is a small mutable pointer, not a reconstruction system. It is
written after an Episode and its state files have completed. Continuing a run
loads those files and executes ``next_episode``. Work interrupted inside an
Episode is rerun from the preceding completed boundary.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Optional

from method_loop import EpisodeRef, StructuralPath, normalize_structural_path

CHECKPOINT_VERSION = "episode_checkpoint_v1"
CHECKPOINT_FILENAME = "checkpoint.json"
STATE_ROLES = frozenset({"episode", "evidence", "frontier", "memory", "policy", "table"})
REQUIRED_STATE_ROLES = STATE_ROLES


class CheckpointError(ValueError):
    """The requested checkpoint is missing or malformed."""


def _text(name: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CheckpointError(f"{name} must be a non-empty string")
    return value.strip()


def _relative_json_path(name: str, value: object) -> str:
    text = _text(name, value)
    if "\\" in text:
        raise CheckpointError(f"{name} must use POSIX path separators")
    path = PurePosixPath(text)
    if (
        path.is_absolute()
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
        or path.suffix.casefold() not in {".json", ".jsonl"}
    ):
        raise CheckpointError(
            f"{name} must be a normalized relative JSON or JSONL path"
        )
    return path.as_posix()


@dataclass(frozen=True)
class CompletedEpisode:
    """The last durable Episode boundary."""

    episode: EpisodeRef
    record_file: str

    def __post_init__(self) -> None:
        if not isinstance(self.episode, EpisodeRef):
            raise TypeError("CompletedEpisode.episode must be an EpisodeRef")
        object.__setattr__(
            self,
            "record_file",
            _relative_json_path("record_file", self.record_file),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "episode": self.episode.as_record(),
            "record_file": self.record_file,
        }

    @classmethod
    def from_dict(cls, value: object) -> "CompletedEpisode":
        if not isinstance(value, Mapping) or set(value) != {"episode", "record_file"}:
            raise CheckpointError("last_completed_episode has unknown or missing fields")
        episode = value["episode"]
        if not isinstance(episode, Mapping):
            raise CheckpointError("last_completed_episode.episode must be an object")
        return cls(
            episode=EpisodeRef.from_record(episode),
            record_file=value["record_file"],
        )


@dataclass(frozen=True)
class NextEpisode:
    """The explicit boundary action to execute when the run continues."""

    path: StructuralPath
    action: str = "pull_next_episode"

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", normalize_structural_path(self.path))
        if not self.path:
            raise CheckpointError("next_episode.path must name an Episode")
        action = _text("next_episode.action", self.action)
        if action != "pull_next_episode":
            raise CheckpointError(f"unsupported next Episode action {action!r}")
        object.__setattr__(self, "action", action)

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": [list(segment) for segment in self.path],
            "action": self.action,
        }

    @classmethod
    def from_dict(cls, value: object) -> "NextEpisode":
        if not isinstance(value, Mapping) or set(value) != {"path", "action"}:
            raise CheckpointError("next_episode has unknown or missing fields")
        return cls(path=value["path"], action=value["action"])


@dataclass(frozen=True)
class ActiveParent:
    """The completed-child position of a still-active parent Episode."""

    episode: EpisodeRef
    next_unit_index: int

    def __post_init__(self) -> None:
        if not isinstance(self.episode, EpisodeRef):
            raise TypeError("ActiveParent.episode must be an EpisodeRef")
        if (
            isinstance(self.next_unit_index, bool)
            or not isinstance(self.next_unit_index, int)
            or self.next_unit_index < 0
        ):
            raise CheckpointError("active_parent.next_unit_index must be non-negative")

    def to_dict(self) -> dict[str, Any]:
        return {
            "episode": self.episode.as_record(),
            "next_unit_index": self.next_unit_index,
        }

    @classmethod
    def from_dict(cls, value: object) -> "ActiveParent":
        if not isinstance(value, Mapping) or set(value) != {
            "episode",
            "next_unit_index",
        }:
            raise CheckpointError("active_parent has unknown or missing fields")
        episode = value["episode"]
        if not isinstance(episode, Mapping):
            raise CheckpointError("active_parent.episode must be an object")
        return cls(
            episode=EpisodeRef.from_record(episode),
            next_unit_index=value["next_unit_index"],
        )


@dataclass(frozen=True)
class EpisodeCheckpoint:
    """Everything the runner needs at one completed Episode boundary."""

    run_id: str
    lineage_id: str
    last_completed_episode: Optional[CompletedEpisode]
    active_parent: Optional[ActiveParent]
    next_episode: Optional[NextEpisode]
    state_files: Mapping[str, str]
    version: str = CHECKPOINT_VERSION

    def __post_init__(self) -> None:
        if self.version != CHECKPOINT_VERSION:
            raise CheckpointError(f"unsupported checkpoint version {self.version!r}")
        object.__setattr__(self, "run_id", _text("run_id", self.run_id))
        object.__setattr__(self, "lineage_id", _text("lineage_id", self.lineage_id))
        if self.last_completed_episode is not None:
            if not isinstance(self.last_completed_episode, CompletedEpisode):
                raise TypeError(
                    "last_completed_episode must be CompletedEpisode or None"
                )
            if self.last_completed_episode.episode.run_id != self.run_id:
                raise CheckpointError(
                    "last completed Episode belongs to a different run"
                )
        if self.next_episode is not None and not isinstance(
            self.next_episode, NextEpisode
        ):
            raise TypeError("next_episode must be NextEpisode or None")
        if self.active_parent is not None:
            if not isinstance(self.active_parent, ActiveParent):
                raise TypeError("active_parent must be ActiveParent or None")
            if self.active_parent.episode.run_id != self.run_id:
                raise CheckpointError("active parent belongs to a different run")
        if (self.next_episode is None) != (self.active_parent is None):
            raise CheckpointError(
                "active_parent and next_episode must either both be present or both be absent"
            )
        if (
            self.active_parent is not None
            and self.next_episode is not None
            and self.active_parent.episode.path != self.next_episode.path
        ):
            raise CheckpointError("next_episode.path must name the active parent")
        if not isinstance(self.state_files, Mapping):
            raise TypeError("state_files must be a mapping")
        normalized: dict[str, str] = {}
        for role, path in self.state_files.items():
            role_name = _text("state file role", role)
            if role_name in normalized:
                raise CheckpointError(f"duplicate state file role {role_name!r}")
            normalized[role_name] = _relative_json_path(
                f"state_files[{role_name!r}]", path
            )
        unknown = set(normalized) - STATE_ROLES
        missing = REQUIRED_STATE_ROLES - set(normalized)
        if unknown or missing:
            raise CheckpointError(
                f"state file roles must use the generic checkpoint vocabulary; "
                f"unknown={sorted(unknown)}, missing={sorted(missing)}"
            )
        object.__setattr__(self, "state_files", normalized)

    @property
    def complete(self) -> bool:
        return self.next_episode is None

    def to_dict(self) -> dict[str, Any]:
        return {
            "checkpoint_version": self.version,
            "run_id": self.run_id,
            "lineage_id": self.lineage_id,
            "last_completed_episode": (
                self.last_completed_episode.to_dict()
                if self.last_completed_episode is not None
                else None
            ),
            "active_parent": (
                self.active_parent.to_dict()
                if self.active_parent is not None
                else None
            ),
            "next_episode": (
                self.next_episode.to_dict()
                if self.next_episode is not None
                else None
            ),
            "state_files": dict(sorted(self.state_files.items())),
        }

    @classmethod
    def from_dict(cls, value: object) -> "EpisodeCheckpoint":
        expected = {
            "checkpoint_version",
            "run_id",
            "lineage_id",
            "last_completed_episode",
            "active_parent",
            "next_episode",
            "state_files",
        }
        if not isinstance(value, Mapping) or set(value) != expected:
            raise CheckpointError("checkpoint has unknown or missing fields")
        completed = value["last_completed_episode"]
        active_parent = value["active_parent"]
        next_episode = value["next_episode"]
        return cls(
            version=value["checkpoint_version"],
            run_id=value["run_id"],
            lineage_id=value["lineage_id"],
            last_completed_episode=(
                CompletedEpisode.from_dict(completed)
                if completed is not None
                else None
            ),
            active_parent=(
                ActiveParent.from_dict(active_parent)
                if active_parent is not None
                else None
            ),
            next_episode=(
                NextEpisode.from_dict(next_episode)
                if next_episode is not None
                else None
            ),
            state_files=value["state_files"],
        )


def resolve_checkpoint_path(source: str | Path) -> Path:
    """Resolve ``--continue`` from either a run folder or checkpoint file."""

    path = Path(source).expanduser()
    if path.is_dir():
        path = path / CHECKPOINT_FILENAME
    if not path.is_file():
        raise CheckpointError(f"checkpoint file does not exist: {path}")
    return path.resolve()


def load_checkpoint(source: str | Path) -> EpisodeCheckpoint:
    """Load the checkpoint and verify every referenced state file exists."""

    path = resolve_checkpoint_path(source)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CheckpointError(f"checkpoint is unreadable: {path}") from exc
    checkpoint = EpisodeCheckpoint.from_dict(raw)
    referenced = list(checkpoint.state_files.values())
    if checkpoint.last_completed_episode is not None:
        referenced.append(checkpoint.last_completed_episode.record_file)
    missing = [name for name in referenced if not (path.parent / name).is_file()]
    if missing:
        raise CheckpointError(
            "checkpoint references missing state files: " + ", ".join(sorted(missing))
        )
    return checkpoint


def write_checkpoint(
    checkpoint: EpisodeCheckpoint,
    directory: str | Path,
) -> Path:
    """Atomically replace ``checkpoint.json`` after a completed Episode."""

    if not isinstance(checkpoint, EpisodeCheckpoint):
        raise TypeError("write_checkpoint requires an EpisodeCheckpoint")
    root = Path(directory).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    for role, relative in checkpoint.state_files.items():
        if not (root / relative).is_file():
            raise CheckpointError(
                f"cannot checkpoint before state file {role!r} exists: {relative}"
            )
    if checkpoint.last_completed_episode is not None:
        record_file = checkpoint.last_completed_episode.record_file
        if not (root / record_file).is_file():
            raise CheckpointError(
                f"cannot checkpoint before Episode record exists: {record_file}"
            )

    payload = json.dumps(
        checkpoint.to_dict(),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".checkpoint.", suffix=".tmp", dir=root
    )
    target = root / CHECKPOINT_FILENAME
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, target)
        directory_fd = os.open(root, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except BaseException:
        try:
            Path(temporary_name).unlink()
        except OSError:
            pass
        raise
    return target
