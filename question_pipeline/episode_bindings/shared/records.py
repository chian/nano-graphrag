"""Durable records projected from completed episode bindings."""

from __future__ import annotations

from .acquisition_support import *  # internal binding vocabulary

class RecordBinding:

    def _write_page_detail(
        self,
        unit: PageUnit,
        record: Any,
        material: PageMaterial,
        strategy_key: str,
        family: str,
    ) -> None:
        detail = unit.credit_detail
        step = _incidence_step(record)
        row = {
            "unit_label": unit.label,
            "source_id": material.source_id,
            "task_id": str(unit.task.id),
            "strategy_key": strategy_key,
            "strategy_family": family,
            "rank": unit.rank,
            "episode_id": unit.episode_id,
            "episode_path": [list(segment) for segment in unit.episode_path],
            "fate": material.fate.to_dict(),
            "credit_note": material.fate.credit_note,
            "skip_reason": fate_skip_reason(material.fate),
            "counts_toward_verdict": (
                _incidence_input(record.controller_input).status
                != OBSERVATION_EXCLUDED
            ),
            "numerical_snapshot_after": {
                "incidence_estimate": step.report.primary.as_record(),
                "controller_verdict": step.verdict.as_record(),
                "facet_curves": {
                    channel: step.report.estimates[channel].as_record()
                    for channel in step.report.channel_schema.base_channels
                },
                "volume_credit": step.volume_credit.as_record(),
            },
            "spec_digest": self.crediter.spec_digest,
            "crediter_built_at_episode_id": self.run_episode_id,
            "credit_semantics": CREDIT_SEMANTICS,
            "text_chars": material.text_chars,
            "guess_count": len(material.guesses),
            "evidence_commit": (
                material.evidence_commit.to_dict()
                if material.evidence_commit is not None
                else None
            ),
            "evidence_commits": [
                commit.to_dict() for commit in material.evidence_commits
            ],
            "lexical_probes": [
                dict(item) for item in material.probe_history
            ],
            "table_queries": [
                dict(item) for item in material.table_history
            ],
            **(detail.to_dict() if detail is not None else {}),
        }
        self.acquisition_page_details.append(row)
        try:
            self.answers_dir.mkdir(parents=True, exist_ok=True)
            with self._page_detail_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, default=str) + "\n")
        except OSError:  # recording never breaks the run
            pass

    def write_episode_record(self, record: EpisodeRecord) -> None:
        if record.scope_level == self.strategy_grain.name:
            self._episode_records.append(window_episode_record(record.as_record()))
        try:
            self.answers_dir.mkdir(parents=True, exist_ok=True)
            self._episodes_path.write_text(
                json.dumps(
                    {
                        "policy_name": ACQUISITION_POLICY_NAME,
                        "credit_semantics": CREDIT_SEMANTICS,
                        "facet_gate": "crediting_active",
                        "declared_facets": list(self.crediter.declared_facets),
                        "spec_digest": self.crediter.spec_digest,
                        "grains": [
                            grain_disclosure(
                                grain,
                                self.controller.grain_controls[grain.name],
                            )
                            for grain in self.controller.grains
                        ],
                        "strategies": self._episode_records,
                        "run": (
                            window_episode_record(
                                self.controller.record.as_record()
                            )
                            if self.controller.record is not None
                            else {}
                        ),
                    },
                    indent=2,
                    default=str,
                ),
                encoding="utf-8",
            )
        except OSError:  # recording never breaks the run
            pass

    def stranded_frontier_work(self) -> list[dict[str, Any]]:
        classes: list[dict[str, Any]] = []
        for family, tasks in self.frontier.pending_by_family().items():
            ended = self._strategy_ends.get(family, "")
            if ended == END_YIELD_STOP:
                reason = "abandoned_by_verdict"
            elif self.budget.exhausted:
                reason = "budget_spent"
            elif self.termination.stopped:
                reason = "run_terminated"
            elif ended == "":
                reason = "never_opened"
            else:
                reason = "frontier_exhausted"
            classes.append(
                {
                    "strategy_family": family,
                    "pending_tasks": len(tasks),
                    "class": reason,
                    "last_instance_ended_by": ended,
                    "run_termination_reason": self.termination.reason,
                    "instances_opened": (
                        self.proposer.instances_opened().get(family, 0)
                        if self.proposer is not None
                        else 0
                    ),
                }
            )
        return classes

    def write_acquisition_yield(self) -> None:
        path = self.answers_dir / "acquisition_yield.json"
        payload = self.controller.export()
        payload["stranded_frontier_work"] = self.stranded_frontier_work()
        payload["pages_pulled"] = self.budget.spent
        payload["pages_accepted"] = len(self.source_ingestion_ledger)
        payload["orphan_meter"] = dict(self.orphan_snapshot())
        payload["missing_token_owner"] = {
            "module": "criteria",
            "tokens": len(self.missing_tokens()),
        }
        payload["hook_failures"] = [dict(item) for item in self.hook_failures()]
        payload["criteria_projection_version"] = self.criteria_projection_version
        try:
            path.write_text(
                json.dumps(payload, indent=2, default=str),
                encoding="utf-8",
            )
        except Exception as exc:  # noqa: BLE001 - disclosed, never silent
            print(f"  [acquisition] yield export failed: {exc}")

    def run_summary(self) -> dict[str, Any]:
        details = self.acquisition_page_details
        chunk_counts: Counter = Counter()
        rule_counts: Counter = Counter()
        triviality_counts: Counter = Counter()
        source_kind_counts: Counter = Counter()
        counterfactual = 0
        no_credit_pages = 0
        subject_identities: set[str] = set()
        for row in details:
            chunks = row.get("chunk_encounters") or []
            chunk_counts[len(chunks)] += 1
            for attribution in row.get("attributions") or []:
                rule_counts[str(attribution.get("rule") or "")] += 1
                triviality_counts[
                    str(attribution.get("triviality_rule") or "")
                ] += 1
                source_kind_counts[
                    str(attribution.get("source_kind") or "")
                ] += 1
            counterfactual += len(row.get("counterfactual_credits") or [])
            for completion in row.get("row_completions") or []:
                subject_identities.add(str(completion.get("identity") or ""))
            if (
                row.get("counts_toward_verdict")
                and not (row.get("attributions") or [])
                and row.get("skip_reason") == ""
            ):
                no_credit_pages += 1

        exported_subjects = 0
        rows_by_table = self.exported_rows()
        for table, columns in self.crediter.basis.subject_key_columns.items():
            rows = rows_by_table.get(table) or []
            if columns:
                exported_subjects += len(
                    {
                        tuple(str(row.get(column, "")) for column in columns)
                        for row in rows
                        if isinstance(row, Mapping)
                    }
                )
        return {
            "credit_semantics": CREDIT_SEMANTICS,
            "criteria_projection_version": self.criteria_projection_version,
            "pages_pulled": self.budget.spent,
            "pages_with_detail": len(details),
            "credit_rule_counts": dict(rule_counts),
            "triviality_rule_counts": dict(triviality_counts),
            "credit_source_kind_counts": dict(source_kind_counts),
            "counterfactual_credit_count": counterfactual,
            "counterfactual_reading": (
                "the excluded columns could never have become datapoints, so an "
                "empty counterfactual means the exclusion had nothing to remove "
                "on this configuration and NEVER that it was unnecessary"
            ),
            "distinct_completed_subjects": len(subject_identities),
            "distinct_exported_subject_keys": exported_subjects,
            "subject_key_columns": {
                table: list(columns)
                for table, columns in self.crediter.basis.subject_key_columns.items()
            },
            "extracted_pages_with_no_credit": no_credit_pages,
            "chunk_counts": {str(k): v for k, v in sorted(chunk_counts.items())},
            "typed_credit_columns": sum(
                1
                for column in self.crediter.basis.columns
                if column.value_type or column.unit
            ),
            "page_best_guess": {"reports": list(self._page_guess_reports)},
            "proposer": dict(self.proposer.ledger) if self.proposer else {},
            "strategy_instances_opened": (
                self.proposer.instances_opened() if self.proposer else {}
            ),
            "strategy_proposals": list(self._strategy_proposals),
            "stranded_frontier_work": self.stranded_frontier_work(),
            "hook_failures": [dict(item) for item in self.hook_failures()],
            "search_provider_batch": dict(self.search_provider_batch),
        }
