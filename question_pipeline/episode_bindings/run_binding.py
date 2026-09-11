"""The run Episode binding."""

from __future__ import annotations

from .shared.acquisition_support import *  # internal binding vocabulary

class StrategyProposer:
    """The ``run`` grain's source: the switch edge.

    Pull order, and every step before the model is a typed check:

    1. the run's terminal state (a goal fulfilled, an execution error, a spent
       budget) -> the named ``SourceEnd`` its ``StopReason`` maps to;
    2. provider health;
    3. the page budget, at this grain as well as inside a strategy -- so a spent
       budget ends the run rather than producing a stream of ``bound_hit``
       children the parent's history excludes, which would leave the run's
       observation count at zero forever;
    4. a declared family eligible to open -> build it. **No model call.**
    5. otherwise sample.

    THE MODEL SITS ONLY IN STEP 5, and only in that step's string work. It
    samples candidate strings and reports a number. It does not decide *whether*
    to propose -- that is the run grain's own verdict, read after every unit --
    and it does not decide whether a candidate is distant enough: the comparison
    in :func:`control.select_first_clearing` does, over a key this class mints in
    code from declared inputs.
    """

    def __init__(
        self,
        *,
        declared: Callable[[], Sequence[str]],
        sample: Callable[[Sequence[Mapping[str, Any]]], Awaitable[Sequence[Mapping[str, Any]]]],
        build: Callable[[str, str, Sequence[str]], Episode],
        catalog: AbstractSet[str],
        declared_target_ids: Callable[[], AbstractSet[str]],
        budget: SourceBudget,
        health: ProviderHealth,
        termination: RunTermination,
        open_cost_scope: Callable[
            [str, str, str, tuple[tuple[str, str], ...]], Any
        ],
        episode_id: str,
        episode_path: tuple[tuple[str, str], ...],
        run_key: str,
        record_proposal: Optional[Callable[[Mapping[str, Any]], None]] = None,
        distance_floor: float = STRATEGY_DISTANCE_FLOOR,
        max_samples: int = MAX_PROPOSAL_SAMPLES,
    ) -> None:
        self._declared = declared
        self._sample = sample
        self._build = build
        self._catalog = catalog
        self._declared_target_ids = declared_target_ids
        self._budget = budget
        self._health = health
        self._termination = termination
        self._open_cost_scope = open_cost_scope
        self._episode_id = str(episode_id)
        self._episode_path = tuple(episode_path)
        self._run_key = run_key
        self._record_proposal = record_proposal
        self._floor = float(distance_floor)
        self._max_samples = max(1, int(max_samples))
        self._opened_content: set[str] = set()
        self._opened: list[dict[str, Any]] = []
        self._opened_token_sets: list[frozenset[str]] = []
        self._instances: dict[str, int] = {}
        self._pulls = 0
        self._resume_episode: Optional[Episode] = None
        # The candidate partition, emitted whether or not any cell is zero:
        # `candidates == operator_not_in_catalog + cleared_floor + below_floor`,
        # with `already_opened` a subset of `cleared_floor`. A zero
        # `operator_not_in_catalog` is the finding that the model stayed inside
        # its catalog on this configuration -- never an absent instrument.
        self.ledger: dict[str, Any] = {
            "pulls": 0,
            "samples": 0,
            "candidates": 0,
            REJECT_OPERATOR_NOT_IN_CATALOG: 0,
            "cleared_floor": 0,
            "below_floor": 0,
            "already_opened": 0,
            "accepted": 0,
            "end": "",
            "distance_floor": self._floor,
            "max_proposal_samples": self._max_samples,
        }

    def opened_content_keys(self) -> tuple[str, ...]:
        return tuple(sorted(self._opened_content))

    def instances_opened(self) -> dict[str, int]:
        """Instances opened per family -- THE WHOLE MAP, and public.

        C37's observable. It is emitted for every family this run opened, not
        only for the families the frontier still holds work for: a family that
        was opened and drained its queue is exactly the case the re-open bound
        is about, and reporting only the families with pending work would hide
        it. Public because the run record is another module's, and reaching into
        a private attribute to build a disclosure makes that disclosure
        something no one can change here without breaking a caller.
        """

        return dict(self._instances)

    def checkpoint_state(self) -> dict[str, Any]:
        """Return the exact string-policy state needed at the next pull."""

        return {
            "opened_content": sorted(self._opened_content),
            "opened": [dict(item) for item in self._opened],
            "instances": dict(self._instances),
            "pulls": self._pulls,
            "ledger": dict(self.ledger),
        }

    def restore_checkpoint_state(self, state: Mapping[str, Any]) -> None:
        """Restore a state emitted by :meth:`checkpoint_state`."""

        opened = [dict(item) for item in (state.get("opened") or ())]
        self._opened = opened
        self._opened_content = {
            str(value) for value in (state.get("opened_content") or ())
        }
        self._opened_token_sets = [
            _proposal_tokens(
                str(item.get("family") or ""),
                item.get("targets") or (),
                item.get("seeds") or (),
            )
            for item in opened
        ]
        self._instances = {
            str(name): int(value)
            for name, value in dict(state.get("instances") or {}).items()
        }
        self._pulls = int(state.get("pulls") or 0)
        restored_ledger = dict(state.get("ledger") or {})
        if restored_ledger:
            self.ledger.update(restored_ledger)
        self.ledger["pulls"] = self._pulls

    def resume_with(self, episode: Episode) -> None:
        """Return the interrupted child once before proposing new work."""

        if self._resume_episode is not None:
            raise ValueError("a proposer may hold only one resumed child")
        self._resume_episode = episode

    async def next(self, view: EpisodeView) -> Episode | None | SourceEnd:
        if self._resume_episode is not None:
            episode = self._resume_episode
            self._resume_episode = None
            return episode
        if self._termination.stopped:
            end = self._termination.source_end()
            self.ledger["end"] = (
                end.reason if end is not None else STOP_REASON_FRONTIER_EXHAUSTED
            )
            return end
        if self._health.fatal:
            self.ledger["end"] = FATAL_SEARCH_ERROR
            return SourceEnd(END_SOURCE_FAILED, FATAL_SEARCH_ERROR)
        if self._budget.exhausted:
            self.ledger["end"] = BOUND_KIND_RUN_SOURCE_BUDGET
            return SourceEnd(END_BOUND_HIT, BOUND_KIND_RUN_SOURCE_BUDGET)

        self._pulls += 1
        self.ledger["pulls"] = self._pulls
        # THE SCOPE WRAPS THE WHOLE PULL, not just the model sample. The
        # declared-family path at step 4 reaches the same billed arm planner as
        # the sampled path does, so a scope around `sample(...)` alone would
        # bill every declared-family pull's planner spend to the orphan meter --
        # free in the record and expensive in reality, which is the exact bias
        # cost accounting exists to remove. A pull that returns a declared
        # family therefore still writes a record, with `proposal_samples: 0`.
        #
        # `observation_id` is `f"{run_key}#p{n}"` where n counts PULLS, not
        # samples. It joins to the run record by `run_key` and to
        # `strategy_proposals.jsonl` by pull number, so a cost record on this
        # edge joins to something -- which is the defect this scope removes, one
        # level out.
        #
        with self._open_cost_scope(
            ObservationKind.STRATEGY_PROPOSAL.value,
            f"{self._run_key}#p{self._pulls}",
            self._episode_id,
            self._episode_path,
        ):
            episode = await self._pull()
        return episode

    async def _pull(self) -> Episode | None | SourceEnd:
        """The pull itself. IT TAKES NO VIEW, and that is the point.

        Every input is a typed object this class was handed -- the run's
        terminal state, provider health, the page budget, the declared families,
        and the declared target ids. The proposer reads no curve, no verdict and
        no unit count, so there is no second acquisition decision hidden here.
        """

        # Step 4: a declared family eligible to open. NO MODEL CALL. `declared`
        # is the set of families with pending frontier work that the
        # deterministic planner routes and that are ELIGIBLE TO RE-OPEN under
        # the caller's written rule -- it is NOT the whole operator catalog,
        # which would stay deterministic while bypassing the pseudo-gradient
        # entirely.
        #
        # The declared path deliberately does not consult the opened-content
        # set. Eligibility is the caller's rule over the child records this run
        # already holds ("the last instance ended `exhausted` AND the frontier
        # now holds work for it"), and a content key fixed per family would make
        # a family that merely ran out of queued work at the instant it was
        # pulled unreopenable for the rest of the run -- work planned for it
        # would sit in the frontier forever with nothing saying so. The key it
        # records is instance-scoped so a proposal can never collide with it.
        for family in self._declared():
            instance = self._instances.get(family, 0)
            return self._open(
                family,
                self._declared_key(family, instance),
                (),
            )

        declared_targets = set(self._declared_target_ids())
        for sample_index in range(self._max_samples):
            self.ledger["samples"] = int(self.ledger["samples"]) + 1
            candidates = list(await self._sample(list(self._opened)) or ())
            self.ledger["candidates"] = int(self.ledger["candidates"]) + len(candidates)
            if not candidates:
                continue
            # THE INADMISSIBLE CANDIDATE NEVER REACHES THE ACCEPT RULE. It is
            # dropped here, before selection -- not marked and passed on, and
            # never renamed onto a catalog member. `keyed` therefore holds only
            # admissible candidates and `keyed_rows` carries each one's index
            # back into `rows`, so the emitted file still carries every
            # candidate the model returned while the rule only ever sees the
            # ones whose operator the catalog declares.
            keyed: list[tuple[str, float]] = []
            keyed_rows: list[int] = []
            rows: list[dict[str, Any]] = []
            for returned_index, candidate in enumerate(candidates):
                family = str(candidate.get("operator") or "").strip()
                targets = sorted(
                    declared_targets
                    & {str(value) for value in (candidate.get("target_ids") or ())}
                )
                seeds = tuple(
                    dict.fromkeys(
                        _normalize_seed(seed)
                        for seed in (candidate.get("query_seeds") or ())
                        if _normalize_seed(seed)
                    )
                )
                admissible = family in self._catalog
                # `""` for an inadmissible candidate, and it never enters
                # `_opened_content`, because that candidate never opens
                # anything: a sentinel in the opened set would make the second
                # inadmissible candidate of a run "already tried".
                content = (
                    self._content_key(family, targets, seeds) if admissible else ""
                )
                distance = candidate.get("distance")
                rows.append(
                    {
                        "sample_index": sample_index,
                        "returned_index": returned_index,
                        "operator": family,
                        "operator_in_catalog": admissible,
                        "target_ids": targets,
                        "query_seeds": list(seeds),
                        "content_key": content,
                        "distance": distance,
                        "min_deterministic_distance": self._deterministic_distance(
                            family, targets, seeds
                        ),
                        "label": str(candidate.get("label") or ""),
                        "rationale": str(candidate.get("rationale") or ""),
                        "distance_floor": self._floor,
                        "max_proposal_samples": self._max_samples,
                        "opened_content_keys": self.opened_content_keys(),
                        "accepted": False,
                        "rejection_class": (
                            "" if admissible else REJECT_OPERATOR_NOT_IN_CATALOG
                        ),
                    }
                )
                if not admissible:
                    # Counted, because how often the model proposes outside the
                    # catalog it was shown is a property of the switch edge and
                    # is otherwise invisible: a dropped candidate leaves no
                    # episode, no scope and no cost of its own.
                    self.ledger[REJECT_OPERATOR_NOT_IN_CATALOG] = (
                        int(self.ledger[REJECT_OPERATOR_NOT_IN_CATALOG]) + 1
                    )
                    continue
                keyed.append((content, distance))
                keyed_rows.append(len(rows) - 1)
            index = select_first_clearing(
                keyed, floor=self._floor, opened=self._opened_content
            )
            self._count_candidates(keyed)
            if index is not None:
                rows[keyed_rows[index]]["accepted"] = True
            for row in rows:
                if self._record_proposal is not None:
                    self._record_proposal(row)
            if index is None:
                continue
            self.ledger["accepted"] = int(self.ledger["accepted"]) + 1
            chosen = rows[keyed_rows[index]]
            return self._open(
                str(chosen["operator"]),
                str(chosen["content_key"]),
                tuple(chosen["query_seeds"]),
                targets=tuple(chosen["target_ids"]),
                label=str(chosen["label"]),
            )

        if int(self.ledger["candidates"]) == 0:
            # The declared catalog is drained AND the sampler returned nothing at
            # all: the honest exhaustion, and the only thing `None` spells.
            self.ledger["end"] = END_EXHAUSTED
            return None
        # The sampling budget was spent. A CUT, not exhaustion -- a later reader
        # uses the run's end to decide whether low yield was a saturated search
        # space or an instrument that stopped asking, and those license opposite
        # conclusions.
        self.ledger["end"] = BOUND_KIND_PROPOSAL_SAMPLES
        return SourceEnd(END_BOUND_HIT, BOUND_KIND_PROPOSAL_SAMPLES)

    def _count_candidates(self, keyed: Sequence[tuple[str, Any]]) -> None:
        """Tally the ADMISSIBLE candidates against the rule's two conjuncts.

        The inadmissible ones are counted where they are dropped, so the ledger
        partitions what the model returned:
        ``candidates == operator_not_in_catalog + cleared_floor + below_floor``,
        with ``already_opened`` a subset of ``cleared_floor``.
        """

        for content, distance in keyed:
            try:
                value = float(distance)
            except (TypeError, ValueError):
                value = float("-inf")
            if value >= self._floor:
                self.ledger["cleared_floor"] = int(self.ledger["cleared_floor"]) + 1
                if content in self._opened_content:
                    self.ledger["already_opened"] = (
                        int(self.ledger["already_opened"]) + 1
                    )
            else:
                self.ledger["below_floor"] = int(self.ledger["below_floor"]) + 1

    def _open(
        self,
        family: str,
        content: str,
        seeds: Sequence[str],
        targets: Sequence[str] = (),
        label: str = "",
    ) -> Episode:
        """Open one INSTANCE of a family, keyed ``family#instance``.

        The path segment is instance-scoped and the family is carried as a
        field, so every ledger grouping, arm join and curve comparison stays by
        family while the scope path stays unique -- ``open_scope`` raises on a
        re-opened path, and the deterministic planner routes the same family
        again by design.

        NOTHING MODEL-AUTHORED ENTERS THE KEY, and that holds because of where
        the catalog test sits rather than by convention: ``family`` is always a
        member of the injected catalog -- the declared path takes it from
        ``declared()`` and the sampled path only reaches here through
        :meth:`_pull`, which drops an out-of-catalog candidate before selection.
        The key is a durable join -- scope path, ``scope_key``,
        ``strategy_family``, the ``_strategy_ends`` key, and the string the
        frontier resolves by equality -- so a model-worded segment here would be
        generated prose deciding which work a strategy may pull.
        """

        self._opened_content.add(content)
        self._opened.append(
            {
                "family": family,
                "content_key": content,
                "targets": list(targets),
                "seeds": list(seeds),
                "label": label,
            }
        )
        self._opened_token_sets.append(_proposal_tokens(family, targets, seeds))
        instance = self._instances.get(family, 0)
        self._instances[family] = instance + 1
        return self._build(f"{family}#{instance}", family, list(seeds))

    def _content_key(
        self,
        family: str,
        targets: Sequence[str],
        seeds: Sequence[str],
    ) -> str:
        """The key a strategy is joined on, minted in code from declared inputs.

        Content-addressed, so two samples of the same content collapse to one
        key and the untried test compares content rather than wording -- which
        is what stops it being evadable by rewording, and is what keeps the
        model's reported distance the only model-supplied input to the accept
        rule. The model's ``label`` is recorded beside it and never joined on.

        A candidate naming an operator outside the injected catalog never
        reaches this function: :meth:`_pull` drops it before selection, records
        its row with ``accepted: false`` and
        ``rejection_class: operator_not_in_catalog``, and counts it in the
        ledger. Rejected, not renamed -- and the rejection is implemented there
        rather than promised here.
        """

        return stable_id(
            {
                "operator": family,
                "targets": sorted(str(target) for target in targets),
                "seeds": sorted(str(seed) for seed in seeds),
            }
        )

    @staticmethod
    def _declared_key(family: str, instance: int) -> str:
        """The content key a deterministically-routed family instance records.

        Instance-scoped, so re-opening a family whose queue refilled is possible
        and a proposal for the same operator with no targets and no seeds cannot
        collide with an instance the planner already ran.
        """

        return stable_id(
            {"operator": family, "declared": True, "instance": int(instance)}
        )

    def _deterministic_distance(
        self,
        family: str,
        targets: Sequence[str],
        seeds: Sequence[str],
    ) -> float:
        """A model-INDEPENDENT comparator, recorded and never branched on.

        Jaccard distance between this candidate's ``(operator, target ids,
        normalized seed tokens)`` token set and the nearest already-opened
        strategy's. Without a comparator, the later phase that sets the floor
        from data has nothing to calibrate against, and the degenerate case --
        every reported distance above the floor, so the floor never rejects
        anything -- is illegible in the trace.
        """

        tokens = _proposal_tokens(family, targets, seeds)
        best = 1.0
        for opened in self._opened_token_sets:
            union = tokens | opened
            if not union:
                continue
            best = min(best, 1.0 - len(tokens & opened) / len(union))
        return round(best, 4)

