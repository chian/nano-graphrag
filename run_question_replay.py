#!/usr/bin/env python
"""Replay recorded numerical observations or reprocess one saved source."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from question_pipeline.acquisition import lexical_threshold_adapter
from question_pipeline.replay import (
    load_saved_source,
    replay_numerical_control,
    replay_saved_source,
)


def _gamma_overrides(values: list[str]) -> dict[str, float]:
    overrides: dict[str, float] = {}
    for value in values:
        grain, separator, raw_gamma = value.partition("=")
        if not separator or not grain.strip() or not raw_gamma.strip():
            raise argparse.ArgumentTypeError(
                "--gamma-override must have the form GRAIN=VALUE"
            )
        grain = grain.strip()
        if grain in overrides:
            raise argparse.ArgumentTypeError(
                f"duplicate --gamma-override for grain {grain!r}"
            )
        try:
            overrides[grain] = float(raw_gamma)
        except ValueError as exc:
            raise argparse.ArgumentTypeError(
                f"gamma for grain {grain!r} must be numeric"
            ) from exc
    return overrides


def _require_new_output(parser: argparse.ArgumentParser, raw_path: str) -> Path:
    output_dir = Path(raw_path)
    if output_dir.exists():
        launcher_files = {"runner.log", "worker.pid"}
        unexpected = [
            item.name for item in output_dir.iterdir() if item.name not in launcher_files
        ]
        if unexpected:
            parser.error("--output-dir must be new or contain only launcher files")
    return output_dir


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    numerical = commands.add_parser(
        "numerical",
        help="Shadow-replay recorded observations through numerical control only.",
    )
    numerical.add_argument(
        "--episodes",
        required=True,
        help="acquisition_episodes.json or one completed_episode.json artifact.",
    )
    numerical.add_argument(
        "--current-binding-thresholds",
        action="store_true",
        help="Apply the current question-pipeline threshold adapter in shadow.",
    )
    numerical.add_argument("--output-dir", required=True)
    numerical.add_argument(
        "--episode-id",
        action="append",
        default=[],
        help="Restrict recalculation to an exact Episode id; may be repeated.",
    )
    numerical.add_argument(
        "--gamma-override",
        action="append",
        default=[],
        metavar="GRAIN=VALUE",
        help=(
            "Use an explicit shadow gamma for one grain while preserving the "
            "recorded observations and all other controller settings; may be repeated."
        ),
    )

    source_parser = commands.add_parser(
        "source",
        help="Reprocess one saved source through extraction and judgement.",
    )
    source_parser.add_argument("--source", required=True, help="Saved source .json or .txt file.")
    source_parser.add_argument("--question", required=True, help="Table-fill research question.")
    source_parser.add_argument(
        "--table-spec-path",
        action="append",
        required=True,
        help="Table contract used for current extraction; may be repeated.",
    )
    source_parser.add_argument("--output-dir", required=True, help="New replay output directory.")
    source_parser.add_argument("--model", default="gpt-5.5")
    source_parser.add_argument("--fast-model", default="gpt-5.4-mini")
    source_parser.add_argument("--chunk-size", type=int, default=2000)
    source_parser.add_argument("--chunk-overlap", type=int, default=200)
    source_parser.add_argument("--extraction-concurrency", type=int, default=1)
    source_parser.add_argument("--extraction-timeout-sec", type=float, default=None)
    args = parser.parse_args()

    output_dir = _require_new_output(parser, args.output_dir)
    if args.command == "numerical":
        try:
            gamma_overrides = _gamma_overrides(args.gamma_override)
        except argparse.ArgumentTypeError as exc:
            parser.error(str(exc))
        if gamma_overrides and args.current_binding_thresholds:
            parser.error(
                "--gamma-override and --current-binding-thresholds are mutually exclusive"
            )
        summary = replay_numerical_control(
            episodes_path=args.episodes,
            output_dir=output_dir,
            episode_ids=args.episode_id,
            gamma_overrides=gamma_overrides,
            threshold_adapter=(
                lexical_threshold_adapter
                if args.current_binding_thresholds
                else None
            ),
            threshold_adapter_name=(
                "question_pipeline.lexical_initial_empty_prefix_v1"
                if args.current_binding_thresholds
                else ""
            ),
        )
        print(
            json.dumps(
                {
                    "operation": summary["operation"],
                    "aggregate": summary["aggregate"],
                    "summary": str(output_dir / "numerical_replay_summary.json"),
                    "trace": summary["trace"],
                },
                indent=2,
            )
        )
        return

    source = load_saved_source(args.source)
    summary = asyncio.run(
        replay_saved_source(
            question=args.question,
            source=source,
            table_spec_paths=args.table_spec_path,
            output_dir=output_dir,
            model=args.model,
            fast_model=args.fast_model,
            chunk_size=args.chunk_size,
            chunk_overlap=args.chunk_overlap,
            extraction_concurrency=args.extraction_concurrency,
            extraction_timeout_sec=args.extraction_timeout_sec,
        )
    )
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()
