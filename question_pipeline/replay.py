"""Two explicit replay operations with different debugging purposes.

Numerical replay is the inexpensive default diagnostic: it preserves recorded
unit order, observation status, credits, facets, and channel declarations, then
feeds every recorded observation through the current estimator-controller
component.  A shadow verdict is recorded but never truncates the historical
stream.  It performs no provider, extraction, evidence, judgement, table, or
model work.

Saved-source reprocessing is the separate end-to-end diagnostic.  It replaces
only provider search with one saved source and reruns the current page/chunk
binding, including extraction and evidence judgement.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

from rarefaction import (
    CHANNEL_SCHEMA_VERSION,
    CONTROLLER_VERSION,
    INCIDENCE_ESTIMATOR_VERSION,
    OBSERVATION_EXCLUDED,
    OBSERVATION_FAILED,
    OBSERVATION_OBSERVED,
    ChannelSchema,
    ControllerConfig,
    EstimatorController,
)
from rarefaction.method import (
    DEFAULT_ALPHA,
    DEFAULT_EPOCH,
    DEFAULT_SUBSAMPLE_SIZE,
    DEFAULT_WINDOW_SIZE,
)

from .acquisition import CREDIT_SEMANTICS
from .pipeline import PIPELINE_MODE_TABLE_FILL, PipelineConfig, QuestionPipeline
from .search import SearchTask

NUMERICAL_REPLAY_VERSION = "numerical_shadow_replay_v1"
SOURCE_REPLAY_VERSION = "saved_source_replay_v1"
REPLAY_VERSION = SOURCE_REPLAY_VERSION


@dataclass(frozen=True)
class SavedSource:
    """One immutable source blob and the metadata needed to identify it."""

    source_id: str
    url: str
    title: str
    source_query: str
    text: str
    metadata_path: str
    text_path: str
    sha256: str

    def search_result(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "title": self.title,
            "markdown": self.text,
            "replay_version": SOURCE_REPLAY_VERSION,
            "replay_of_source_id": self.source_id,
            "replay_source_sha256": self.sha256,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "url": self.url,
            "title": self.title,
            "source_query": self.source_query,
            "text_chars": len(self.text),
            "metadata_path": self.metadata_path,
            "text_path": self.text_path,
            "sha256": self.sha256,
        }


def load_saved_source(path: str | Path) -> SavedSource:
    """Load a source sidecar or text file without consulting the network."""

    supplied = Path(path).resolve()
    if not supplied.is_file():
        raise FileNotFoundError(f"saved source does not exist: {supplied}")

    metadata: Mapping[str, Any] = {}
    if supplied.suffix.lower() == ".json":
        loaded = json.loads(supplied.read_text(encoding="utf-8"))
        if not isinstance(loaded, Mapping):
            raise ValueError("saved source metadata must be a JSON object")
        metadata = loaded
        source_id = str(metadata.get("id") or supplied.stem)
        text_path = supplied.with_name(f"{source_id}.txt")
        metadata_path = supplied
    else:
        source_id = supplied.stem
        text_path = supplied
        candidate_metadata = supplied.with_suffix(".json")
        metadata_path = candidate_metadata if candidate_metadata.is_file() else supplied
        if candidate_metadata.is_file():
            loaded = json.loads(candidate_metadata.read_text(encoding="utf-8"))
            if not isinstance(loaded, Mapping):
                raise ValueError("saved source metadata must be a JSON object")
            metadata = loaded
            source_id = str(metadata.get("id") or source_id)

    if not text_path.is_file():
        raise FileNotFoundError(
            f"saved source text is missing beside its metadata: {text_path}"
        )
    text = text_path.read_text(encoding="utf-8")
    if not text.strip():
        raise ValueError("saved source text is empty")
    return SavedSource(
        source_id=source_id,
        url=str(metadata.get("url") or ""),
        title=str(metadata.get("title") or ""),
        source_query=str(metadata.get("source_query") or ""),
        text=text,
        metadata_path=str(metadata_path),
        text_path=str(text_path),
        sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
    )


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _is_episode_record(value: Any) -> bool:
    return (
        isinstance(value, Mapping)
        and isinstance(value.get("scope_level"), str)
        and isinstance(value.get("units"), list)
    )


def _episode_roots(payload: Mapping[str, Any]) -> Iterator[Mapping[str, Any]]:
    if _is_episode_record(payload):
        yield payload
        return
    for record in payload.get("strategies") or ():
        if _is_episode_record(record):
            yield record
    run = payload.get("run")
    if _is_episode_record(run):
        yield run


def _walk_episodes(record: Mapping[str, Any]) -> Iterator[Mapping[str, Any]]:
    yield record
    for unit in record.get("units") or ():
        child = unit.get("child") if isinstance(unit, Mapping) else None
        if _is_episode_record(child):
            yield from _walk_episodes(child)


def _channel_schema(record: Mapping[str, Any]) -> ChannelSchema:
    raw = record.get("channel_schema")
    if not isinstance(raw, Mapping):
        raise ValueError("episode has no recorded channel_schema")
    base = tuple(str(value) for value in raw.get("base_channels") or ())
    union = str(raw.get("union_channel") or "") or None
    union_members = tuple(str(value) for value in raw.get("union_members") or ())
    controller_channels = tuple(
        str(value) for value in raw.get("controller_channels") or ()
    )
    return ChannelSchema(
        base_channels=base,
        union_channel=union,
        overlap_allowed=bool(raw.get("overlap_allowed", False)),
        union_members=union_members or None,
        controller_channels=controller_channels or None,
    )


def _controller_config(record: Mapping[str, Any]) -> ControllerConfig:
    raw = record.get("controller")
    if not isinstance(raw, Mapping) or not raw:
        final = record.get("final_verdict")
        raw = final.get("controller") if isinstance(final, Mapping) else None
    if not isinstance(raw, Mapping):
        raise ValueError("episode has no recorded controller declaration")
    gamma_raw = raw.get("gamma")
    if isinstance(gamma_raw, Mapping):
        legacy_values = {float(value) for value in gamma_raw.values()}
        if len(legacy_values) != 1:
            raise ValueError(
                "a legacy per-channel controller with unequal gamma values "
                "cannot be projected onto one hypervolume threshold"
            )
        gamma = legacy_values.pop()
    else:
        gamma = float(gamma_raw)
    return ControllerConfig(
        required_channels=tuple(str(value) for value in raw.get("required_channels") or ()),
        gamma=gamma,
        rho={str(name): value for name, value in (raw.get("rho") or {}).items()},
        streak_length=int(raw.get("streak_length")),
    )


def _estimator_parameters(record: Mapping[str, Any]) -> tuple[int, int, float, str]:
    curve = record.get("curve")
    if not isinstance(curve, Mapping):
        curve = {}
    diagnostics = curve.get("diagnostics")
    if not isinstance(diagnostics, Mapping):
        diagnostics = {}

    def value(name: str, default: Any) -> Any:
        return diagnostics.get(name, curve.get(name, default))

    return (
        int(value("window_size", DEFAULT_WINDOW_SIZE)),
        int(value("subsample_size", DEFAULT_SUBSAMPLE_SIZE)),
        float(value("alpha", DEFAULT_ALPHA)),
        str(curve.get("epoch") or DEFAULT_EPOCH),
    )


def _observation_status(unit: Mapping[str, Any]) -> int:
    explicit = unit.get("observation_status")
    if explicit is not None:
        status = int(explicit)
    elif not bool(unit.get("counts_toward_verdict", True)):
        status = OBSERVATION_EXCLUDED
    elif bool(unit.get("crediting_disabled", False)):
        status = OBSERVATION_FAILED
    else:
        status = OBSERVATION_OBSERVED
    if status not in {
        OBSERVATION_OBSERVED,
        OBSERVATION_FAILED,
        OBSERVATION_EXCLUDED,
    }:
        raise ValueError(f"unknown recorded observation status {status!r}")
    eligible = bool(unit.get("eligible", status == OBSERVATION_OBSERVED))
    if eligible != (status == OBSERVATION_OBSERVED):
        raise ValueError("recorded eligible flag conflicts with observation status")
    return status


def _recorded_first_stop(record: Mapping[str, Any]) -> dict[str, Any] | None:
    for position, unit in enumerate(record.get("units") or (), start=1):
        snapshot = unit.get("numerical_snapshot_after")
        verdict = snapshot.get("controller_verdict") if isinstance(snapshot, Mapping) else None
        if isinstance(verdict, Mapping) and bool(verdict.get("stop")):
            return {
                "observation_number": position,
                "unit_index": unit.get("unit_index"),
                "unit_label": str(unit.get("unit_label") or ""),
                "outcome": str(verdict.get("outcome") or ""),
            }
    return None


def _comparison(
    recorded: Mapping[str, Any] | None,
    shadow: Mapping[str, Any] | None,
) -> str:
    if recorded is None and shadow is None:
        return "same_no_stop"
    if recorded is None:
        return "shadow_stop_only"
    if shadow is None:
        return "recorded_stop_only"
    left = int(recorded["observation_number"])
    right = int(shadow["observation_number"])
    if left == right:
        return "same_stop_position"
    return "shadow_earlier" if right < left else "shadow_later"


def _compact_estimates(report: Any) -> dict[str, Any]:
    return {
        channel: {
            "incidence_samples": estimate.incidence_samples,
            "observed_results": estimate.observed_results.as_record(),
            "expected_results": estimate.expected_results.as_record(),
            "remaining_results": estimate.remaining_results.as_record(),
            "control_statistics": {
                name: band.as_record()
                for name, band in estimate.control_statistics.items()
            },
            "diagnostics": dict(estimate.diagnostics),
            "formula_versions": dict(estimate.formula_versions),
        }
        for channel, estimate in report.estimates.items()
    }


def replay_numerical_control(
    *,
    episodes_path: str | Path,
    output_dir: str | Path,
    episode_ids: Sequence[str] = (),
) -> dict[str, Any]:
    """Replay frozen observations through current numerical code in shadow.

    A predicted stop is an output only.  Every recorded unit is advanced in
    original order, including units after that predicted stop.  The supplied
    artifact is never mutated and no pipeline binding is invoked.
    """

    source_path = Path(episodes_path).resolve()
    if not source_path.is_file():
        raise FileNotFoundError(f"episode artifact does not exist: {source_path}")
    artifact_sha256 = _file_sha256(source_path)
    with source_path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, Mapping):
        raise ValueError("episode artifact must be a JSON object")

    selected = set(str(value) for value in episode_ids)
    seen: set[str] = set()
    records: list[Mapping[str, Any]] = []
    for root in _episode_roots(payload):
        for record in _walk_episodes(root):
            identity = str(record.get("episode_id") or "")
            if not identity:
                identity = json.dumps(record.get("path") or (), separators=(",", ":"))
            if identity in seen:
                continue
            seen.add(identity)
            if not selected or str(record.get("episode_id") or "") in selected:
                records.append(record)
    if selected:
        found = {str(record.get("episode_id") or "") for record in records}
        missing = selected - found
        if missing:
            raise ValueError(f"episode ids not found in artifact: {sorted(missing)}")
    if not records:
        raise ValueError("episode artifact contains no selected Episode records")

    for record in records:
        units = record.get("units") or ()
        if int(record.get("units_consumed", -1)) != len(units):
            raise ValueError(
                f"episode {record.get('episode_id')!r} is incomplete: "
                f"units_consumed={record.get('units_consumed')!r}, "
                f"serialized_units={len(units)}"
            )
        for unit in units:
            window = unit.get("window") if isinstance(unit, Mapping) else None
            if isinstance(window, Mapping) and bool(window.get("windowed")):
                raise ValueError(
                    f"episode {record.get('episode_id')!r} has windowed incidence "
                    "identities; exact numerical replay is impossible"
                )

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    trace_path = output_path / "numerical_replay_steps.jsonl"
    episode_results: list[dict[str, Any]] = []
    grains: Counter[str] = Counter()
    comparisons: Counter[str] = Counter()
    observations = 0

    with trace_path.open("w", encoding="utf-8") as trace:
        for record in records:
            path = tuple(
                (str(segment[0]), str(segment[1]))
                for segment in record.get("path") or ()
            )
            if not path:
                raise ValueError("episode has no recorded scope path")
            schema = _channel_schema(record)
            config = _controller_config(record)
            window_size, subsample_size, alpha, initial_epoch = _estimator_parameters(record)
            units = record.get("units") or ()
            if units and str(units[0].get("epoch") or ""):
                initial_epoch = str(units[0]["epoch"])
            component = EstimatorController(
                scope_path=path,
                epoch=initial_epoch,
                channel_schema=schema,
                control=config,
                window_size=window_size,
                subsample_size=subsample_size,
                alpha=alpha,
            )
            shadow_stops: list[dict[str, Any]] = []
            for position, unit in enumerate(units, start=1):
                unit_epoch = str(unit.get("epoch") or component.epoch)
                if unit_epoch != component.epoch:
                    component = component.transitioned(unit_epoch)
                status = _observation_status(unit)
                credits = tuple(str(value) for value in unit.get("credits") or ())
                facets = {
                    str(name): tuple(str(value) for value in values)
                    for name, values in (unit.get("facets") or {}).items()
                }
                # Failed/excluded units retained their accepted identities for
                # audit, but those identities were not incidence observations.
                if status != OBSERVATION_OBSERVED:
                    credits = ()
                    facets = {}
                step = component.advance(
                    str(unit.get("unit_label") or f"unit-{position - 1}"),
                    credits,
                    observation_status=status,
                    facets=facets,
                    is_root=len(path) == 1,
                )
                observations += 1
                stop_record = None
                if step.verdict.stop:
                    stop_record = {
                        "observation_number": position,
                        "unit_index": unit.get("unit_index"),
                        "unit_label": str(unit.get("unit_label") or ""),
                        "outcome": step.verdict.outcome,
                        "epoch": component.epoch,
                    }
                    shadow_stops.append(stop_record)
                trace.write(
                    json.dumps(
                        {
                            "replay_version": NUMERICAL_REPLAY_VERSION,
                            "episode_id": str(record.get("episode_id") or ""),
                            "path": [list(segment) for segment in path],
                            "observation_number": position,
                            "unit_index": unit.get("unit_index"),
                            "unit_label": str(unit.get("unit_label") or ""),
                            "observation_status": status,
                            "recorded_credit_count": len(unit.get("credits") or ()),
                            "shadow_stop": stop_record is not None,
                            "shadow_verdict": step.verdict.as_record(),
                            "shadow_estimates": _compact_estimates(step.report),
                        },
                        separators=(",", ":"),
                        default=str,
                    )
                    + "\n"
                )

            recorded_stop = _recorded_first_stop(record)
            shadow_stop = shadow_stops[0] if shadow_stops else None
            comparison = _comparison(recorded_stop, shadow_stop)
            grain = str(record.get("scope_level") or path[-1][0])
            grains[grain] += 1
            comparisons[comparison] += 1
            final_report = component.report()
            episode_results.append(
                {
                    "episode_id": str(record.get("episode_id") or ""),
                    "path": [list(segment) for segment in path],
                    "grain": grain,
                    "recorded": {
                        "units_consumed": int(record.get("units_consumed", 0)),
                        "ended_by": str(record.get("ended_by") or ""),
                        "end_reason": str(record.get("end_reason") or ""),
                        "first_stop": recorded_stop,
                        "controller_version": str(
                            (record.get("controller") or {}).get("version") or ""
                        ),
                    },
                    "shadow": {
                        "observations_consumed": len(units),
                        "all_recorded_observations_consumed": True,
                        "first_stop": shadow_stop,
                        "stop_observation_numbers": [
                            value["observation_number"] for value in shadow_stops
                        ],
                        "final_verdict": component.verdict().as_record(),
                        "final_estimates": _compact_estimates(final_report),
                        "estimator_parameters": {
                            "window_size": window_size,
                            "subsample_size": subsample_size,
                            "alpha": alpha,
                        },
                    },
                    "comparison": comparison,
                }
            )

    criteria = {
        name: payload.get(name)
        for name in ("credit_semantics", "facet_gate", "declared_facets", "spec_digest")
        if name in payload
    }
    summary = {
        "replay_version": NUMERICAL_REPLAY_VERSION,
        "operation": "numerical_shadow_recalibration",
        "input": {
            "artifact": str(source_path),
            "sha256": artifact_sha256,
            "criteria": criteria,
            "selected_episode_ids": sorted(selected),
        },
        "execution": {
            "provider_calls": 0,
            "model_calls": 0,
            "extraction_calls": 0,
            "evidence_judgement_calls": 0,
            "table_writes": 0,
            "historical_stream_mutated": False,
            "shadow_verdicts_truncate_stream": False,
        },
        "current_numerical_versions": {
            "incidence_estimator": INCIDENCE_ESTIMATOR_VERSION,
            "numerical_controller": CONTROLLER_VERSION,
            "channel_schema": CHANNEL_SCHEMA_VERSION,
        },
        "aggregate": {
            "episodes": len(episode_results),
            "observations": observations,
            "episodes_by_grain": dict(sorted(grains.items())),
            "comparisons": dict(sorted(comparisons.items())),
        },
        "trace": str(trace_path),
        "episodes": episode_results,
    }
    summary_path = output_path / "numerical_replay_summary.json"
    summary_path.write_text(
        json.dumps(summary, indent=2, default=str),
        encoding="utf-8",
    )
    return summary


async def replay_saved_source(
    *,
    question: str,
    source: SavedSource,
    table_spec_paths: Sequence[str | Path],
    output_dir: str | Path,
    model: str | None = None,
    fast_model: str | None = None,
    chunk_size: int = 2000,
    chunk_overlap: int = 200,
    extraction_concurrency: int = 1,
    extraction_timeout_sec: float | None = None,
    strategy_key: str = "source_replay#0",
) -> dict[str, Any]:
    """Reprocess one saved source and write an auditable replay record."""

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    replay_input = {
        "replay_version": SOURCE_REPLAY_VERSION,
        "provider_search_called": False,
        "source": source.to_dict(),
        "configuration": {
            "question": str(question),
            "table_spec_paths": [str(Path(item)) for item in table_spec_paths],
            "model": model,
            "fast_model": fast_model,
            "chunk_size": int(chunk_size),
            "chunk_overlap": int(chunk_overlap),
            "extraction_concurrency": int(extraction_concurrency),
            "extraction_timeout_sec": extraction_timeout_sec,
            "strategy_key": str(strategy_key),
        },
    }
    (output_path / "replay_input.json").write_text(
        json.dumps(replay_input, indent=2, default=str),
        encoding="utf-8",
    )
    config = PipelineConfig(
        question=str(question),
        pipeline_mode=PIPELINE_MODE_TABLE_FILL,
        output_dir=str(output_dir),
        answer_mode="table",
        table_spec_path=[str(Path(item)) for item in table_spec_paths],
        chunk_size=int(chunk_size),
        chunk_overlap=int(chunk_overlap),
        extraction_concurrency=int(extraction_concurrency),
        extraction_timeout_sec=extraction_timeout_sec,
        model=model,
        fast_model=fast_model,
    )
    pipeline = QuestionPipeline(config)
    task = SearchTask(
        query=source.source_query or str(question),
        topic="source_replay",
        expansion_op="source_replay",
        producer_class="source_replay",
        metadata={
            "replay_version": REPLAY_VERSION,
            "replay_of_source_id": source.source_id,
            "replay_source_sha256": source.sha256,
        },
    )
    episode = pipeline.provider_binding.build_source_replay_episode(
        task,
        source.search_result(),
        strategy_key=strategy_key,
    )
    record = await pipeline.acquisition.run(episode)
    pipeline.provider_binding.write_episode_record(record)
    pipeline.provider_binding.write_acquisition_yield()

    assignments = list(pipeline.crediter.checkpoint_assignments())
    tables = {
        str(name): [dict(row) for row in rows]
        for name, rows in pipeline.crediter.rows_by_name.items()
    }
    summary = {
        **replay_input,
        "credit_semantics": CREDIT_SEMANTICS,
        "episode": {
            "episode_id": record.episode_id,
            "ended_by": record.ended_by,
            "end_reason": record.end_reason,
            "units_consumed": record.units_consumed,
        },
        "credit": {
            "assignments": len(assignments),
            "new_slots": sum(bool(row.get("new_to_table")) for row in assignments),
            "repeat_slots": sum(
                not bool(row.get("new_to_table")) for row in assignments
            ),
            "reported": sum(
                str(row.get("source_kind") or "") == "verbatim"
                for row in assignments
            ),
            "best_guess": sum(
                str(row.get("source_kind") or "") == "best_guess"
                for row in assignments
            ),
        },
        "table_rows": {name: len(rows) for name, rows in tables.items()},
        "page_details": len(pipeline.provider_binding.acquisition_page_details),
        "hook_failures": [dict(item) for item in pipeline.hook_failures],
    }

    answers_dir = output_path / "answers"
    tables_dir = answers_dir / "tables"
    answers_dir.mkdir(parents=True, exist_ok=True)
    tables_dir.mkdir(parents=True, exist_ok=True)
    (answers_dir / "replay_assignments.json").write_text(
        json.dumps(assignments, indent=2, default=str),
        encoding="utf-8",
    )
    for name, rows in tables.items():
        (tables_dir / f"replay_{name}.json").write_text(
            json.dumps(rows, indent=2, default=str),
            encoding="utf-8",
        )
    (answers_dir / "replay_summary.json").write_text(
        json.dumps(summary, indent=2, default=str),
        encoding="utf-8",
    )
    return summary


__all__ = [
    "NUMERICAL_REPLAY_VERSION",
    "SOURCE_REPLAY_VERSION",
    "REPLAY_VERSION",
    "SavedSource",
    "load_saved_source",
    "replay_numerical_control",
    "replay_saved_source",
]