def _normalize_seed(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())

def _proposal_tokens(
    family: str,
    targets: Sequence[str],
    seeds: Sequence[str],
) -> frozenset[str]:
    tokens = set(_tokens(family))
    for target in targets:
        tokens |= _tokens(target)
    for seed in seeds:
        tokens |= _tokens(seed)
    return frozenset(tokens)

class RunBinding:
    """Methods owned by the run Episode."""

    def _strategy_episode_update(
        self,
        record: EpisodeRecord,
        *,
        strategy_key: str,
        family: str,
    ) -> EpisodeUpdate:
        prompt_context = self._strategy_learning_observation(
            strategy_key=strategy_key,
            family=family,
            record=record,
        )
        return self._episode_update(
            record,
            prompt_context=prompt_context,
            retain_trace=self.checkpoint_completed_strategy is not None,
        )

    def build_run_episode(self) -> Episode:
        self.proposer = StrategyProposer(
            declared=self.eligible_families,
            sample=self.sample_strategies,
            build=self._build_strategy_episode,
            catalog=self.strategy_catalog,
            declared_target_ids=self._declared_target_ids,
            budget=self.budget,
            health=self.health,
            termination=self.termination,
            open_cost_scope=self.open_cost_scope,
            episode_id=self.run_episode_id,
            episode_path=self.run_path,
            run_key=self.run_key,
            record_proposal=self._record_strategy_proposal,
        )
        self.controller.proposer = self.proposer
        if self._resume_proposer_state:
            self.proposer.restore_checkpoint_state(self._resume_proposer_state)
        if self._active_strategy_key:
            self.proposer.resume_with(
                self._build_strategy_episode(
                    self._active_strategy_key,
                    self._active_strategy_family,
                    self._active_strategy_seeds,
                )
            )
        return Episode(
            grain=self.run_grain,
            key=self.run_key,
            source=self.proposer,
            on_unit=self._on_strategy,
            bound=self.episode_unit_safety_cap,
            resume_units=tuple(
                ResumeUnit(
                    label=str(item["label"]),
                    controller_input=_restored_observation(item),
                )
                for item in self._completed_run_units
            ),
        )

    async def _on_strategy(
        self,
        episode: Episode,
        contribution: Any,
        record: Any,
    ) -> None:
        update = contribution.episode_update
        family = str(episode.key).split("#", 1)[0]
        try:
            if update is None:
                raise TypeError("strategy Episode returned no EpisodeUpdate")
            try:
                observation = dict(update.prompt_context or {})
                observation["volume_credit"] = (
                    _incidence_step(record).volume_credit.as_record()
                )
                self._strategy_learning_history.append(observation)
            except Exception as exc:  # noqa: BLE001 - memory is advisory
                self.record_hook_failure(
                    "strategy_learning_observation", episode.key, exc
                )
            observed = int(_incidence_step(record).unit_yield.unit_index)
            if observed != int(self._completed_strategies):
                self.record_hook_failure(
                    "strategy_unit_index",
                    episode.key,
                    ValueError(
                        f"local completed-strategy count "
                        f"{self._completed_strategies} disagrees with the "
                        f"run episode's unit index {observed}"
                    ),
                )
            strategy_episode_id = update.record_id
            strategy_path = (
                (self.run_grain.name, self.run_key),
                (self.strategy_grain.name, str(episode.key)),
            )
            self.set_active_strategy(strategy_episode_id, strategy_path)
            await self.post_strategy(
                episode.key,
                family,
                strategy_episode_id,
                run_unit_index=int(_incidence_step(record).unit_yield.unit_index),
            )
        except Exception as exc:  # noqa: BLE001 - hook must not unwind the tree
            self.record_hook_failure("on_strategy", episode.key, exc)
        finally:
            self.set_active_strategy("", ())
            self._completed_strategies += 1
        self._completed_run_units.append(
            {
                "label": str(episode.label),
                "credits": list(
                    _incidence_input(contribution.controller_input).identities
                ),
                "active": (
                    _incidence_input(contribution.controller_input).status
                    == OBSERVATION_OBSERVED
                ),
                "note": _incidence_input(contribution.controller_input).note,
                "facets": {
                    str(name): list(values)
                    for name, values in _incidence_input(
                        contribution.controller_input
                    ).channels.items()
                },
                "counts_toward_verdict": (
                    _incidence_input(contribution.controller_input).status
                    != OBSERVATION_EXCLUDED
                ),
            }
        )
        self._active_strategy_key = ""
        self._active_strategy_family = ""
        self._active_strategy_seeds = []
        self._active_search_units = []
        if self.checkpoint_completed_strategy is not None:
            try:
                if update is None:
                    raise TypeError(
                        "strategy checkpoint requires an EpisodeUpdate"
                    )
                result = self.checkpoint_completed_strategy(update, record)
                if hasattr(result, "__await__"):
                    await result
            except Exception as exc:  # noqa: BLE001 - disclosed hook failure
                self.record_hook_failure("checkpoint", episode.key, exc)

    def eligible_families(self) -> list[str]:
        """Pending families whose last instance ended by honest exhaustion."""

        pending = self.frontier.pending_by_family()
        return [
            family
            for family in pending
            if self._strategy_ends.get(family, END_EXHAUSTED) == END_EXHAUSTED
        ]

    def current_strategy_seed_queries(self) -> list[str]:
        seeds: list[str] = []
        for values in self._strategy_seed_queries.values():
            for seed in values:
                if seed not in seeds:
                    seeds.append(seed)
        return seeds

    def _declared_target_ids(self) -> AbstractSet[str]:
        ids: set[str] = set()
        for state in self.goal_states():
            catalog = state.get("target_catalog") if isinstance(state, Mapping) else None
            for key in ("fill_deficits", "unmet_count_targets", "count_targets"):
                for target in (catalog or {}).get(key) or []:
                    if isinstance(target, Mapping):
                        value = str(target.get("id") or target.get("target_id") or "")
                        if value:
                            ids.add(value)
        return ids

    def accepted_source_terms(self) -> list[str]:
        terms: list[str] = []
        for record in self._accepted_sources[-25:]:
            title = str(record.get("title") or "").strip()
            if title:
                terms.append(title)
        return terms

    def strategy_learning_history(self) -> tuple[Mapping[str, Any], ...]:
        """Completed strategy outcomes available to the next proposer.

        This is post-verdict memory. It can shape later query strings, but it
        cannot revise the completed strategy's credits, estimate, or verdict.
        """

        return tuple(dict(item) for item in self._strategy_learning_history)

    def _strategy_learning_observation(
        self,
        *,
        strategy_key: str,
        family: str,
        record: EpisodeRecord,
    ) -> dict[str, Any]:
        """Compress one completed strategy into measured search feedback."""

        def observed(curve: Mapping[str, Any]) -> int:
            band = curve.get("observed_results")
            if not isinstance(band, Mapping):
                return 0
            return int(float(band.get("value") or 0))

        def labeled_facets(
            episode_record: EpisodeRecord,
        ) -> dict[str, Any]:
            out: dict[str, Any] = {}
            for channel, value in _facet_estimates(
                _incidence_state(episode_record)
            ).items():
                out[
                    self.crediter.facet_labels.get(
                        str(channel), str(channel)
                    )
                ] = value
            return out

        search_units = {
            unit.child.scope_key: unit
            for unit in record.unit_records
            if unit.child is not None
        }
        skipped: Counter[str] = Counter()
        candidate_fates: Counter[str] = Counter()
        searches: list[dict[str, Any]] = []
        for outcome in self.last_search_outcomes:
            search_unit = search_units.get(outcome.task_id)
            search_record = search_unit.child if search_unit is not None else None
            skipped.update(outcome.skipped_by_reason)
            for candidate in outcome.candidate_source_outcomes:
                fate = str(candidate.get("fate") or "")
                if fate:
                    candidate_fates[fate] += 1
            searches.append(
                {
                    "query": outcome.query,
                    "provider_results": int(outcome.firecrawl_hits),
                    "processed_pages": int(
                        outcome.result_buffer.get("processed_results") or 0
                    ),
                    "unprocessed_pages": int(
                        outcome.result_buffer.get("unprocessed_results") or 0
                    ),
                    "sources_acquired": len(outcome.accepted_source_ids),
                    "duplicate_urls": len(set(outcome.duplicate_urls)),
                    "skipped_by_reason": dict(outcome.skipped_by_reason),
                    "error": str(outcome.error or ""),
                    "ended_by": (
                        search_record.ended_by if search_record is not None else ""
                    ),
                    "distinct_findings": (
                        observed(
                            _incidence_state(search_record).report.primary.as_record()
                        )
                        if search_record is not None
                        else 0
                    ),
                    "credit_occurrences": (
                        sum(
                            _incidence_step(unit).unit_yield.credits_observed
                            for unit in search_record.unit_records
                            if _incidence_step(unit).unit_yield.eligible
                        )
                        if search_record is not None
                        else 0
                    ),
                    "repeat_occurrences": (
                        sum(
                            len(_incidence_step(unit).unit_yield.repeat_identities)
                            for unit in search_record.unit_records
                            if _incidence_step(unit).unit_yield.eligible
                        )
                        if search_record is not None
                        else 0
                    ),
                    "incidence_estimate": (
                        _incidence_state(search_record).report.primary.as_record()
                        if search_record is not None
                        else {}
                    ),
                    "findings_by_column": (
                        labeled_facets(search_record)
                        if search_record is not None
                        else {}
                    ),
                    "volume_credit": (
                        _incidence_step(search_unit).volume_credit.as_record()
                        if search_unit is not None
                        else None
                    ),
                }
            )

        return {
            "strategy_key": strategy_key,
            "strategy_family": family,
            "seed_queries": list(
                self._strategy_seed_queries.get(strategy_key) or ()
            ),
            "ended_by": record.ended_by,
            "end_reason": record.end_reason,
            "searches_completed": int(record.units_consumed),
            "distinct_findings": observed(
                _incidence_state(record).report.primary.as_record()
            ),
            "incidence_estimate": (
                _incidence_state(record).report.primary.as_record()
            ),
            "findings_by_column": labeled_facets(record),
            "volume_credit": None,
            "searches": searches,
            "totals": {
                "provider_results": sum(item["provider_results"] for item in searches),
                "processed_pages": sum(item["processed_pages"] for item in searches),
                "unprocessed_pages": sum(item["unprocessed_pages"] for item in searches),
                "sources_acquired": sum(item["sources_acquired"] for item in searches),
                "duplicate_urls": sum(item["duplicate_urls"] for item in searches),
                "distinct_findings": observed(
                    _incidence_state(record).report.primary.as_record()
                ),
                "credit_occurrences": sum(
                    item["credit_occurrences"] for item in searches
                ),
                "repeat_occurrences": sum(
                    item["repeat_occurrences"] for item in searches
                ),
                "skipped_by_reason": dict(skipped),
                "candidate_fates": dict(candidate_fates),
            },
            "acquired_source_titles": [
                str(source.get("title") or "").strip()
                for source in self._accepted_sources
                if str(source.get("title") or "").strip()
            ],
        }

    def _record_strategy_proposal(self, row: Mapping[str, Any]) -> None:
        self._strategy_proposals.append(dict(row))
        try:
            self.answers_dir.mkdir(parents=True, exist_ok=True)
            with (self.answers_dir / "strategy_proposals.jsonl").open(
                "a", encoding="utf-8"
            ) as handle:
                handle.write(json.dumps(dict(row), default=str) + "\n")
        except OSError:  # recording never breaks the run
            pass

    def drain_strategy_sources(
        self,
        bootstrap_sources: Sequence[Mapping[str, Any]] = (),
    ) -> list[dict[str, Any]]:
        records = [
            *(dict(record) for record in bootstrap_sources),
            *self._accepted_sources,
        ]
        self._accepted_sources = []
        return records

    def drain_followup_outcomes(self) -> list[SearchOutcome]:
        outcomes = self._pending_followup_outcomes
        self._pending_followup_outcomes = []
        return outcomes

    def reset_strategy_state(self) -> list[dict[str, Any]]:
        summaries = summarize_prompt_arms(self.last_search_outcomes)
        self.harvester.record_prompt_arm_summaries(summaries)
        self.last_search_outcomes.clear()
        self._page_guess_reports = []
        return summaries

    @property
    def page_guess_reports(self) -> tuple[Mapping[str, Any], ...]:
        return tuple(self._page_guess_reports)
