# Control Layer Build Tracker

Phase and gate state for the control-layer build: prompt mutation and tuning
against a costed reward, per
`docs/TABLE_FILL_POLICY_LEARNING_WHITEPAPER.tex` Roadmap items 1, 3, 4.

> **Estimator amendment — 2026-08-28.** `docs/ACQUISITION_LOOP.md` now fixes
> the acquisition method as a frozen generic `ChannelSchema`, an
> `IncidenceEstimator` over immutable incidence samples, exact rolling
> rarefaction, and a numeric role-based `IncidenceEstimate` with bias-corrected
> incidence Chao2 as its current reachable-total estimate. The 4A--4E records
> below supply the structural history of Episode composition, nesting,
> one-unit processing, and typed end reasons. 4G-a, the 4G-b controller
> migration and legacy teardown, and evidence-first acceptance are Coded after
> their required structural reviews passed. Coded is not evidence: live
> confirmation remains pending through the foundational registered
> Firecrawl-plus-LLM experiment.
>
> **Search and graph boundary — 2026-08-31.** The foundational run is a
> Firecrawl-only experiment composition. Firecrawl and GASL remain peer search
> types in the method, each with its own composed Episode grains and
> rarefaction state. No graph operation occurs in acquisition or an Episode
> hook. Optional graph-addition proposals are completed-run downstream
> transformations that write no graph; only a separately executed,
> human-authorized merge may create a new graph revision. Historical language
> below describing graph enrichment hooks or provider→graph→GASL sequencing is
> superseded and does not authorize implementation.

## Baseline

Commit `92f8e64`. Working tree returned to it for `gasl/` and
`question_pipeline/` on 2026-08-10.

```
NO TEST SUITE — `tests/` was deleted; phases close on experiments only
```

`tools/check_runtime_invariants.py` passes at baseline.

Earlier revisions of this section carried a table of eight named baseline test
failures, pass counts, and rules for comparing them. All of it is void:
`tests/` has been deleted, so there is no suite, no failing-name gate, and no
count to compare. It is recorded here rather than silently dropped because the
stale version instructed agents to run a suite that must not exist. A phase
closes on a live run on current code — never on a suite result, and never on
measurement against recorded artifacts of an earlier tree (see `CLAUDE.md`
§Checks: no replay).

## Coded is not evidence

`Coded` means an implementation exists and `tools/check_runtime_invariants.py`
passes. It is the starting line, not the finish. Unit tests, contract tests,
fixtures, and mocks never move a row past it — a shape check passes on a
function that returns its first argument, and every defect this build exists
to prevent is invisible to one.

Rows advance through experiments, defined in
`docs/CONTROL_LAYER_EXPERIMENTS.md`: real runs, real search, real data, with
conditions manipulated and directions predicted in advance.

| State | Meaning |
| --- | --- |
| `Chartered` | Design accepted and a tracker row exists; no implementation yet. |
| `Coded` | Implementation exists; the invariant checker passes. Not evidence. |
| `Confirmed` | The phase's claim held on at least two independent routes. |
| `Diagnosed` | The claim failed, and a discriminating sub-experiment verified why. |
| `Open` | The claim failed and the cause is not yet isolated. |

`Confirmed` and `Diagnosed` are both terminal and both successful. "The routing
carries no signal, because X, verified by Y" is knowledge and is worth more than
a green suite. `Open` is not terminal — it means an investigation is unfinished,
and the run keeps working it.

Operational counts from a real run are observations, not goodness. Only the
criterion transition establishes progress, and only an independent re-derivation
from source establishes that the transition was real.

## Phase state

| Phase | Owner | State | Experiment | Notes |
| --- | --- | --- | --- | --- |
| 0 — baseline | `control-architect` | n/a | n/a | Tree at `92f8e64`; result above |
| 0 — agents | `control-architect` | n/a | n/a | In `.claude/agents/`: one orchestrator (`build-orchestrator`, added 2026-08-24), five stewards, one instrument, twelve phase agents (eleven for 0–3 plus `acquisition-kernel` for 4A), three layer agents (`question-pipeline`, `gasl-runtime`, `corpus-runner`), and `iteration-driver` |
| 0E — harness | `experiment-harness` | **Diagnosed** | §0E | Apparatus; validated on the dedup ordering |
| 0M — model tiering | `model-tiering` | **Diagnosed** | §0M | Equivalence campaign per call site; changes behavior deliberately |
| 1A — `control.py` | `control-architect` | Coded | via consumers (1C, 2C) | Vocabulary; no experiment of its own |
| 1B — cost fields | `cost-accountant` | **Confirmed** | §1B | A1–A5 and B1–B3 held; B3 failed once, verified cause, fixed. All three stewards PASS |
| 1C — decision ledger | `decision-ledger` | **Diagnosed** | §1C | Passed through `Open`; first cause was wrong | Reconstruction; resume stability |
| 1D — `criteria.py` | `criteria-projection` | **Diagnosed** | §1D | Blind verification both directions. Supplies the IDs 1C/2A/2C/3A/3B join on |
| 4G-a — incidence rarefaction output | `acquisition-kernel` | **Coded** | Foundational registered Firecrawl-plus-LLM experiment | `ChannelSchema` freezes generic base and kernel-derived union channels before observation; `IncidenceEstimator` records immutable eligible per-unit incidence sets and emits numeric role-based `IncidenceEstimate` records with exact rolling rarefaction and pairwise uncertainty plus bias-corrected incidence Chao2 reachable-total bands. Corrected post-code `modularity-steward` **PASS** and `reward-design-steward` **PASS**; invariant and deterministic implementation diagnostics pass. Coded is not evidence; live verification is pending through the foundational experiment |
| 4G-b — numerical controller migration and teardown | `acquisition-kernel` + `modularity-steward` | **Coded — `modularity-steward` and `reward-design-steward` reviews PASS; live verification pending** | Foundational registered Firecrawl-plus-LLM experiment | The live `Episode` path consumes role-based `IncidenceEstimate` values through the versioned numerical controller; the replaced decision module, exports, configuration, and second loop/driver path are retired. Required-channel verdicts remain conjoined and only the root may declare whole-run convergence. Coded is not evidence |
| 4G-c — evidence-first acceptance | `question-pipeline` | **Coded — modularity re-review PASS and evidence/reward rereview PASS; live verification pending** | Foundational registered Firecrawl-plus-LLM experiment | Exact source/version/chunk/span assertion candidates and deterministic direct acceptances persist before accepted-cell and first row-completion identities feed incidence. The obsolete raw/guess `ColumnProjection.identities()` path is deleted; candidates, raw values, provenance-only records, and unaccepted best guesses cannot mint incidence. Coded is not evidence |
| 1D-a — declared subject identity | `criteria-projection` | **Diagnosed — FINAL** (2026-08-25), closed on **zero provider spend**. Patch applied; four prior executions recorded invalid in `experiments/log/1D-a-live-declared-identity.md`; the credit blocker cleared 2026-08-24 with `LLM_API_KEY`. **The standing registration must not run: dispatched `experiment-steward` review 2026-08-25 returned UNFALSIFIABLE**, quoted verbatim in that log under the agent's name. Its decisive finding, verified independently by the orchestrator against the tree: P-L2 measures `subject_ids`/`criterion_ids` on control-decision records, and `PolicyDecision.to_dict()` (`control.py:994-1006`) never emits either key — they exist only on `TargetRef.to_metadata()` (`:347-363`), which projects onto candidate and outcome metadata, never onto a ledger record. So the quoted "0/21 non-empty" baseline is 0/21 **absent**, and P-L2's falsifier trips whatever the mechanism does. Also found: P-L3's two routes share one instrument (`criteria._subject_key_values`), so the registration has a single route — the same defect 4E-b named; the hash set does not guard the producers of any measured artifact; and `max_rounds: 1` cannot exercise the claim's between-round differentiator. A v2 re-registration under a **new id** is required before any provider call (amending hashes in place is refused by `registry.py:104-110`, since `implementation` sits inside the fingerprint) | §1D-a | Amendment to 1D, not a new phase: 1D's claim to supply join IDs fails in production. **Correction, 2026-08-25: `subject_ids`/`criterion_ids` are ABSENT from 21/21 control decisions across both runs, not empty.** Earlier revisions of this row said "empty"; the dispatched `experiment-steward` review established that the keys are never written at all, and the difference is the whole finding — "empty" describes a mechanism that ran and produced nothing, "absent" describes a field nothing mints. **Cause verified 2026-08-25** by a dispatched `criteria-projection` failure protocol (six sub-experiments, quoted in the log). There are **two causes at two grains, sharing only the field name `key_columns`**, and conflating them is what produced the standing registration. **C1:** `TargetRef.from_mapping` (`control.py:337-338`) reads `criterion_ids`/`subject_ids` off a deficit mapping, and neither mapping that reaches it declares or emits them — `FillDeficit` (`goals.py:59-79`, verified: seventeen fields, none of them these) and `pipeline._target_deficit_from_metadata`. At `cd44ebb` the producer existed and was fed from the criteria projection; the prune removed the snapshot-driven deficit builder and `goals.py` now does not import `criteria` at all (verified). The reader survived, the producer did not — so *never wired* and *pruned* are the same fact from two ends, and **1D-a's patch is orthogonal to what P-L2 measures**, on any tree since `92f8e64`. **C2, the more serious:** `goals._coerce_count_target` (`:874-878`) takes `key_columns` **verbatim from the LLM universe estimate**, and `_target_id` (`:984-991`) hashes it into the target id (both verified) — so it is the identity `_distinct_count` counts over, the join predicate in `_search_outcome_matches_target`, and the input to the stop criterion and the deficit priority. It re-rolls: eight ids for one logical family across r3+r4, with `country_year_context` alternating on nothing but `'calendar year'` vs `'calendar_year'`. **Not inert** — on attempt4b round 2, 303 rows exported with `observed_count=0` on all three count targets and `deficit_count` 5,669–14,196. The projection's own identity is **not** model-emitted and does not re-roll (ruled out by sub-experiment, corroborated by 1D's `SUPPORT_LOST=0`/`CRITERION_REMOVED=0` across all six round pairs). So the answer to "is it hallucinating" is yes, but not where this row said: `criteria.py`'s subject identity is clean, and the model sits on `goals.py`'s count-target edge. Also established, strengthening the steward's F1: `subject_ids` reaches **no artifact of any of the four runs** — not even search-outcome metadata, because `pipeline._stamp_control_action` writes four keys and deliberately does not apply `ActionCandidate.to_metadata()`. There is no surviving surface on which P-L2's clause could be measured, so v2 **drops** it rather than rewording it. **v2 registered 2026-08-25** — `experiments/log/1D-a-live-declared-identity-v2.md`, fingerprint `50fa6c9d2f522b68178abf9d2e0aa9b3`, spec `experiments/runs/1da-live/spec_v2.json`, instrument `experiments/1da-live/analyze_v2.py` written and hashed **before** the run so instrument and registration cannot disagree (4E-b's P12 failure). v1 is retained verbatim with its verdict. Seven predictions, each naming the file and JSON path that carries it. The hash set is now 24 entries covering the producers of every measured artifact — identity chain, export chain, population chain, entry point, declared inputs, continuation inputs — and because it includes `search.py`, `acquisition.py` and `goals.py`, **the guard mechanically enforces that this run precedes 4E-c's code and 1D-c's producer**. The launcher's credential defect is fixed at its one owner: `resolve_runtime_llm_config` is asked and its result exported, refusing to start on an empty key, with no fallback chain re-derived in the script. **Reconnaissance the orchestrator verified independently, and the reason P2b is a real prediction:** all three r4 `country_year_context` seed rows carry `country` populated with `year=''` beside a populated `calendar_year`, and the one `earthquake_event_impact` row carries `magnitude=None` — so all four seed rows are unbound on their declared key columns, and the visible mechanism is that traversal populated the *alias* rather than the declared column. P2b's `bound >= 1` is registered two-sided against exactly that risk rather than only in the convenient direction. **v2 returned UNCONTROLLED** by a dispatched `experiment-steward`, 2026-08-25, quoted in the v2 log — **revision cycle 2 of 3**. The finding, verified independently by the orchestrator: P2a's control removed the whole spec instead of the ingredient under test. `criteria.py:946-947` reaches the canonical fallback only when `spec.key_columns` is empty; `criteria.py:1529-1532` fills that field from `subject_key_columns` **or** `key_columns`; and the hash-guarded YAML declares `key_columns` on both tables (`:38-41`, `:180-182`). So an exported spec always carries a non-empty `key_columns`, `specs=None` compares "no spec" against "a spec" rather than isolating the patch, and P2a's falsifier could not occur — the project's own record had already measured the consequence (`1D-a-declared-subject-identity.md:169-171`: projected `subject_id`s "byte-identical patched vs unpatched"). v3 must control against the exported spec with `subject_key_columns` stripped and `key_columns` retained, register `differs == 0` as a confirmed negative, demote two analytic clauses, register P4b's expected inertness with its derivation, and register the adjudication rule that **P3 inert and P4b inert means the run does not confirm**. The steward passed and ring-fenced P1, P2b, P3(1–3), D1, the hash set, the credential fix, the teardown list and the coupling clause, found **no post-hoc shaping**, and confirmed the refusal to build a non-shared Route 2 was correct — noting the "must not share `_subject_key_values`" phrasing originated in the diagnosis, which the orchestrator had propagated into the brief as a requirement of its own. One optional item is the orchestrator's to rule on and is ruled: a `subject_key_columns` distinct from `key_columns` may be declared **only if right on design merit and argued as such**, never because it makes a prediction fire — a key column chosen for its effect on an outcome is tuning to green wearing a schema change. **v3 registered 2026-08-25** — `experiments/log/1D-a-live-declared-identity-v3.md`, fingerprint `31e0db0a74968d6a30284651cd1c834c`, instrument `analyze_v3.py`. All six required items addressed; the only two hash-set entries that moved against v2 are the analyzer and the launcher, which is mechanical proof the tree did not move between registrations. The adjudication rule is **implemented inside the hashed instrument**, so the verdict is computed by fingerprinted code rather than chosen once the numbers are in. **The optional declaration change was declined on design merit**, correctly: `country_year_context`'s grain is one country in one calendar year, so a `[country]` subject would fold Algeria 2005/2006/2007 into one subject and make `_project_field` emit one criterion carrying three values where there are three datapoints — the over-counting the contract exists to prevent, which `criteria` has no `conflicting` status to notice. **v3 declares its own ceiling in advance: route 2 is predicted to carry nothing, so the reachable best case is incomplete-on-routes, never `Confirmed`.** The orchestrator's finding on why, verified against the tree: the amendment's ingredient is semantically inert on this contract *by construction* — `two_grain_table_spec.yaml` declares `key_columns` on both tables (`:38-41`, `:180-182`) and `criteria.py:1529-1532` fills the identity field from `subject_key_columns` **or** `key_columns` — while 1D-a's defect was originally found on a contract declaring no `key_columns` at all. So the fix may be under test on a contract that never exhibited the defect. That question, and whether the open contract decision (**should `earthquake_event_impact.subject_key_columns` drop `magnitude`?** — two-sided: magnitude is a measured property with its own scale, so Mw 7.0 and Ms 7.3 become two subjects and the archetypal datapoint is uncreditable; against, `epicenter_location` is nullable so an aftershock collides into the mainshock) must be settled before any run, went to `experiment-steward` as an explicit spend gate. **v3 returned UNCONTROLLED — do not launch** (2026-08-25, quoted in the v3 log). Not for v2's reason: **all six required items were verified satisfied**, item by item, and the declined declaration was confirmed correct. The verdict attaches to the pairing of this design with *this contract*, and the steward's form of the finding is sharper than the orchestrator's. **The route-bearing observable is the one quantity the amendment provably does not move, and the project already measured it**: P2a, P3, P4a and P4b are all comparisons over `subject_id`, and `1D-a-declared-subject-identity.md:169-171` records that projected `subject_id`s are "byte-identical patched vs unpatched" — which is not contract-specific, because where no `key_columns` is declared `_identity_fields` falls to `canonical_subject_identity` and `declared_subject_identity`'s step 2 returns the same tuple (`table_specs.py:580`), and where it is declared the `or` branch returns the same tuple. **`subject_id` is inert under this amendment on every contract shape.** What the amendment actually moves is `subject_key` *readability* — same entry, `:171-174`, `0` → `163/168` non-`None` rows — and that mattered only because the attempt4b specs declared `key_columns` as `()`. This contract declares it, so `subject_key` was already readable pre-patch with the identical tuple: **this contract neutralizes the only effect the amendment has.** So incomplete-on-routes was optimistic; the reachable best case is a run in which nothing observed distinguishes the patched tree from the pre-patch one. The steward also established that `_export_seed_tables` runs at `pipeline.py:5988` *before* the round loop and `seeded_from_graph` skips the seed search, so P1's seed half and P4a's seed side are written with no search at all — the provider call would buy exactly one live number, P2b's substantive half, which is about the extraction producer (declared `year` vs alias `calendar_year`) and not about the claim. **`Diagnosed` is the honest terminal state and is already reachable without spending anything**, on a verified structural fact plus a prior independent measurement from the other direction. Two instrument observations were recorded and explicitly **not** to be patched, since both err away from the claim and neither can manufacture a confirmation.

**A separate finding from the same review, verified independently by the orchestrator, that would have invalidated a paid run.** `4C-acquisition-surface-v2.md:10` names `1da-live/launch.sh` as 4C's run, but that launcher guards **only** the 1D-a spec — it references neither `spec_4c.json` nor `spec_4d.json`, so nothing would have checked them. Against the tree, **four of `spec_4c.json`'s seven hashes have drifted**: `question_pipeline/pipeline.py`, `rarefaction/accumulator.py`, `rarefaction/scopes.py`, `rarefaction/driver.py` (`rarefaction/stop_rule.py` is byte-identical, as 4E-a claimed). `rarefaction/episode.py` is in no 4C hash set at all, and `spec_4c.json` still asserts disjoint hash sets. 4E-a and 4E-b legitimately changed those files, so **4C v2 is void against the current tree** and any launch today would produce a 4C result its own registration does not cover. 4C v3 — already chartered under §4E-c — must land before 4C runs.

**The contract question is therefore blocking and was dispatched blinded.** `reward-design-steward` holds it, because identity fields are excluded from 1D's criteria projection (`criteria.py:1024-1031`) *and* from 4C's credit basis (`acquisition.py:105-106`) simultaneously, so the ruling decides what can ever be counted as a datapoint. Per the steward's procedural guard, the brief withholds the effect on P2a entirely and asks for a ruling on grain grounds alone: **a contract decided by its effect on a prediction is that prediction tuned through a schema change.** If the ruling drops `magnitude`, P2a becomes a live two-sided contrast as a *consequence*, never a motive, and the experiment re-registers as v4 on the moved hash set. If it keeps `magnitude`, **nothing is spent** and 1D-a closes `Diagnosed` on the finding above. **Ruled 2026-08-25: DROP `magnitude`**, quoted in the v3 log. The blinding held — the ruling closes by recording that no effect on any registered experiment's predictions was sought, consulted, or weighed. Keeping it is labelled **VOLUME-SCORED**, the inflated quantity being *subject count inflated by measurement disagreement*, on a test that generalizes past this table: **an identifier is something every source of one subject agrees on; a measurement is precisely a thing they can disagree about.** The contract is its own proof — `magnitude` needs the companion `magnitude_scale` to be interpreted, and that companion is itself `nullable: true` with "Do not infer a scale that was not given" (`:64-67`), so the identity would contain a number whose own declared basis may be absent; the file already reasons this way one column over for `economic_damage_usd` (`:103-106`), and nobody would key on that. The aftershock counter-argument is right about the gap and wrong about the fix: magnitude does not close the collision (two aftershocks at the same rounded magnitude still collide) and buys partial coverage with a guaranteed false split. The decisive asymmetry is **which failure announces itself** — a false split is invisible (two subjects, each internally consistent, each fully supported, every count inflated), while a false merge is legible with no new machinery, since `criteria.py:105-111` records multiple distinct values for one criterion in `CriterionState.values`. Under no-silent-failures, take the identity whose failure is readable. **Verified by the orchestrator before applying: completeness is unaffected** — `required_columns()` (`table_specs.py:99-111`) is `key_columns` plus every non-nullable column and `magnitude` is `nullable: false` (`:58`), so it still returns through the second branch. Consequential: `epicenter_location` must not change nullability and must not enter the identity (free text that `_normalize_value` only casefolds); and **`event_date` is now load-bearing at variable declared granularity** (`:47`), so `2023-02-06` and `2023-02-06T01:17:35Z` are two subjects for one event — pre-existing, not created by this ruling, recorded as an open contract decision and deliberately not folded in. **Orchestrator sequencing decision:** the steward advised re-registering 4C v3 before launching, but 4C v3 is chartered to follow 4E-c and 4E-c does not exist — so this run is **decoupled to serve 1D-a v4 only**, 4C v2 is void and does not ride it, and 4C v3 follows 4E-c as already chartered. v4 in progress: contract change applied, P2a re-registered as a live two-sided contrast **as a consequence of a blinded grain ruling and never as its motive** — the sentence that is the audit trail, and the reason the earlier shortcut of declaring `subject_key_columns: [country]` was refused. **v4 was never written, and that is the finding.** The contract change was applied and then *measured*, and P2a is still analytic: the ruling drops `magnitude` from **both** lists — correctly, since `acquisition.py:105-106` unions them — which restores `subject_key_columns == key_columns == (event_date, epicenter_country)`. The orchestrator verified this directly through the loader on the edited contract: identity **with** `subject_key_columns` and **without** it are both `('event_date','epicenter_country')`, so `differs == 0` analytically and `experiment-steward`'s F1 survives the ruling verbatim. Three substitutions were available and all correctly declined — declaring the key while keeping `magnitude` (forbidden by the ruling, and tuning); `country_year_context: [country]` (already declined on merit); and re-pointing the route at what the change *did* move, which are contract effects holding identically on the pre-patch tree and so "a different experiment wearing 1D-a's id". **The verified cause, on three independent legs:** (1) structurally, `subject_id` is inert under this amendment on *every* contract shape, since both the declared and the fallback path return the same tuple; (2) by prior independent measurement from the other direction, `1D-a-declared-subject-identity.md:169-171` recorded projected `subject_id`s "byte-identical patched vs unpatched"; (3) by direct measurement on the post-ruling contract, above. The amendment's only real effect is `subject_key` **readability** (`0` → `163/168` non-`None`), observable solely on a contract declaring **no** `key_columns` — which is a new registration with a different declared input, not an amendment to this one. **What 1D-a was actually chasing turned out to be two other defects**, both now carrying their own rows: the absent producer for the plural join ids (1D-c) and the model-emitted count-target identity (1D-b). **The permanent change this investigation justified, and which stays:** the `earthquake_event_impact` contract fix, ruled on grain grounds by a blinded steward and independent of any experiment — `magnitude` now enters both `criteria.datapoint_fields` and `acquisition.declared_credit_columns`, the r4 seed row's `subject_key` binds where it was `None`, and Mw 7.0 vs Ms 7.3 for one event collapses from two subjects to one. `table_spec_yaml_sha256` moves accordingly, which hard-fails the guards of all three closed 1da-live registrations — correct, since none of them may run. Teardown executed: the three analyzers deleted, every log retained Cause is upstream — table specs declare no `key_columns` (verified: absent from all three attempt4b specs, `deliverable: false`), so `criteria.py:940-941` falls through and the only surviving identity is model-emitted planner prose that re-rolls each round. Fix is a declared identity in `table_specs.py`; no new identity type, module, or mutable state. **Depends on `question-pipeline`** as sole writer of `table_specs.py`. Blocks per-cell operation of any yield posterior |
| 1D-b — model-authored count-target identity | `question-pipeline` | **Chartered** 2026-08-25, split out of 1D-a's diagnosis so a `goals.py` defect is not fixed inside an amendment about `criteria.py` — the conflation of two same-named fields is what produced an unfalsifiable registration in the first place | needs its own registration | A model sits on a what-counts decision edge, with realized numeric harm. `goals._coerce_count_target` (`:874-878`) takes `key_columns` verbatim from the LLM universe estimate; `_target_id` (`:984-991`) hashes it into the target identity; `_attach_observed_count`/`_distinct_count` count distinct rows over it; `pipeline._search_outcome_matches_target` joins on it; the result drives the "all estimated count targets covered" stop criterion and the deficit priority. `docs/ACQUISITION_LOOP.md` §"Decisions are numerical" makes "which columns and rows count toward a target" required-numerical and names a model there as the violation. Evidence of harm, from the runs' own artifacts: attempt4b round 2 exported 303 rows and recorded `observed_count=0` on all three count targets with `deficit_count` 5,669–14,196, because `_distinct_count` resolves names by exact equality and a model-authored `'event date/time'` matches no exported column. **Latent on the two-grain contract** (every target sits in `unestimated_count_targets`, so `_attach_observed_count` never runs) and realized on attempt3/attempt4b — which is where 1D-a's baseline came from. Proposed fix, not applied: join on the declared `subject_key_columns`, resolved in code; keep the model's list as a recorded label and never hash it into `_target_id` or pass it to `_distinct_count` — the same shape `prompt-mutation-steward` required of 4E-c's proposer key, one grain over. Required verdicts: `modularity-steward`, `reward-design-steward` (it feeds a deficit priority), `experiment-steward` |
| 1D-c — restore the deficit→criterion producer | `question-pipeline` | **Chartered** 2026-08-25 on a dispatched `modularity-steward` boundary ruling (quoted in `experiments/log/1D-a-live-declared-identity.md`): **option (a), restore the producer, and `goals.py` may import `criteria`** — but only with the snapshot arriving as a **parameter**, never computed inside `goals.py`. Option (b), deleting the vestigial reader, was **rejected**: it decouples nothing (the read already returns `()`), and it defers the join to 2C and 3A which are reached through `pipeline.py`, so its end state *is* the MISPLACED outcome arrived at by omission | needs its own registration | Boundary reasoning, verified by the orchestrator: the edge is strictly downward and closes no cycle — `criteria.py:124-125` imports only `.control` and `.provenance`, `control.py` imports nothing from the package, and `criteria.py` never imports `goals`. The tree already contains this arrangement deliberately and says why, at `provenance.py:28-32`: that module lives where it does because "what `criteria` refuses to treat as a datapoint and what `goals` refuses to treat as a fillable column have to be the same set, or the run will search for columns it will never credit." Subject identity is the same kind of fact. Six binding conditions: **C-a1** no `project_rows` inside `goals.py` (the tree already computes a fourth projection at `pipeline.py:3126-3131` for no purpose but to detect that two derivations disagree, reporting `chain_divergence_reason` — and `criteria.py:904-907` names the precedent, "a second spelling of an identity rule fails silently"); **C-a2** ids read off the supplied snapshot, never recomputed, and `FillDeficit.key_columns` never used as identity — that is 1D-b's model-emitted field and conflating the two is the original defect; **C-a3** `criteria_snapshot_id` is the id of the snapshot passed in; **C-a4** written cardinality per deficit type, never the whole unresolved set (448,869 criteria on this corpus); **C-a5** the new fields must not enter `_fill_deficit_id` (`goals.py:1803-1819`) — snapshot ids are content-addressed and move every round, so folding one in renumbers every deficit and destroys `search_memory`'s attempt history, the identical harm 1D-b documents one grain over; **C-a6** no reverse import and no widening of the baseline `evidence_gap` chain. The vestigial reader **stays** — under (a) it stops being vestigial when the producer lands, and `from_mapping` is a coercion boundary by design, so the missing-value announcement belongs at the first consumer that joins, on the `_credited_criterion_ids` pattern (`pipeline.py:4511-4520`). `control.py` needs **no change and none is licensed here**; putting the ids onto a ledger record is a separate `PolicyDecision` surface dispatch. **Does not gate 1D-a**: even with the producer landed, the ids still reach no artifact, so 1D-a v2 measures declared identity on the surfaces that already carry it |
| 2A — `path_features.py` | `path-features` | **Diagnosed** | §2A/2B | Score predicts `evidence_gap` rate |
| 2B — path gate | `path-gate` | **Diagnosed** | §2A/2B | M2/S1 failed as registered; verified cause is `criteria_projection_v1`'s support definition, not the gate. All three stewards PASS |
| 2C — path memory | `path-memory` | **Diagnosed** | §2C | N1 failed, verified cause (transcription); G2 magnitude failed, not fully diagnosed (reported honestly). All three stewards PASS |
| 3A — costed reward | `reward-engineer` | **Confirmed** | §3A | P1 held (yield ≠ volume); P2's round-set falsified, traced to real delayed-credit mechanism. `reward.score` untested live — no run yet carries `cost_records.jsonl`. All three stewards PASS |
| 3B — arm tuning | `arm-tuner` | **Diagnosed** | §3B | Pseudo-gradient never wired end to end: three severed links found across three review cycles. Headline A/B/C unmeasurable. All four stewards PASS |
| 4A — `rarefaction/` kernel | `acquisition-kernel` | **Confirmed** (kernel arithmetic, via §4B consumer runs: emitted data and offline recomputation agreed on every walk; the shared-across-surfaces claim binds fully at 4C). Dispatched `modularity-steward` review 2026-08-24: **PASS**, quoted in `experiments/log/4A-kernel.md` — eight findings, none blocking; F7 (driver pulls a unit before testing the bound, contrary to the charter) and F6-edge-2 (`ended_by` cannot carry a source-reported reason) carried to 4E-a, F2 (dead `PERMITTED_LOWER_LAYERS` in the checker) and F8 (prototype `experiments/stop-rule/stop_rule.py` teardown due) to the 4E-a code dispatch, F3 (`goals.py` round-grain first-seen accumulation) to the `pipeline.py` recomposition | §4A | New top-level pure package: accumulator (f1/f2/Chao1 with degeneracy disclosure), stop rule (port of `experiments/stop-rule/stop_rule.py`), nested scopes, and the episode **driver** — the loop as a first-class function. Charter: `docs/ACQUISITION_LOOP.md`. Amends `tools/check_runtime_invariants.py` to admit `rarefaction` as a permitted lower layer |
| 4B — walk yield binding | `gasl-runtime` | **Diagnosed — FINAL** (2026-08-25). P4B-1/4/5 held; P4B-2 failed as registered, cause verified by D4B-1 (sparse tree-like condition, not mechanism — the verdict fired at the exact arithmetic point on a dense real graph and the two-sided control held; one D4B-1b window miss diagnosed to registration arithmetic, route-2 confirmed). **P4B-3 re-scored** on `experiment-steward`'s instruction: held on its registered falsifier only — one clause of its prediction text ("ends `bound_hit`") was contradicted by the emitted record, which shows `ended_by="exhausted"` under `bound_kind="walk_node_budget"`, unreported at the time; that is the rule-6 defect 4E-b fixes. All three owed reviews are now **dispatched and recorded verbatim** in the log, each superseding the fork-orchestrator's self-issued block of the same name: `experiment-steward` **PASS** (with the two log corrections now applied), `modularity-steward` **PASS** (naming three boundary defects the self-review missed, all fixed by 4E-b), `gasl-design-steward` **PASS** (naming four, all but the fan-out cap conflation fixed by 4E-b). Also recorded: route 2 was narrower than the log claimed — the posterior arithmetic is single-route, and the curve half of P4B-1 had no second route at all, because the label-summary export made f1/f2/Chao1 unrecomputable | §4B | GASL walks run through the driver: unit = one seed expansion, credits = node encounters made expanding it; yield numbers emitted in result data after every seed; walk quits on verdict, budget caps demoted to disclosed safety bounds. The depth steps inside a seed still run to their caps (hop-level grain; 4E-b decides). `gasl-design-steward` reviews |
| 4C — acquisition surface inversion | `question-pipeline` | Coded (registered §4C; **re-registers as v3 after 4E-c** — as coded, the page loop is inline in the harvester and `AcquisitionController` is consulted between pages with a hand-kept fan-up, which the composition rules in the charter name as NOT-BOUND; the live run follows the re-binding by dependency; reward episode-ledger consumption stays deferred behind reward-design-steward) | §4C | The teardown: per-page fetch → extract inline → credit → observe replaces search-all → ingest-all → credit-at-round-end. There is no relevance gate or relevance-model call. As coded, `question_pipeline/acquisition.py` holds the crediter and a controller the harvester consults; it does not run the driver (4E-c makes it a composition). No graph operation occurs in acquisition or an Episode hook; an optional graph-addition proposal is a completed-run downstream transformation and writes no graph. Per-search verdict cuts result-list consumption (disclosed skip reason); reward consumes episode ledgers later. Depends on 1D/1D-a declared identity for crediting |
| 4D — strategy grain | `question-pipeline` | Coded, **to be redesigned in 4E-c and re-registered (v3)**: as registered it demotes a stopped strategy's tasks within a round with an all-stopped override, which interleaves searches across strategies and clashes with the composition in `docs/ACQUISITION_LOOP.md` §"The template" — a strategy is an episode of searches that ends by its own verdict, and the `run` grain's source proposes the next. The full multi-round run follows 4C v3 | §4D | Unit = completed search Episode; the strategy verdict ends the episode, recorded as a `PolicyDecision`; the `run` source (proposer) is the switch edge. `prompt-mutation-steward` reviews that source |
| 4E — episode composition | `acquisition-kernel` (4E-a), `gasl-runtime` (4E-b), `question-pipeline` (4E-c), in that order | **4E-a: Coded, design and code steward-passed, compat-confirmed on the `drive_episode` path; not `Confirmed` — it has no experiment of its own and closes through 4E-b/4E-c (§4E). 4E-b: Confirmed** (2026-08-25) — eleven of eleven falsifiable predictions held, rule 6 demonstrated fixed by a 41-of-42-field identity with one field moved, rules 6 and 7 both closed. **4E-c: Chartered**, next. See the 4E-b and 4E-a sections below | §4E | The refactor the recurring pattern demands: `rarefaction/episode.py` — `Grain` (unit, credit, policy, declared once) and `Episode` with swappable parts (`source` with a view-reading protocol, `extract`, `credit`, hooks, `bound`) whose source may yield child episodes, so nesting, fan-up, and the bound-leak rule are properties of the class. Charter: `docs/ACQUISITION_LOOP.md` §"The template" — the only place the rules live. 4E-a lands the class on `drive_episode`, design to `modularity-steward` before code; 4E-b re-states the walk as a composition, fixes the two 4B defects the charter names (misreported `ended_by`, extractor/hook shared closure), registers whether a depth-step verdict binds, and predicts identical firing points on the D4B-1a graph; 4E-c replaces the harvester's inline page loop and the controller's hand fan-up with the composition run ⊃ strategy ⊃ search ⊃ page, implements the two credit kinds (per-column non-trivial values; completed rows) and the proposer source, after which 4C and 4D re-register (v3) and run in full |

### Takeover build, 2026-08-31 — rounds removal through the foundational live run

The operator handoff of 2026-08-31 (recorded in full in `docs/NEXT_STEP.md`,
which is the standing instruction set for this build and wins beside the
charter where older docs disagree) defines the serial phases below. Both
operator vocabulary rulings bind every phase: generic Episode/unit/source
vocabulary in core components; search/strategy/paper verbiage reserved for
the specific layer bindings (`docs/NEXT_STEP.md` §"Vocabulary rules").

| Phase | Owner | State | Experiment | Notes |
| --- | --- | --- | --- | --- |
| P1 — finish removing rounds | `question-pipeline` | **Confirmed — PASS** (2026-08-31). Independent dispatched `phase1_modularity_steward`: “No global round identity | PASS | Episode IDs/paths and parent-local `unit_index` replaced durable round identity.” Scope cleanup restored accidental remediation outside round removal; invariant checker passed before closure | Structural gate: no global round identity | Round identity, offsets, quotas, filenames, continuation inference, and cost/prompt/reward attribution were removed structurally. `max_source_units` is the one operator-declared pulled-unit bound, default unbounded; a cut is `bound_hit`, never convergence. Direct ownership now joins through Episode identity/path. The same review's completion-probe topology, graph-hook mutation, broader binding ownership, and operational event-identity observations are preserved in `experiments/log/round-removal-phase1.md` but deferred as non-blocking to their later owners (Phase R, P2, and P4). No later-phase architecture was closed here |
| P-R — binding-file consolidation and head diagrams | `gasl-runtime` (walk binding), `question-pipeline` (provider consolidation) | **Confirmed — PASS** (2026-08-31). Independent dispatched modularity reviews passed both serial moves: GASL walk binding **PASS**; provider binding consolidation **PASS** | Structural modularity gates; no paid/live run | `gasl/walk_binding.py` now owns the query ⊃ walk ⊃ seed binding and diagram; `graph_nav.py` delegates GRAPHWALK while retaining unrelated handlers. `question_pipeline/acquisition.py` now owns the full run ⊃ strategy ⊃ search ⊃ page binding and diagram behind injected collaborators; `pipeline.py` retains one `acquisition.run(...)` call and downstream post-strategy transformations. File-boundary moves only, with compile/import/invariant/diff checks passing. P1 and P-R close in one combined commit because their independently reviewed hunks are interleaved in `acquisition.py` and `pipeline.py`; the commit is explicitly a combined closure, not Phase-R-only. No Phase 2 event work, checkpointing, graph-semantics redesign, best guess, memory, or live-experiment work is included |
| P2 — event rabbit-hole check | `question-pipeline` | Chartered; after P-R under the serial rule | Structural | The provider batch request belongs to the search Episode; results process one-by-one as units. No pre-unit source-pull Event type, no causal-parent event graph; `EventContext` already removed — verify stale exports/imports gone. `EventRef`/`UnitContext` survive only where they connect accepted evidence to the unit that produced it |
| P3 — continuation checkpoint | `question-pipeline` | Chartered | Structural + gate reviews | One canonical `checkpoint.json` per run folder, atomic at completed-Episode boundaries; `--continue <folder-or-file>` replaces the seed/continuation flag family; no directory scanning, no numbered-artifact inference, no resuming inside an Episode. `question_pipeline/checkpoint.py` audited down to the simple mutable boundary and wired. Generic state-role names (frontier/memory/evidence) |
| P4 — peer search methods | team | Chartered | Structural | Firecrawl and GASL are peer search types, each composed from `Episode` with its own rarefaction history; GASL is not a post-Firecrawl stage; table compilation is not an Episode child. Graph additions are proposed post-run as a reviewable table, never auto-merged; a copy-paste merge CLI is rendered as inert text |
| P5 — table input-state snapshot | `question-pipeline` | Chartered | Structural | Every compiled table records the exact input state (evidence registry/version, accepted source state, table-spec identity/version, optional immutable graph revision, run lineage); published time supports an explicit unknown |
| P-Live — foundational Firecrawl-plus-LLM experiment | orchestrator + `question-pipeline` | Chartered; last, after every structural gate | Registered before any paid call including a credential probe; `experiment-steward` approval on design and result | The real earthquake table-fill on live Firecrawl and real extraction, one process to its own numerical or typed end; the eight registered checks and credential/transport procedure in `docs/NEXT_STEP.md` §"First foundational live experiment" |

### 4E-c — the provider surface as a composition (open; orchestrator checkpoint)

**State: Chartered, design in flight.** Written by the orchestrator on taking
over from a predecessor killed mid-turn, so that a later reader — or a later
restart of this same role — can recover the state without re-deriving it.

Verified on disk at handover, 2026-08-25: HEAD `9624b33`;
`tools/check_runtime_invariants.py` passes; no `run_question_pipeline`,
`run_composition`, or `run_compat` process is live; `experiments/log/` carries
no 4E-c file, so the design does not yet exist in the tree.

Two dispatches are outstanding and neither has reported:

1. ~~A `question-pipeline` agent specifying the 4E-c design.~~ **Delivered**:
   `experiments/log/4E-c-provider-composition.md`, 1,173 lines, design only,
   no code written (verified against `git status`). The orchestrator verified
   its load-bearing citations against the tree rather than accepting them —
   `scopes.py:140-141`, `stop_rule.py:36-39`, eleven `acquisition.py` line
   citations and `search.py:444-471` all land where claimed, and the tree's
   own `searches_to_stop` puts the all-barren crossing at **10** for all
   three proposed policies with `min_observations` not moving it, so §2.1 is
   correct. Three counting errors to correct in the note, none changing a
   decision: `acquisition._MISSING` has 8 entries (note says 11),
   `criteria._MISSING_STRINGS` has 17 (note says 16), and the sets differ by
   **nine** tokens rather than the eight §5.3 names — it omits
   `"not specified"`. The substantive finding there is verified true and
   slightly larger than stated: under 4C as coded a page saying a value is
   "not reported" mints an acquisition credit, counting absence as yield at
   the grain that decides whether to keep fetching.

#### Design review, cycle 1 — closed, three non-PASS; revision dispatched 2026-08-25

All three required stewards returned non-PASS, so the design does not become
code. A single revision was dispatched to `question-pipeline` carrying the
union of the three verdicts (8 required changes, 23 conditions, F1–F9), all
four operator instructions, the R7 chunk-grain ruling, the reachability table
and its two-sided constraint, the four-way missing-token consolidation, the
three counting corrections, and the two defects found during 1D-a's close —
rather than three serial rejections, so the phase spends one of its three
cycles instead of all of them. **This is cycle 1 of 3.**

**Revision 2 delivered 2026-08-25** — `experiments/log/4E-c-provider-composition.md`
line 2688 to end, appended after all three verdicts, which are preserved
verbatim where they were. No code written. Its substantive moves: §10's
"no model call sits on any row" claim **struck** rather than defended, with a
12-row fate table fixing `(active, counts_toward_verdict)` per page fate so
that judged-not-relevant becomes `active=True, credits=()` — the page still
enters the stop history, so **the model no longer shrinks the denominator**,
and the remaining numerator effect is named and recomputable without it; R1
and the `evidence_gap` finding treated as **one defect at two places**, the
producer's judgement reaching the stop rule at numerator and denominator;
`declared_credit_columns` routed through a `criteria`-owned predicate rather
than a name exclusion, covering the class (orchestrator-verified direction:
24 → 22, the two `evidence_gap` entries the only drops, no legitimate column
lost); the exclusion **tested** by a per-page counterfactual credit ledger and
an offline curve recomputation with the identities re-admitted, two-sided so
an inert exclusion reports itself; hash sets built by glob over
`question_pipeline/` and `rarefaction/` with a launcher guarding every spec
riding the run. **One item reported unbuildable rather than substituted**: the
`run` grain's yield verdict cannot be observed live inside this build's
provider budget — the crossing is 10 completed strategies, on the order of a
thousand fetch-judge-extract cycles — so its accounting is built and verified
offline while its verdict is **registered inert with the arithmetic that makes
it inert**, refusing to lower `RUN_GRAIN.policy` to reach it. Reachability for
the other pairs is bought with observations, not thresholds: Condition A
(`papers_per_query=12`, 48 pages) reaches page ⊂ search and Condition B (132
pages) reaches search ⊂ strategy, forcing one disclosed config change —
`SourceBudget` charges every **pulled** page, since a rejected page still
costs a fetch and a judge call and the denominator R1 made model-independent
would otherwise be unbounded. Corrections it made to the reviews: the four
missing-token sets are 17/11/9/8 and the single owner must hold the **union
(18)** because `goals` uniquely carries `"not specified in current evidence"`
— which moves `criteria`'s own semantics and is put to both stewards, the
ownership half to `modularity-steward` and the datapoint half to
`reward-design-steward`. **Cycle-2 review dispatched to all three stewards.**

**Cycle-2 verdicts, two of three in.**

`prompt-mutation-steward` — **PASS with five binding conditions**; all five
revision-1 findings closed, no TEXT-INFERRED/COUNT-SCORED/SURFACE-BOUND
finding surviving. It ruled the switch edge **honest** despite the run
verdict's registered inertness: the grain's unit, credit and threshold are all
named and measurable, so its charter's measurement-gap clause is not
triggered — the sample is simply too small, and nothing unmeasurable was
papered over with a model. It confirmed refusing to lower the policy is right,
since "a threshold fitted to make its own mechanism visible stops being a
decision", and found the dishonest form — a record where a spent budget is
indistinguishable from a verdict — foreclosed four ways. **Its condition 1 is
the substantive catch, verified by the orchestrator**: §11.3 hands
`query_seeds` to `strategy.target_deficit_queries`, whose signature
(`strategy.py:135-144`) has **no channel for them** — and since §11.2 hashes
seeds into the content key, unfixed this makes the proposer's novelty
fictional, two proposals differing only in seeds instantiating byte-identical
arms. Its F3 fix is confirmed buildable (`metadata` is a dataclass field at
`search.py:81`, bound before `__post_init__` at `:83`), closing both the
persistent-mode frontier drop and the path collision, and it checked the one
route the design did not name — batch mode, foreclosed by
`pipeline.py:716-719`. **Condition 5 corrects its own revision-1 wording** as
too broad for this tree.

`modularity-steward` — **PASS with conditions C24–C40**; all eight required
changes R1–R8 closed and all twenty-three revision-1 conditions dispositioned,
with no LLM-DECIDED, NOT-BOUND, DUPLICATED-OWNER or MISPLACED finding. It
**confirmed the orchestrator's R1 reading**: the defect was never that a model
judges relevance (the charter lists it as string work and puts fetch-judge-
extract inside `extract`), but that the judge's boolean was routed onto
`CreditResult.active`, whose declared meaning is "no crediting judgement was
possible" — corrupting the disclosure *and* shrinking the denominator. It
verified the fix buildable rather than assuming: `observe` raises only on
`counted and not active`, and `_observe_facets` handles the active credit-less
unit on both shapes, so **no kernel change is needed**. It ruled the
`evidence_gap` owner correct — `criteria` already exports `datapoint_fields`
with the identical no-second-opinion argument, and `is_provenance_name` sits
*inside* `_is_value_field`, so this is one predicate replacing two rather than
two stacked. It ruled the missing-token union onto **`criteria` at 18**, since
consolidating onto 17 would silently delete a token a consumer relies on — a
behaviour change hidden inside a cleanup. **C33 is the confound worth
naming**: the design registered one direction where the change has three —
`goals` gains 9 tokens, `best_guess` 7, `acquisition` 10, `criteria` 1 — and
`goals` decides which columns are worth searching for, so its nine tokens mean
more deficits and more searches *in the very run that measures the
composition*. **C26**: the decision-edge table is still incomplete — three
edges live in the design and not in it (fatal/non-fatal provider-error
classification, whether the page best-guess call runs, `route_next_family`),
none carrying a model. **C25**: `RunTermination.source_end()` returns `None`
for both "no termination" and `FRONTIER_EXHAUSTED`, so that reason could never
end the run. §2.3 ruled **in scope**: `assert_registered_all` belongs in
`experiments/registry.py`, the inline-per-launcher fallback being N copies of
one rule.

`reward-design-steward` — **MODEL-SCORED and UNTRACEABLE, non-PASS.** Both
revision-1 blocking findings and all eight of its revision-1 conditions are
**closed**: F1 by §12.1's ten-row enumeration of every provider and model call
and its scope, a genuinely new `ObservationKind.STRATEGY_PROPOSAL`, and a
per-strategy orphan delta — going further than asked by moving the relevance
judge *into* the SOURCE scope, where `_record_run_residual_cost`'s own
docstring admits it ran outside all four; F2 by `_round_label(
run_view.units_consumed)` minted once at strategy-open, both halves verified
live; F3–F10 by §12.4's non-joinability sentence naming `source_id` as the one
join and forbidding the text join by name.

**What blocks is one thing revision 2 introduces.** §13 row 12 concedes it in
the design's own words — "**MODEL:** the judge sets fate 7 vs. 12, i.e.
whether the page is extracted, i.e. the numerator" — and `accepted` is not a
rule over anything measured: `progress_judge.py:81-83` returns
`self.decision == "accept"` over the model-emitted closed label set at `:31`.
§3.2 defends this on the premise that the influence "cannot be removed by any
allocation short of extracting every page". **That premise is false, and the
orchestrator verified the correction directly:** the same `judge_progress`
call already returns `fruitfulness_score`, `novelty_score` and
`specificity_score` as floats (`progress_judge.py:62-64`), so a written
threshold over those — label recorded, never branched on — is available at no
extra provider call, in exactly the shape revision 2 already uses one edge
over for the proposer's distance floor. 4E-c is also the phase that wires the
model onto the accumulator at all: under 4C a rejected page never reached it.

**Orchestrator adjudication of a declared steward divergence.**
`reward-design-steward` noted that `modularity-steward`'s concurrent PASS
closed R1 on the premise above, and that neither review considered the
threshold form. Per §"Run protocol" any single non-PASS is a non-PASS, so the
phase does not proceed regardless. On the merits the orchestrator rules **for
`reward-design-steward`**: the charter lists judging relevance as string work
— which is why the denominator ruling is right — but the same section says
"the number is data for a rule with a written threshold; **the model does not
also decide what the number means for the loop**", and a boolean accept/reject
label consumed as a branch is the model deciding what its own judgment means.
The disagreement is not whether a model may judge relevance; it is whether its
*label* may be what a stop rule's numerator branches on. `modularity-steward`
has been given the corrected fact and asked for its amended position on R1 and
on C27 — **routing a verified fact its ruling depended on, not brokering a
verdict between stewards.**

Its other blocking finding, **R2-F2**: the missing-token union is a projection
**version** change and no bump is proposed, and §10's "strictly fewer
supported, never more" is wrong — `_missing` has five call sites and two are
identity (`criteria.py:861`, `:965`), so a key column carrying the token flips
`bound`, moves the subject id, and re-mints every criterion of that subject as
`SUPPORT_GAINED`, the one creditable kind, unsuppressed because its id moved.
Both tables declare prose subject keys and `pipeline.py:3468` is the tree's
own writer of that token. Requires `criteria_projection_v5` with a written
rationale, the direction claim corrected, and P4E-c-6 widened. **RC3**: the
consolidation is **five-way**, not four — `pipeline.py:3453-3471` holds a
fifth `_is_missing` in the module that writes the tables. **RC4**:
`_orphan_cost_delta()` returns the ORPHAN meter's `round_index` of 0 and
`residual.update({...})` does not overwrite it, so the per-strategy residual
still lands in round 0 — F1's defect surviving inside its own fix. It ruled
§1's observable **genuinely tests** rather than asserts (24 → 22 verified,
only the two `evidence_gap` entries dropped; a crediter returning its first
argument produces two identical curves and the observable reports inertness,
which is correct for such a crediter), and best-guess-in-`extract` **sound and
not inflationary**, with §9.3's refusal to let a guess supply a subject key as
the load-bearing guard — one gap, **RC8**: a row credit completed 13/14 by
guess is not "whole answers" and nothing records the split.

**`modularity-steward` amended its own revision-2 PASS to LLM-DECIDED** in a
dated follow-up, after being given the corrected premise. It is recorded as a
follow-up to its re-review, not a replacement of it, and it **governs**. Two
grounds, the second independent of the first: (A) necessity is gone and the
third allocation is cheaper than reported — the three scores are *already at
the consumer*, `strategy.py:472` mapping `fruitfulness_score` onto
`confidence` and `pipeline.py:1554-1556` carrying all three onto
`SourceRelevanceDecision.metadata`; (B) its own revision-2 closure said the
judge is "handed one page and asked a question about that page", and having
read the call whole it withdrew that as factually wrong — the payload
deliberately carries the run's declared stop criteria, and
`pipeline.py:1588-1594` says so in its own comment, so the prompt asks for
coverage yield against the deliverables and returns a decision word.

**Two traps in the obvious fix, both verified by the orchestrator, and the
reason revision 3's brief leads with them.** *Only one of the three scores
qualifies*: `progress_judge.py:383-388` defines `fruitfulness_score` as
likelihood of improving the declared deliverables (a progress estimate over
run state) and `novelty_score` relative to CURRENT TASK STATE JSON (precisely
what the accumulator computes by dedupe, asked of a model where it is already
measured); **`specificity_score` alone is a property of the page against the
declared contract**, and a floor over either of the others draws LLM-DECIDED
again. *The label is still on the branch one layer down*: `_merge_judgments`
ranks by `(_DECISION_RANK[decision], fruitfulness_score)` (`:148-152`), takes
`deciding = max(...)` (`:154`), and lifts all three scores from that window
(`:182-201`) — so on a multi-window page (mean 2.71, max 4 live) the model's
label selects which score any new rule reads. C27 also needs a mechanical
clause: the gate decides whether extraction *runs*, so the compliant shape is
a pure predicate exported by `acquisition.py` and called from `extract`, and
what must not survive is `pipeline.py:1547` building an `accept` boolean that
`extract` gates on.

**Cycle 2 of 3 is consumed. Revision 3 was dispatched 2026-08-25 and is the
last** before the phase is marked Blocked with the verdict quoted.

**Revision 3 delivered** — same log, lines 6062–7296, appended after every
prior verdict, all preserved verbatim. Design only; no code. It **withdrew**
revision 2's premise rather than defending it and took `modularity-steward`'s
T3 *second, Ground-B-closing* form rather than the minimum: the relevance
judge's payload narrows to (question, declared target columns, page text),
with the contract block rendered from `acquisition.declared_credit_columns`
so the gate's question and the credit basis cannot drift;
`specificity_score`'s definition carried **verbatim** from the existing prompt
so 4E-c authors no score; and `decision`, `fruitfulness_score`,
`novelty_score`, `coverage_delta`, `_DECISION_RANK` and the label fallback
**deleted, not merely unread**. Measured: task state 85,208 rendered chars →
contract block 8,402. T2 closed as
`deciding = max(key=(specificity_score, -window_index))`, with
`_merge_judgments`' documented cost — the order statistic over document
length — registered as a measured clearance-rate-by-`window_count` observable
rather than left as a known property nobody quantified.

**The fact that licenses the stronger form, verified by the orchestrator and
stated in neither steward's text:** `judge_progress` has exactly one call site
(`strategy.py:456`, reached only from `pipeline._source_relevance_decision:1524`;
the only other occurrences are the import there and a re-export in
`__init__.py:75`). The progress judge *is* the source gate — there is no
second consumer — so narrowing is an edit to one gate rather than a fork, and
costs no second provider call. Its load-bearing argument: narrowing removes no
capability, because the wide payload existed for `novelty_score`
(`judge_progress:228-234`), and non-duplication relative to run state is
exactly what the accumulator computes by dedupe. *The estimate stood in for a
measurement that did not exist when it was written; 4E-c builds the
measurement, so 4E-c retires the estimate.*

**A genuine conflict between two stewards' requirements, flagged rather than
buried, and put to both.** `reward-design-steward`'s required item 3 asks for
a rule/label agreement rate; under `modularity-steward`'s T1 that observable
**cannot exist**, since it needs the model to emit a label and T1 forbids the
prompt from naming one — the instrument that would detect "the float is just
the label again" can only be built by reintroducing the mechanism it detects.
Revision 3 states this at §1.10, argues the hypothesis does not arise under
form 2 (T6's failure mode is foreclosed by construction — there is nothing to
fit to), substitutes a score decile histogram against the floor, and writes
out the fallback in one line (form 1: keep the payload and label, floor over
`specificity_score`, agreement rate computable) with its price named — Ground
B stays open, T1 stays failed. Either steward can rule for the fallback
without forcing a redesign. It also concedes that **no counterfactual over
this floor is computable**, since a rejected page is never extracted, and
names `evidence-verifier` blind against the emitted distribution as the route
that would later make the floor measured.

Its own new findings, three of them corrections against itself:
`_NON_VALUE_FIELDS` is **28** not 17; the credit basis is **13** and 9, not 14
and 9; and a "12,206 structural criteria" figure is absent from its cited
region and is dropped. RC4 was **stamped and rebased** — it found the half the
finding did not name, that `_orphan_cost_delta` is cumulative since
construction, so per-strategy records would each carry the whole run's
residual and summing them would multiply-count; P4E-c-10 registers the
partition identity. The orchestrator separately verified that `value_type` and
`unit` are absent on **all 32** columns of the live contract, so any
non-triviality clause resting on a declared type is structurally inert there
and is registered two-sided so the run cannot report it as exercised.

**Final-cycle review dispatched to all three stewards**, each told the cycle
position as fact and instructed explicitly that it must not influence the
verdict — a phase Blocked on an honest rejection is a correct outcome and
costs this build far less than a design passed to avoid the label.

**Cycle-3 verdicts, one of three in.** `prompt-mutation-steward` — **PASS**,
all five binding conditions closed, and it recorded that "the cycle count did
not enter this verdict", having considered a non-PASS on its new condition 6
and set down why it did not take one. It found §1 strictly better than
revision 2 at its surface: the model's label is **deleted, not merely
unread** — including `_DECISION_RANK`'s window selection, which was the route
by which the label chose which score a numerical rule would read — and it
judged §1.10's refusal to reintroduce the label in order to measure its own
removal to be the stronger form, since with no label in the record there is
nothing for a later phase to fit the floor to. Its condition 1 is closed at
the mechanism: seeds now enter the prompt whose output *is* the arms, so the
content the key is hashed over is content the run consumed; it is a data
channel and not prose steering on three checked grounds, the decisive one
being that seeds are **shared context across every arm of the call** and so
cannot differentially bias one sibling against another — the property that
keeps a sibling contrast meaningful.

**Three new binding conditions, of which one is a cross-phase consequence the
orchestrator verified end to end.** R1's fix **deletes the only producer of
`off_axis_count`**, which is a routing input rather than query text:
`search_memory.py:730` reads it from `skipped_by_reason["not_relevant"]`; its
sole producer is `search.py:540-541`'s `if not decision.accept:
outcome.skip("not_relevant")`, gated by the boolean revision 3 deletes by
name; and `strategy_state.py:503-507` branches on it
(`off_axis_dominant → target_terminology_swap`). Revision 3's fate table
assigns fate 11 a `credit_note` class and is **silent on `skip_reason`**, so
one of the pseudo-gradient's four named routing classes goes dead silently if
the hook writes the new label, or the population changes with an unregistered
direction if it writes the old one. Required: fix the fate → `skip_reason`
mapping, declare it once in `acquisition.py`, and register the `off_axis_count`
distribution two-sided so "the branch never fired" can be told from "the
branch no longer exists". Condition 7: the narrowed response shape turns
`matched_needs`/`missing_needs` into **column names**, and those are exactly
the two fields `strategy_state._memory_terms` concatenates into the literal
query — ranked ahead of `_field_terms`, whose docstring says field names come
last on purpose — while §8's registered observable is a distinct-term *count*
that would most likely **fall** under the substitution, reading as the safe
direction while the query surface degrades. Condition 8: carry
`strategy_origin` onto the arm and contrast rows.

`reward-design-steward` — **PASS with RC10–RC15.** Both revision-2 blocking
findings closed, all nine revision-2 conditions closed, and its revision-1
F1–F10 still closed. On **R2-F1** it found the fix stronger than what it had
required: "There is no label to branch on because the prompt does not ask for
one" — deleting the field forecloses the class, not the instance. It verified
the deepest half itself rather than accepting the note: the model's label was
choosing which window's number a numerical rule would read, and §1.6 replaces
that selector with the same expression the fate rule uses. It also drew the
boundary explicitly so the closure is not read as an exception — MODEL-SCORED
targets a model output that *is* the decision or that reward sums as yield,
whereas here the model reports one float whose definition predates the design
and arithmetic against a module constant takes the branch, which is the
charter's own worked example of a relevance grade.

**It ruled on the two-steward conflict by withdrawing its own requirement.**
The rule/label agreement rate is **withdrawn** and form 1 **ruled against**:
the observable was specified under form 1 and the hypothesis it tests does not
survive form 2; it cannot be built without reintroducing the mechanism it
detects; and buying it back means keeping a payload that hands a model the
run's declared stop criteria, catalog progress, universe estimate and
completion scope and asks it to weigh them. **RC13 replaces it with something
better than was asked for**: score-decile against credits **actually minted**
— a comparison with a *measured* quantity, where the agreement rate would have
compared the model against its own opinion of itself — recorded, never
branched on, disclosed as truncated at the floor, with `evidence-verifier`
named as the untruncated route.

**A fact it added that strengthens R2-F2 beyond the note's claim, verified by
the orchestrator:** `CRITERIA_PROJECTION_VERSION` is itself inside the
subject-id payload (`criteria.py:820-826`), so at the bump **every** subject id
moves, not only token-carrying ones — which makes §2.4's nothing-compares
clause necessary rather than prudent. **RC10**, registered two-sided and not
blocking: `declared_credit_columns` excludes subject-key columns by
construction (`acquisition.py:105-109`), and revision 3 now puts that exclusion
on the **gate's ask**, so a page carrying only declared key values is scored
against columns it does not claim to carry — the loop both declines to credit
and declines to admit identity-bearing pages. **RC12** names two mechanical
gaps that made RC4's partition identity hold by accident: §4 reads the
thread-shared meter **twice** where one snapshot serving both makes it exact
under a torn read, and `_orphan_cost_delta` carries every non-numeric field
whole including `error_class`, so one orphaned error would be counted once per
strategy. **RC14**: `SourceRelevanceDecision.confidence` loses its producer and
must not be backfilled from `specificity_score`. It also flagged **RC3's best
call** — keeping `pipeline._is_missing`'s empty-collection clause out of
`criteria` is right, since folding it in would have ridden a second,
undisclosed semantic change into `_subject_key_values` and `_project_field` on
the same version bump.

`modularity-steward` — **PASS with C48–C52; its amended LLM-DECIDED on R1 is
lifted**, and it stated plainly that "Blocked is not the right outcome here."
**All three stewards therefore PASS revision 3, and 4E-c's design closes on
cycle 3 of 3.** It ruled against the form-1 fallback on three grounds, the
first deciding it: **the agreement rate is not the instrument its name
suggests** — it compares the model to itself, a label and a float from one
call over one payload, so high is ambiguous between "the fix was cosmetic" and
"the model is coherent", low between "the fix bit" and "the model is noisy". It
measures self-consistency, never validity. It also re-verified all five
state inputs the form-1 payload would restore (`pipeline.py:1607-1626`) and
that T1 fails on its face there. The load-bearing argument holds at its
surface too: `judge_progress`'s own docstring (`:224-236`) says the state is
sent whole *because* novelty is defined relative to it — so removing that
score removes the payload's reason for being wide, and a page carrying only
already-seen values mints zero new identities at `scopes.observe`, the same
fact measured instead of estimated. Its **C50** is the substantive one:
`extraction.extract_from_text` swallows per-chunk failures and returns
`([], [])`, so the fate table's "extraction raised" row is unreachable for the
failure it names and a page whose every chunk failed becomes a barren *judged*
unit in the stop rule's denominator — the charter's silent-failure class, and
the design already holds the premise at the chunk grain without carrying it to
the page grain.

**A steward finding the orchestrator checked and could not reproduce.** C51
asserts the credit basis is 21 rather than 22, and the pre-fix basis 23
(13+10). Running that steward's own stated method against the live contract
gives **24 (14+10) pre-fix and 22 (13+9) post-fix**, with `evidence_gap` the
only column the predicate drops beyond the naive count. Restoring `magnitude`
to `key_columns` and dropping `subject_key_columns` reproduces C51 **to the
digit** (23 = 13+10, 21 = 12+9): the arithmetic and method are right and the
tree state is stale by one commit, since the `magnitude` grain ruling is
committed at `6f06549` and `magnitude` now sits *in* the credit basis. This
matters rather than being bookkeeping — C51 instructs the code review to
change a number that is already correct, and §1.3 sizes the model-facing
contract block over that same column set. The measurement and its
reproduction were routed back to the steward for restatement under a dated
heading; **the PASS is not reopened and the other conditions stand as
written.**

**C51 withdrawn by the steward, with its own diagnosis of the cause** (log
lines 8479–8645, dated heading). Needing the live contract, it listed the
filename across the tree and loaded
`question_runs/earthquake_twograin_20260823_130605_1da/code_snapshot/two_grain_table_spec.yaml`
— a **code snapshot captured by an Aug 23 run** — rather than
`experiments/runs/earthquake-impact/two_grain_table_spec.yaml`. It ran the
current tree's predicate against a two-day-old contract and reported the
difference as the design's error: `CLAUDE.md` §Checks' no-replay rule broken
inside a condition whose entire content was that someone else had carried a
number forward instead of re-deriving it. Re-derived against the live file it
reproduces the orchestrator's figures to the digit — pre-fix **24** (14, 10),
post-fix **22** (13, 9), `evidence_gap` the only column dropped — and it
corrects the orchestrator's reading in turn: **§0's 13 is the *post*-fix
earthquake number**, 14 being what the fix starts from. It withdraws two of
its own sentences with the condition. The 8,402-character block measurement
stands, so the no-drift property answering Ground B is intact, and it
confirmed C24, C29, C48, C49, C50 and C52 take no contract as input.

**The general rule this yields, carried into every dispatch brief from here:**
a `code_snapshot/` directory inside a run is *that run's recorded artifact*,
stale by construction the moment the tree moves. Anything measured from one is
a replay however current it looks, and the live tree is the only source for a
claim about the live tree.

**C51 as replaced — a real semantic change that was hidden under the bad
arithmetic, and a second-order consequence of the orchestrator's own
`magnitude` ruling.** `magnitude` is no longer a subject key and is now one of
the 22 credit columns. §9 row 20 requires every declared credit column *and*
every subject-key column non-trivial, with **subject keys verbatim only** — a
subject key can never be satisfied by a judged best guess, a credit column can
through R8. **So a guessed `magnitude` can now contribute to a
row-completeness credit where it previously could not**: a loosening of the
row-credit rule on the deliverable table, arriving from a contract ruling
rather than a design decision, landing exactly where RC8 already looks. One
paragraph records it; no new observable is needed, since P4E-c-13 already
emits the per-column verbatim/guessed split per row credit. The implementation
brief requires that paragraph to land **where a later reader of the reward
join will find it** — beside the row-credit rule in code and in the emitted
record's own documentation — not only in the design log.

**Verdict: PASS stands. C48, C49, C50, C52 as written; C51 as replaced; the
agreement-rate ruling unchanged. All three stewards PASS revision 3, 4E-c's
design is closed, and implementation is dispatched** with its own three
implementation-defect cycles, `modularity-steward` on the code before any run
and `experiment-steward` on the 4C v3 / 4D v3 registrations before any
provider call.

#### 4E-c: Coded (2026-08-25). Code review dispatched; nothing has been run

The provider surface is a composition of `rarefaction.Episode` —
`run ⊃ strategy ⊃ search ⊃ page` — with the round loop, `_fetch_papers` and
its wave loop, `_apply_strategy_yield_gate`, `_ingest_papers`,
`_acquisition_item_sink`, `SearchBatch`/`merge_search_batches`, both harvest
loops and `next_wave`/`requeue_front` deleted. **A round is a completed
strategy.** `Coded` is the starting line, not the finish: the phase closes on
the 4C v3 / 4D v3 live run behind two gates.

**Orchestrator verification, before the code review was dispatched.**
`tools/check_runtime_invariants.py` passes; no test suite was created; no
process is live and nothing has been run against a provider. By AST over the
live tree, **all fourteen claimed deletions are genuinely gone** — the twelve
above plus `_search_new`/`observe_item`/`close_search` and
`ScopedYield.facet_path` — and there is **exactly one `run_async` call site in
`question_pipeline`**, `acquisition.py:2431`, which is charter rule 1
delivered at the top level. The implementer's own contract re-derivation was
against the **live** file and reproduces 24 → 22 (13 + 9); it did not change
the design's 22 to 21.

**A scope trap recorded because it would mislead any later reader of this
diff.** `git diff HEAD` is **not** the phase diff: the working tree carries
uncommitted changes predating this phase. Separated by modification time, the
4E-c diff is 19 files touched today; `question_pipeline/estimator.py` — which
shows **−1096 lines** against HEAD — together with `provenance.py`,
`completion.py`, `llm_utils.py`, `strategy_state.py` and the `richness.py`
deletion are **inherited from 2026-08-22 and are not this phase's work**. The
code review was briefed with that separation.

**Two judgements by the implementer that the orchestrator endorsed.** It did
**not** write the v3 analyzer or the `4e-c-live` launcher, because both belong
to the registration — `experiment-steward`'s gate — and writing them now would
build the experiment before its prediction was registered;
`registry.package_hashes` and `assert_registered_all` are in place for that
launcher to call. And it exercised the changed code on constructed inputs
during development while **explicitly declining to offer that as evidence**,
since the phase's evidence is the live run. Both are the correct posture under
§"Coded is not evidence". Noted for the registration: `experiments/4c-4d/analyze.py`
reads `SearchOutcome.item_yield`, which this phase removes, so v3 needs an
analyzer written against `acquisition_episodes.json` and
`acquisition_page_detail.jsonl`.

**Code review: `modularity-steward` returned TEXT-COUPLED — not PASS**
(implementation-defect cycle **1 of 3**). It closed both conditions it had
graded substantive, and closed them well — C50's `PageFate` is a genuine
two-axis partition with a real producing side, and C51-as-replaced sits beside
the rule and in the emitted `row_credit_rule` — plus C1–C9, C11–C36, C38–C47,
C49, C52 and the other stewards' conditions it was asked to verify. "The
composition itself is right."

**F1, blocking, and reproduced by the orchestrator.** Two docstrings promise
that "a candidate naming an operator outside the injected catalog is rejected,
not renamed"; the `"\x00"` sentinel does not reject.
`control.select_first_clearing` skips only on a bad or below-floor distance and
on `key in opened`, so
`select_first_clearing([("\x00", 0.9)], floor=0.5, opened=set())` returns
**0 — accepted**. That raw model-emitted string then becomes the strategy's
`Episode.key`, a scope-path segment, `AcquisitionDecision.scope_key`, the key
`_eligible_families` reads, and the argument `SearchFrontier.next_for`
resolves by **string equality** — so a reworded operator reaches different
work. **This is 1D-a's verified failure class, model-emitted prose as a join
key, reappearing at a new grain in the phase whose own design deleted the
relevance label for the same reason.** Silent second consequence: such a
family matches no task, runs zero units, ends `exhausted`, and still enters
the run grain's stop history as a barren judged unit — after up to three
REASONING-tier samples and a full round body.

**F2, required, verified by the orchestrator.** `acquisition.py:1955-1959`
opens the `STRATEGY_PROPOSAL` cost scope with `view.units_consumed`, while the
owner `pipeline._round_label` (`:1582-1583`) returns
`round_offset + local_round_idx` and both live launchers pass
`--round-offset 3`. The switch edge's spend is stamped round `k` while its
strategy is `3+k`, and `reward.aggregate_round_cost` filters on that field —
**dropping the proposer's spend from the round that paid for it.** That is
`reward-design-steward`'s F1 reappearing through the very scope opened to
close it, and a second owner of `round_index` that revision 3's "one
expression" was meant to abolish. F3 (C48's disclosure of *why* no agreement
rate exists is claimed and not delivered), F4 (a subject-key column's declared
type is looked up in a basis that excludes it, so it always returns `""`) and
F5 — **a registration fix, not a code one**: P-R0c's predicted exclusion
classes would falsify against correct code, so the wording is corrected when
v3 is written. Fix dispatched.

**Cycle-1 fix delivered; code re-review dispatched.** Three files changed
(`acquisition.py`, `pipeline.py`, `strategy.py`); nothing the reviewer closed
was touched and the design was not reopened. **Orchestrator verification of
the blocker's fix, including the new risk the fix itself introduces:**
dropping candidates before selection shifts indices, so the map back to the
original rows had to be exact or the wrong candidate would be accepted.
`keyed`/`keyed_rows` are appended only for admissible candidates
(`acquisition.py:2172-2173`), `select_first_clearing` therefore sees only
those (`:2174`), and `rows[keyed_rows[index]]` (`:2179`, `:2186`) recovers the
original row — correct. The `"\x00"` sentinel is gone from the file entirely
and `""` never reaches `_opened_content`. F2 verified routed through the one
owner: `StrategyProposer.__init__` takes `round_index: Callable[[], int]`
(`:1959`), the cost scope calls `int(self._round_index())` (`:2062`), and
`pipeline.py:1633` passes `round_index=lambda: self._round_index`. The
implementer reports the scope now opening as
`("strategy_proposal", "run#p1", 3)` at offset 3 where the old expression gave
`0`. `tools/check_runtime_invariants.py` passes; no test suite, fixture or
mock was created; no provider was contacted. **The fix answers cycle 1 rather
than starting cycle 2; two cycles remain if the re-review does not close.**
The model's out-of-catalog rate is now measurable where it was invisible —
proposal rows carry `rejection_class` and the ledger carries
`operator_not_in_catalog`, both additions the v3 analyzer must read.

**Code re-review: `modularity-steward` returned PASS and lifted its
TEXT-COUPLED.** F1, F2, F3, F4, C10, C37 and both clauses of C48 closed;
**cycle 1 closes with two implementation-defect cycles unspent.** It drove
F1's new index risk under two drops plus a below-floor skip at once and
confirmed the accepted row is the catalog member; confirmed the ledger
partition holds in every case driven; and closed the silent second consequence
at the mechanism rather than the claim — no episode is built, and
`driver.py:554-575` writes a unit record only for a unit the source returned,
so nothing barren enters the run grain's stop history and the round body never
runs. **It searched for a second route by which a model-authored string could
reach `Episode.key` and found none**: `_open` has exactly two callers, and the
declared path's family resolves through `search.task_strategy_family`, whose
every writer in the package is a code literal. Every number in its review came
from executing the live tree against the live contract, never a
`code_snapshot/`.

Two required corrections, one edit each, neither needing another steward
cycle. **F6** — `acquisition.py:2246-2250` still asserts "`family` is always a
member of the injected catalog", which is **false on the first strategy of
every run** (the seed search is `expansion_op="llm_initial"`). Nothing breaks,
since those families are code literals, but *a docstring wider than the code
is exactly F1's shape*, and F1 was believed for a full cycle because two
docstrings promised a guarantee nobody had checked. **F7** — `_count_candidates`
admits any parseable float at or above the floor while `select_first_clearing`
rejects a non-finite one, so a ledger can read `cleared_floor: 3, accepted: 0`
with **no cell naming the reason**: the partition identity holds and
legibility fails. Also recorded for the registration and deliberately not
changed: `spec_digest` guards a mid-run rewrite correctly but digests the
basis *serialization*, so it is **not** a cross-code-version contract identity
and v3 must not compare it across phases.

Also
carried to it, as pre-existing and explicitly **not 4E-c's to close**: a third
live text chain, the judge's `matched_needs`/`missing_needs` reaching
`strategy_state._memory_terms` and being concatenated into the literal next
query — a mechanism the tree already documents at `progress_judge.py:173-176`.
Revision 3 must therefore narrow "the model sits only inside `extract`" to a
claim about **control** only.

*(Recovery note: a session limit cut the orchestrator mid-dispatch of this
review round and terminated its children before any verdict was produced. Disk
was re-derived — HEAD `6f06549`, no live process, no revision-2 verdict
section in the log, no code written — and all three reviews were re-dispatched
clean. Nothing was salvaged from the interrupted attempt.)*

`prompt-mutation-steward` (dispatched 2026-08-25, quoted verbatim at
`experiments/log/4E-c-provider-composition.md:1177`) returned
**TEXT-INFERRED — non-PASS**. Per §"Run protocol" any single non-PASS is a
non-PASS, so the design does not proceed to code; the revision dispatch waits
until `modularity-steward` and `reward-design-steward` report, so the phase
agent receives every condition in one cycle instead of consuming three.

It ruled the crux **PASS** and said so separately to prevent the verdict being
misread: the model *is* off the decision edge, because judging semantic
distance is string work and §11 step 4 branches on a written constant while
`rationale` reaches no predicate. Three blocking findings, of which the
orchestrator independently verified two against the tree:

- **F1** — the strategy's join key is a model-emitted string whenever the
  candidate's `operator` names no catalog member, which makes the untried-key
  conjunct evadable by rewording and puts 1D-a's own failure ("identity
  coming from model-emitted planner prose") back at a new grain. Fix: mint the
  key in code, reject candidates outside the catalog, record the model's label
  and never join on it.
- **F2** — a proposed strategy's `query_seeds` are not arms: no delta, no
  hypothesis, no arm id, and no stated owner for turning seeds into
  `SearchTask`s. Degrades silently rather than failing.
- **F3, verified** — the 1A order-dependent-attribution defect is fixed at the
  candidate layer (`control.py:691-696` includes `prompt_arm.id` in
  `dedupe_key`) and still open one layer below, where this composition takes
  its scope key: `SearchTask.stable_id()` (`search.py:90-98`) hashes only
  `{query, parent_id, topic, expansion_op}`, and `enqueue` (`search.py:278`)
  silently drops a repeat id in persistent mode — the mode `1da-live/launch.sh`
  runs in. Two arms with identical query text mint one `task.id`, so under
  `key=task.id` the branches are a silent frontier drop or a path collision
  that raises at `scopes.py:140-141` and unwinds the whole record tree, since
  §4 gives the driver nothing that catches. The design addresses neither.
- **F5** — §11's spent sampling budget returns `None` (exhausted), which is
  rule 6's defect that 4E-b was Confirmed for fixing: a cut recorded as a
  source that ran out. It needs `SourceEnd(END_BOUND_HIT, PROPOSER_EXHAUSTED)`.
- **F4** — `MAX_PROPOSAL_SAMPLES`'s "Bounds a cost, decides nothing" is false
  while the run verdict is inert below ten strategies; it is the operative end
  of the proposing arc and must be disclosed as such.

`reward-design-steward` (dispatched 2026-08-25, quoted verbatim in the same
log) returned **UNCOSTED and UNTRACEABLE — non-PASS**. It confirmed the
boundary this build cares most about holds — `reward.py` untouched, no
acquisition number reaching `score_criterion_yield`, the deferred wiring still
deferred, and **no model on any of §10's fifteen decision edges**, including
the three what-counts rows. Its two blocking findings are about the cost half
and the join half of the reward contract, which 4E-c is the phase that
physically lands:

- **F1** — the switch edge's model call sits inside **no cost scope**. §7
  declares two scopes (`search` around the provider call, `source` around
  fetch/judge/extract); §11's `await sample(...)` is a third provider-billed
  site inside neither, at reasoning tier, up to three samples per switch, with
  a payload carrying the finished strategy records, the table contract, the
  criteria snapshot and the deficits. The run source is pulled after both
  meters have reset, so `costs._target()` returns `_ORPHAN`, which carries
  `round_index=0` by construction — and `reward.aggregate_round_cost`'s filter
  can then only ever count it in round 0. **The switch edge is free in the
  record and expensive in reality**, on every strategy after the first. That
  lands on the one run that could give the reward's division step its first
  live evidence, which §3A records as having none at all.
- **F2, verified by the orchestrator** — §1.1 defines `round_index` as
  `len(record.unit_records)` at hook time, and that expression does not exist:
  `driver.py:459` types the hook's third argument as `UnitRecord`, whose
  fields (`:173-198`) are `unit_label`, `yield_record`, `credit_note`,
  `credits`, `facets`, `child`. `round_index` is a reward join key twice (the
  cost filter and the first-harvest credit window) and failure is silent —
  `records=0` yields `score = None`. Both correct values already exist:
  `UnitRecord.yield_record.unit_index` and `EpisodeView.units_consumed`.

Its most load-bearing condition, **F3**: no ID join exists from an acquisition
credit to a criterion transition in either direction, and that is *correct*
for a control signal — but it must be written down, because the only thing
standing between the charter's deferred reward wiring and a text join on
`(table, column) ≈ (table, field)` is a sentence nobody has written. The one
honest join is `source_id`. Also **F5**: §5.6's fan-up determinism claim is
false for a zero-unit child, reproducing one grain up the exact ambiguity
§5.6 abolishes; and **F9**: 1D-a's re-rolling identity reaches the new run
grain, where a drifting subject key makes every row credit new again across
the whole process — which ties 4E-c's correctness to 1D-a's diagnosis.

`modularity-steward` (dispatched 2026-08-25, quoted verbatim in the same log
under two dated headings) returned **LLM-DECIDED — non-PASS**: eight required
changes, twenty-three conditions. **All three stewards are now non-PASS and
design review cycle 1 is closed.** Its two findings the orchestrator verified
independently:

- **R1, the verdict word — a model sets the stop rule's denominator.** §10
  claims "No model call sits on any row of this table", but §4 routes five
  page fates onto one flag — four mechanical, one the relevance judge's
  boolean — and `disabled` means `active=False`, which `driver.py:374-376`
  passes straight through as `counts_toward_verdict=result.active`, which
  `scopes.py:212-217` uses to gate `tracker.record`. So a model's verdict
  decides which pages enter the `search` grain's stop-rule **denominator** —
  the rule deciding whether to keep fetching. Charter `:86-89`: "the model
  does not also decide what the number means for the loop." It also fails
  open, so a judge outage moves the verdict silently. Fix: a written fate
  table fixing `(active, counts_toward_verdict)` per fate, mirrored as a §10
  row naming where a model sets it.
- **R2, non-termination.** §6.3 calls `orchestration_stop_override` "the
  authority that can end the process"; `control.py:1216-1223` is a pure
  function returning `StopDecision | None` and raises nothing. With §8.6
  deleting the round loop, once the budget is spent every strategy ends
  `bound_hit`, `episode.py:257-261` excludes those from the parent's history,
  and the run verdict can never fire — with `max_rounds <= 0` supported,
  `Episode(RUN).bound` is `None`. An unbounded loop paying proposer model
  calls against a spent budget, with goal-fulfilled stops no longer mattering.

Also required: **R3** (a strategy path opens once, but the planner re-routes
to the same closed-catalog families, so from the second strategy on planned
work is enqueued under a closed path and silently never runs — which §13's
P4D-1 would misread as the expected observable); **R4** (the leaf label cannot
be `source_id` — `Leaf` is frozen and labelled at pull time, while `source_id`
is minted inside `extract`, so §7's cost join is unbuildable as specified);
**R5** (rule 1 is not delivered — §8 never names `_fetch_papers`, whose wave
loop pulls units and whose fourth call site survives the round loop's
deletion); **R6** (seed acquisition runs before an extractor exists, and
`extraction.py:84-86` swallows it, so the pipeline records "the genuine
negative" for a case that is not one — and 4E-c would make those pages units
of the first strategy's stop history).

Ruled sound and not to be regressed: §2.1's arithmetic (re-derived
independently — crossing 10 for both policies, `min_observations` moving
nothing), §5.1/§5.3's single owner for normalization and missing tokens,
§5.6's facet shape, §6.4, §6.5's refusal to force a yield verdict into
`control.PolicyDecision`, §7's single cost owner, §9's four export rules,
§8.7's kernel deletion, §14's hand-off of the `gasl/` configuration defect to
a named row, and all seven of §17's answers to the operator checklist. Rule 7
was ruled explicitly as asked: `SourceBudget`/`ProviderHealth` **licensed
outright** as byte-for-byte 4E-b's landed `NodeBudget` shape;
`PageUnit.credit_detail` **licensed narrowly** — single writer, single reader,
ordering guaranteed by the kernel's fixed step order rather than by
convention — conditional on three conditions, failing which the attribution
must move onto `PageMaterial`, the redesign §5.5(a) rejects. The scope
question: the forcing argument is **sound**, though for its second reason
rather than its first, and the teardown is **under-specified, not
over-scoped** — `pipeline.py:6052-6460` holds three acquisition branches, an
alternative round body with its own record and stop decision, an empty-graph
branch and five terminal breaks, of which §6.3 lists the main body only, and
the omissions are exactly R2.

#### Two operator instructions received mid-review, 2026-08-25

Both amend the design under review and were relayed to `modularity-steward`
in flight.

1. **The chunk grain.** Both surfaces must carry live evidence, and inside one
   fetched page the unit is one chunk extracted; 4E-c's registration must
   produce evidence at the page grain **and** the chunk grain, or state
   explicitly that it credits once per page from all chunks together and
   register what that costs — that the chunk-grain accumulator and verdict do
   not exist and the innermost row is unbound. **The instruction arrived
   asserting the charter's grain table already carries a chunk row. It does
   not**, and the orchestrator verified this rather than accepting it:
   `docs/ACQUISITION_LOOP.md:100-106` has one provider row ("one fetched page
   or document"); `:275-276` says "chunks are how a page is fed to extraction,
   **not a grain**"; `:408-409` says credits "are minted per page from all of
   them". Binding a chunk grain is therefore a **charter amendment**, not the
   implementation of an existing row, and `:108-109` supplies the derivation
   route that makes an amendment legitimate. If the grain binds, the charter's
   grain table, §"The compositions" and §"Surface bindings" 1 are amended in
   the same change, so the only place the rules live does not diverge from the
   code.

   **Ruled (R7), and adopted: do not bind the chunk grain in 4E-c.**
   `modularity-steward` verified the charter premise independently and ruled
   against binding on three grounds. Binding it would **delete the
   row-completeness credit kind**: the page would have to become an `Episode`,
   a parent's credits are then fixed as the child's distinct identities
   (`episode.py:249-256` — 4E-a Review 1 removed `Grain.project` precisely to
   keep that fixed), and `extraction.py:97-111` merges entities *across*
   chunks, so no per-chunk crediter would ever see a completed row and the
   charter would be amended against itself. It would also **serialize
   extraction** unregistered (`driver.py:532-537` forbids parallel prefetch
   where `extraction.py:90-95` gathers today). And the charter already carries
   the pattern for an unbound innermost grain at `:103` and `:273-274` — the
   GASL depth step. **The path that satisfies the instruction without the
   amendment**, and what 4E-c registers: name the chunk unit and credit
   sentences, emit per-chunk numbers inside the page's `UnitRecord` as
   declared disclosure with no tracker, policy or verdict, and register
   whether a chunk verdict *would* have changed anything — the numbers being
   in the emitted encounters, exactly as 4E-b decided the hop-level grain.
   That yields live evidence at the chunk grain, no charter amendment, and the
   innermost row unbound and saying so, which is what the instruction asked
   for. The override path is spelled out in the steward's log entry.
2. **Best-guess moves inside the `extract` slot** — verbatim extraction, then
   guided guessing for declared columns the verbatim pass left unfilled, with
   **one** `credit` call over the union. This is what makes the
   row-completeness credit kind **reachable**: under verbatim-only extraction
   a row completes rarely, so that accumulator sits near zero and the
   charter's §"Credits" kind 2 is nominal. The boundary is unchanged — model
   does string work, the crediter stays a deterministic projection, and it
   records **which kind minted each credit** so verbatim and guessed credits
   stay separable in the record and in any later reward join.
   `question_pipeline/best_guess.py` is the concept owner and moves *into* the
   injected extractor; it must not become a second loop, a second crediter, or
   a controller-sequenced stage. Whether a guessed credit may ever be a reward
   datapoint is unchanged and remains `reward-design-steward`'s question.
3. **Register the nesting itself — two live loops, not one.** Every experiment
   to date exercised **one** live grain: 4B and 4E-b bound the seed expansion
   inside a walk and measured that loop, while the grains above it were
   accounting only. So the template's central claim — a child episode *is* a
   unit of its parent, credits fan upward, each grain's verdict fires on its
   own denominator — **has never been tested with two loops live at once.**
   That is the claim the whole refactor exists to make and it is currently
   unevidenced. Five predictions, each with a falsifier, over every pair the
   run can reach (page ⊂ search, search ⊂ strategy, strategy ⊂ run, and chunk
   ⊂ page if the grain binds): (a) the denominators and curves differ, with
   each grain's crossing predicted from the policy arithmetic in advance;
   (b) **two-sided** — page-level yield collapses inside one search while
   search-level yield across searches stays high, so the inner verdict cuts
   that result list and the outer loop continues; if the inner never fires, or
   firing also stops the outer, the nesting is not doing what it claims;
   (c) the parent's distinct set equals the union of its children's distinct
   sets, both recomputing offline from the nested records — the charter's
   route 2 "from the leaves up", never yet exercised across a real parent and
   child; (d) an identity new to the child is a repeat to the parent, in an
   observed case, or the independent-dedupe claim is untested even if the code
   is right; (e) a `bound_hit` child's credits appear in the parent's curve
   while that unit is excluded from the parent's verdict observation count.
   Per 4E-b's lesson the registration names **which artifact carries each
   observable**, since only the nested record tree can carry a parent/child
   relationship and a flattened projection cannot.

##### Reachability, computed before any prediction is written

The operator requires each prediction to be reachable on the run's actual
configuration or registered as inert. The orchestrator computed this with the
kernel's own `searches_to_stop` rather than leaving it to the registration:

| all-barren | hit 0.05 | hit 0.10 | hit 0.15 | hit 0.20 | hit 0.25 |
| --- | --- | --- | --- | --- | --- |
| 10 units | 10 | 22 | 49 | 192 | never |

Identical at every grain: `min_observations` 4 (search) and 8
(strategy/run) both sit *below* the crossing, so they move nothing — §2.1's
claim is verified across hit rates, not only the all-barren case.

**On `experiments/runs/1da-live/launch.sh` as written, every grain's verdict
is unreachable**: `papers_per_query=3` against a search crossing of 10;
`queries_per_round=4` against a strategy crossing of 10; at most 4 strategies
against a run crossing of 10. The run-wide `max_papers=6` is **fewer pages
than a single search needs to fire**. So prediction (b), the asymmetric
two-sided condition that is the heart of this instruction, cannot be reached
on that configuration at all, and neither can any live verdict.

Two consequences, both binding on the v3 registration. **The 4C/4D v3 run is
configured to reach the crossings — `papers_per_query >= 10` with a page
budget to match — not by loosening a policy.** Lowering `min_useful_rate` or
`certainty` to manufacture a crossing inside a small run is tuning a threshold
against no measurement, which `experiment-steward` returns TUNED for and which
is not recoverable by re-running. And because firing also requires the pages
to actually be barren (10 units only at a hit rate at or below 0.05; 22 at
0.10; never at 0.25), prediction (b) is registered **two-sided against
observed barrenness** — the firing point conditional on the observed rate, and
inertness as the other side — rather than as a bare assertion that a verdict
will fire. 1D-a's own run keeps its small configuration: it is not measuring a
verdict and does not need one.

##### Two defects found during 1D-a's close, both required in the 4E-c revision

**The producer's self-grade is inside the acquisition credit basis.** Verified
by the orchestrator on the live contract: `evidence_gap` appears in
`acquisition.declared_credit_columns` for `earthquake_event_impact`.
`declared_credit_columns` excludes by `provenance.is_provenance_name`, which
returns `False` for `evidence_gap` and `completeness`, while
`criteria._is_value_field` returns `False` for both — so the field is **inside
4C's credit basis and outside 1D's projection**. §"From reward-design review of
1D" forbids "Producer self-verdict fields (`completeness`, `evidence_gap`)
re-admitted by any route", and this is that route: a page carrying an
`evidence_gap` string mints an acquisition credit, which is yield, which feeds
the stop rule deciding whether to keep fetching. The producer grades its own
output into a control signal. (`completeness` is not currently in the basis;
`evidence_gap` is.) Pre-existing, not created by 4E-c, and 4E-c is the phase
that owns the crediter.

**`event_date` is load-bearing at variable declared granularity.** Now that it
is half the `earthquake_event_impact` identity, `:47`'s "most precise form the
source states" means `2023-02-06` and `2023-02-06T01:17:35Z` are two subjects
for one event. Pre-existing; the grain-correct repair is a declared fixed
granularity with any finer stated timestamp kept as a separate reported column
— the same measurement-versus-identity logic the `magnitude` ruling turned on.
An open contract decision, deliberately not folded into that ruling.
2. ~~`experiment-steward` on 1D-a's standing registration.~~ **Returned
   2026-08-25: UNFALSIFIABLE.** Recorded in the 1D-a row above and quoted in
   full in `experiments/log/1D-a-live-declared-identity.md`.

**Sequencing ruling, adjudicated by the orchestrator against the written
criteria in §"Run protocol".** The steward
ruled that 1D-a should run **before** 4E-c, on the current tree, and that
ruling is adopted — it restores the order this tracker's own dependency graph
already states ("1D-a's live run precedes 4E and does not wait on it") and
which `docs/ACQUISITION_LOOP.md` §Sequencing repeats. The reasoning is that
4E-c rewrites `pipeline.py`, which produces every artifact all three
predictions measure, so deferring 1D-a guarantees a *third* re-registration
rather than avoiding one; and `control.py` is in 4E-c's path regardless,
since the strategy-ending decision is written at the `run` grain's hook, so
the guard trips either way. The run is four queries and six papers — the
credit saved by combining it with 4C was small, and 4C v3 cannot ride with it
in any case because 4E-c is still `Chartered` and no provider call may be made
against an unwritten registration.

Two further facts the steward established that bear on later work: one
execution *could* legitimately serve both 1D-a and 4C — neither has a
manipulated arm, so neither can contaminate the other's control — provided
the coupling is registered rather than assumed (4C's per-search verdict cuts
the exported-row population the 1D-a predictions quantify over, and
`acquisition.py:105-106` folds `subject_key_columns` into 4C's excluded key
set, making the 1D-a declaration an input to 4C's credit basis). And **4C
v2's steward verdicts are self-issued** — recorded in its log as "conducted
by the orchestrator against each steward's charter; no subagent dispatch
available" — which §"Review gates" disqualifies, so 4C's v3 registration
needs dispatched verdicts and cannot inherit them.

The resulting order, replacing the one this orchestrator was handed:
4E-c design verdicts (in flight, no provider credit) → 1D-a v2
re-registration and its run on the current tree → 4E-c code → 4C v3 and
4D v3.

Constraint on 4E-c's export, carried from 4E-b's durable lesson rather than
left in that phase's log: **routes 1 and 2 there shared an instrument.**
`route2.py` read the same `results.json` the runner wrote, so route 2 checked
the record's internal *consistency* and not its *completeness*, and a
projection defect reached both routes identically. A third artifact — the
execution trace — is what caught it. 4E-c's export must not repeat that
shape; its route 2 reads something the runner did not project.

### 4E-b — the GASL walk as an `Episode` composition (2026-08-25)

**State: Confirmed.** `experiments/log/4E-b-walk-composition-v3.md`; results
`experiments/runs/4e-b-walk-composition/out/`. Registered v3
(`983b5a6da32be6356faac35d88936c1f`) and run once, nine conditions, one
process. **Eleven of thirteen predictions carried live falsifiers and all
eleven held; P10 and P13 (and P12's C9 clause) carry none and are labelled
disclosure, every disclosed number re-observed exactly. Nothing failed.**

`_walk` is now one `Episode` — `walk ⊃ seed` declared as data, `query ⊃ walk`
available but unbound — with no loop of its own. Rule 6 fixed:
`_SeedStream.next` returns `SourceEnd(END_BOUND_HIT,
BOUND_KIND_WALK_NODE_BUDGET)`, the seed budget is `Episode.bound`, every
completeness branch reads the end the loop named, and the correcting wrapper
is deleted. Rule 7 fixed: `collect` is the sole writer of a typed `NodeBudget`
the source reads before a pull; `expand` reads neither it nor `walked_data`,
the intra-expansion row cut being deleted. Per-unit records are windowed with
disclosure instead of replaced by a label summary, restoring route 2 at
identity level.

**The decisive result (P5).** C5 against 4B's capped record, same inputs,
diffed field by field: **41 of 42 shared fields byte-identical; exactly one
moved — `walk_yield.ended_by`, `exhausted` → `bound_hit`, with
`end_reason='walk_node_budget'` newly present; zero fields lost.** That is the
charter's rule-6 defect demonstrated fixed on live data, two-sidedly: the old
value would have meant the fix did not land, and any *other* number moving
would have meant the rule-7 deletion was not behaviour-neutral. C1/C2/C3
reproduce the pre-composition record 42-of-42 fields identical on the same
graph bytes, with the walk binding as the sole manipulated ingredient. C4 is
the first live exercise anywhere of the disabled-crediter path (three id-less
seeds, `counts_toward_verdict=false`, verdict identical to C3's — the gate did
not leak). C9 exercised `graph_nav.py:795-810` live for the first time.

**An instrument defect this phase found, and the limit it exposes.** The
orchestrator reported P12's contract clause as failed after reading
`out/results.json`; the clause held. That file is a *projection* written by the
disposable runner, which for depth-1 executor conditions reuses 4B's
`run_walks.py:107-115` and emits only command/status/count/completeness — it
never carried `refinement`. The emitted contract does: five gated walks at 19
contract keys each, all `trigger=provider_error`; C9 at 18 keys with the field
absent. **The limit that matters beyond this phase: routes 1 and 2 share an
instrument** — `route2.py` reads the same `results.json` the runner writes — so
route 2 checks the record's internal *consistency*, not its *completeness*, and
a projection defect propagates to both routes identically. What caught the gap
was a third artifact, the trace. The defective code is the runner, which
teardown deletes; no `gasl/` change is licensed by it.

**Observed and not fixed under this registration**, all owed to a follow-up
row: A-1 (fan-out truncation reporting `BOUND_KIND_WALK_NODE_BUDGET` with
`bound=edge_cap` — registered as the expected value in P2), A-2 (`residual`
inflated by id-less seeds; C9's `residual=1` is this defect, **not** a seed
left behind — every one of its five seeds was pulled), A-3
(`adapters/base.py` docstring drift after the row-cut deletion), A-4
(`_SeedStream.next` testing the budget before pulling; no condition reaches
it), `modularity-steward`'s R1 (pilot episode record discarded) and R3
(`walk_yield["units"]` type change).

**R4 — a standing constraint violation with no owner yet, named here so it does
not dissolve into "owed".** `gasl/search_refinement_agent.py:122` re-derives
the environment fallback chain and the `gpt-5.5` default inline, and `:302-303`
resolves model and reasoning effort from env inline — duplicating
`gasl/llm/runtime_config.py`, which §"Standing constraints" makes the one owner
of configuration and credential resolution. Both code stewards flagged it; it
is pre-existing, P12 depended on current behaviour, so it did not change under
this registration. It belongs to the strict dependency-linear layering the
operator asked for and needs its own row: **4E-c takes it, or a `gasl-runtime`
housekeeping row does.**

Steward verdicts, all dispatched, quoted verbatim in the logs under the agent's
name: `gasl-design-steward` **PASS** and `modularity-steward` **PASS** on the
composition, both explicitly requiring no code change; `experiment-steward`
**UNFALSIFIABLE** (v1: P10's falsifier could not trip), then **POST-HOC** (v2:
C9's numbers read off the same tree before being registered), then **PASS** on
v3, then **PASS** on the result.

### 4E-a — `rarefaction/episode.py` (2026-08-25)

**State: Coded; design and code both PASSED by dispatched `modularity-steward`
reviews; the phase's one live run confirmed. Not `Confirmed` — 4E-a has no
experiment of its own and closes through 4E-b/4E-c (`docs/CONTROL_LAYER_EXPERIMENTS.md`
§4E).** All verdicts quoted verbatim, under the dispatched agent's name, in
`experiments/log/4E-a-episode.md` (Reviews 1, 1b, 2, 3, 4) and
`experiments/log/4E-a-kernel-compat-v2.md` (pre-run and post-run
`experiment-steward`).

Built: `rarefaction/episode.py` — `Grain` (the one policy owner), `Acquirable`
/ `Leaf` / `Episode` as a Composite whose `acquire` carries fan-up and the
bound-leak flag, `EpisodeView`, `UnitSource`, `leaves(...)`, `Context` with
ancestry-path scopes. `driver.py` rebuilt around `drive(source, acquire)` as
the one loop body, with `drive_episode` keeping its 4A signature as the
iterable form over it; `scopes.py` gains path scopes, `open_scope`, and facet
accumulators; `accumulator.py` gains `counts_toward_verdict`. Arithmetic
untouched; `stop_rule.py` byte-identical.

Design history, because it is the phase's substance: revision 1 →
**DUPLICATED-OWNER**; revision 2 → **DUPLICATED-OWNER and MISPLACED** (the
Composite was missing — `run` dispatched on `isinstance`, scopes were flat,
fan-up and the leak rule sat in the parent's loop); revision 3 → **PASS** with
thirteen code-review conditions. Code review 1 → **NOT PASS**, one blocking
defect: `_observe_facets` refused `facets={}` at any path scope carrying
credits, so a facet-less crediter (4E-b's walk) or an empty search under a
facet-declaring strategy would raise and unwind the whole record tree. Fixed
(implementation defect cycle 1 of 3); code review 2 → **PASS**.

Also closed here: 4A's owed dispatched `modularity-steward` review (**PASS**,
eight findings, quoted in `experiments/log/4A-kernel.md`); the
`experiments/stop-rule/` prototype torn down after 4B's route 2 verified the
port live; `PERMITTED_LOWER_LAYERS` wired into `scan_layering` as an explicit
allow conditional on purity (4A review F2).

**4E-a kernel compat (v2)** — `experiments/log/4E-a-kernel-compat-v2.md`,
results `experiments/runs/4e-a-kernel-compat/out/results.json`. **Behavior
preservation confirmed for the `drive_episode` level/key path only.** 4B's
GRAPHWALK, unmodified, on the refactored kernel reproduced D4B-1's live
pre-refactor numbers exactly on both conditions — 1a `yield_stop` at unit 17
of 40, `distinct=1`, `residual=23`, `bound_kind=walk_yield_stop`; 1c
`exhausted` at 40, `distinct=1,525`, `walk_node_budget` at `bound=50` — with
P-C1–P-C5 all held as registered, route 2 recomputing both verdicts to four
decimals in a separate process, and every pre-existing emitted key
byte-identical to the pre-refactor record (only `path`, `end_reason`,
`policy`, `facets` are added). **Does not confirm `episode.py`.**
`Episode`/`Leaf`/`Context`, path scopes, facets (including the
`_observe_facets` defect Review 3 blocked on), fan-up, `bound_hit`,
`SourceEnd`, and every `counts_toward_verdict=False` case were not executed by
this run; nor were duplicate seeds, a sparse graph, or any
`units_crediting_disabled > 0` unit (D4B-1b absent). Those close through
4E-b/4E-c. P-C3's stamped-policy clause is a shape check on this surface and
is recorded as disclosure.

Registration v1 was rejected by `experiment-steward` before running
(UNCONTROLLED) and never ran; it is retained in
`experiments/log/4E-a-kernel-compat.md` as the record, with its verdict.

**A defect in the record, disclosed rather than quietly fixed.** The
orchestrator wrote an `experiment-steward` verdict into
`experiments/log/4E-a-kernel-compat-v2.md` before the dispatched agent had
returned it. The agent's real verdict arrived afterward and is PASS, and the
licensing order was intact (its R3 requirement was applied and verified before
the run), but the recorded text was a reconstruction presented as the agent's
words — the self-review-as-dispatched-review failure §"Review gates" names. The
reconstruction was removed from the tree and replaced with the agent's verbatim
text under a correction notice in that log. The post-run `experiment-steward`
reviewed the corrected record and found it sound.

**Carried to 4E-b:** a D4B-1b-shaped condition (sparse graph, duplicate seeds,
non-degenerate curve, nonzero f1 at the stop); `gasl/search_refinement_agent.py`
into the registration's hash set; the model disclosure restated as observed
(the executor is built with no model, the agent reports `agent_unavailable`,
the hint steers nothing); the charter's pseudo-code residue (`on_child`, the
`isinstance` branch, `children`) amended when 4E-b next touches it;
`graph_nav.py:473-478` windows `walk_yield["units"]` with disclosure rather
than dropping per-unit credits, or route 2 cannot rebuild f1/f2/Chao1 from the
export; `expand` reads no `NodeBudget`; the node budget becomes
`SourceEnd(END_BOUND_HIT, BOUND_KIND_WALK_NODE_BUDGET)`; `Context(order=...)`
declared; both faces of the coincident-bound corner registered.
**Carried to 4E-c:** `ColumnProjection(spec)` picks one shape for a
credit-less page and holds it; the page `extract` converts fetch failures into
`CreditResult.disabled`, never a raise; only `Leaf` and `Episode` implement
`Acquirable`; facet accumulators record only `crediting_active`;
`ScopedYield.facet_path` is used or deleted; the strategy-ending
`PolicyDecision` is written at the `run` grain's hook.

## Dependencies

```
Phase 0
  ├─ 0E ─── 0M ─── 1B ────────────────────┐
  └─ 1A ─── 1D ─┬─ 1C ────────────────────┤
                └─ 2A ─┬─ 2B              │
                       └─ 2C ─────────────┴─ 3A ─── 3B

4A ─┬─ 4B ──┐
    └─ 4C ──┴─ 4E-a ─── 4E-b ─── 4E-c ─── 4C(v3) ─── 4D
                          (4C also needs 1D and the 1D-a fix: crediting
                           joins on declared criterion identity; 1D-a's
                           live run precedes 4E and does not wait on it)
```

The 4-series is the acquisition-loop rebuild chartered in
`docs/ACQUISITION_LOOP.md`: the phase-batched round flow was structurally
incapable of per-item and per-search rarefaction — the credits a keep-going
decision needs were computed two phases after the decision points had passed —
so the flow is rebuilt around a first-class episode loop rather than patched.
4A is pure arithmetic with no provider call and can start immediately. 4B
proves the loop generalizes on the smallest surface. 4C is the teardown of the
old flow and blocks on 1D-a because credits join on declared criterion
identity. 3A's reward consumes 4C's episode ledgers once they exist; until
then its round-end derivation stands.

0E and 1A start together after Phase 0 — 1A is pure vocabulary with no provider
call, so it does not wait on the harness. 0M needs 0E. 1B needs 0M. 1D needs 1A.
1C and 2A start once 1D lands, in parallel. 2B and 2C start once 2A lands, in
parallel. 3A needs 1B, 1C, and 1D. 3B needs 3A and 2C.

Every phase from 1B onward runs experiments, so all of them need 0E.

**0M before 1B, and before every phase experiment.** Tiering changes which model
serves which call site — a deliberate behavior change. Phase 1's claim is that
instrumentation is inert, and a model change riding inside it would corrupt that
A/A ablation. Land tiering, record the configuration, then hold it fixed for
the rest of the run. It also means every later run's costs are
interpretable, which they are not without knowing which model served which call.

1C follows 1D rather than running beside it because every ledger record carries
a criteria-snapshot ID, and a ledger written against an invented snapshot ID
cannot be joined to anything afterward. The serialization is deliberate.

### Why 1D exists

Earlier revisions of this tracker ran 2C, 3A, and 3B off a criteria snapshot
that no phase created. The concept was described in `AGENTS.md` and
`docs/MEMORY.md` as though it were in the tree; it was pruned with `cd44ebb`.
`criteria_snapshot`, `snapshot_id`, and `CriteriaSnapshot` have zero occurrences
at baseline, and the `criteria` in `goals.py` are goal-completion flags, not
per-datapoint criteria with stable IDs.

Five phases join on those IDs. Without an owner the graph is unsatisfiable, and
the failure is silent: an agent can invent a local snapshot inside its own
module, pass every test, and report Coded on sand. 1D makes the dependency
explicit and gives it one owner.

## Cross-phase handoffs

Findings from a closed phase that a later phase must act on. Raised by review,
not by the implementing agent, and recorded here because they die otherwise.

### From 1A review — for 1C

**`strategy_origin` key mismatch, silent.** Baseline writes `strategy_origin` at
`pipeline.py:2402` and `:2433` and reads it at `search_memory.py:251` through
`metadata.get("strategy_origin", "")`. `ActionCandidate.to_metadata()` emits the
same values under `action_origin` (`control.py:515`). Wire as-is and every memory
attempt records an empty string — the `.get` default means nothing raises. Either
project `ActionOrigin` onto both keys or carry a translation, but do not discover
this from a run.

**Do not add `rationale` back to the metadata projection.** `to_metadata()`
deliberately excludes it, which narrows an existing prose channel: baseline
records rationale at `search_memory.py:257`, those attempts land in
`strategy_history`, and `strategy.py:154` names that inside a prompt. Restoring
it would re-widen a text-coupling that 1A closed.

**Two owners of query normalization.** `control.py:1277` and `search.py:1010`
are independent, currently byte-equivalent `normalize_query` definitions, each
backing a live dedupe — `search.py:929-949` and `control.py:1244-1251`.
`control.py` cannot import `search.py` without breaking its purity, so the fix
direction is `search.py` importing control's, at wiring time. Left alone, a
change to one desyncs frontier dedupe from policy dedupe with nothing failing.

**`StopReason` halt values have no baseline counterpart.** 1C owns the mapping
and inherits nothing to map onto.

### From 2B and 2C review — for 3A

**`path_gate_admitted`/`path_gate_considered`/`path_gate_demoted` are plain
untyped integers in the ledger record and sidecar artifact, guarded only by
docstring prose.** `reward-design-steward`'s 2B review: nothing in `path_gate.py`
currently consumes them as reward, but when 3A wires reward to read the ledger
it needs an explicit, structural exclusion — a reward-ineligible-field list or a
namespace convention — not a comment for a future reader to notice. These are
survival counts, not yield.

**Outcome 5 from 2C (`search_memory.classify_path_outcome`) is not verified
support and must not be credited as such.** 2C's own ground-truth route
measured outcome 5's blind-agreement rate at 0.444 — *below* outcomes 2, 3, and
4, not above — and its 104 claim pairs are 104/104 `row_ref_accepted` and 0/104
on a bound subject. `reward-design-steward`'s 2C review restates this as a
standing trap: crediting `semantic_claim_pairs` length or a
`SUPPORT_GAINED_ATTRIBUTED` count as criteria-transition yield, without routing
through 1D's actual `diff_snapshots`/basis machinery, reintroduces the exact
volume-scoring this steward exists to block.

### From 1D and 0E review — for 3A

**Delete `reward.py:_coverage` (333-358); do not reconcile it.** It computes
cell-value-plus-row-source-ids, which is exactly `criteria.py`'s
`ROW_REF_UNCHECKED` basis — the same projection computed twice. The two have
**already drifted**: `criteria.py:_NON_VALUE_FIELDS` (887-913) excludes 21 names;
`reward.py:_STRUCTURAL_FIELDS` (85-99) excludes a different set including
`description`, `entity_name`, `title`, `url`, `aliases`. They disagree today on
which columns count as datapoints. Consume the snapshot instead.

**`gained_source_ids` does NOT mean a new source — an earlier revision of this
section said it did, quoting 1D's own report. That was wrong.**
`criteria.py:571-597` computes it as new *to this criterion*, and
`_transition_kind` (`:610-612`) emits `SUPPORT_GAINED` when `before is None`, so
for a criterion minted this round `old_sources` is empty and `gained_source_ids`
is *every* source the state cites, however old. SUB-3 measured 55–88% of
`SUPPORT_GAINED` landing on subjects absent from the earlier snapshot; SUB-4
measured 0.7–6% of new rows citing anything ingested that round. A 3A rule of
"credit when `gained_source_ids` is non-empty" therefore credits nearly all of
it, including the 3,839 gains at 9→10 that came from re-traversing 120
already-held papers.

Required form, an ID join that survives delayed credit:

```
credit iff gained_source_ids ∩ {sources first accepted this round} ≠ ∅
```

with `first_accepted_round[source_id]` from 1C/1B, not from the transition.
Necessary, not sufficient — a re-traversal can incidentally touch a new source.

**Credit `SUPPORT_GAINED` only — never `EVIDENCE_CHANGED`.**
`CriterionState.values` folds extractor strings into the snapshot ID, and
`_normalize_value` only casefolds and collapses whitespace, so an extractor
rephrasing "12 patients" as "twelve patients" emits a spurious
`EVIDENCE_CHANGED`. Rewording must not become yield. `criterion_id` correctly
excludes values, so the join key itself is prose-free.

**Close the `evidence_gap` prose chain** (`pipeline.py:198` → `goals.py:1714`,
`search.py:979`) and `goals.py:_row_status` (1707-1716). This is why 1D exists;
until it closes, rows-are-transport is nominal. (When this was written nothing
imported `criteria.py`; 1C, 2A, 2C, and 3A now do. The prose chain itself is
still open and is still 3A's to close.)

### From reward-design review of 1D — 3A must never credit

Verdict on 1D's `supported` definition: PASS with a mandatory floor. Verdict on
the `TransitionKind` vocabulary as handed to 3A: **VOLUME-SCORED** — four of six
members are operational counters with IDs attached.

Never credited, at any weight:

1. `CRITERION_ADDED` — 12,623–29,208 per round against 950–5,160
   `SUPPORT_GAINED`. Rows materialized, with an ID on it.
2. `EVIDENCE_CHANGED` — pays for re-extraction churn and duplicate-row spelling
   drift.
3. `BASIS_CHANGED` — every occurrence on this corpus is
   `row_ref_unmatched → row_ref_accepted` (812/812 at seed→5). Status did not
   move; a source got accepted. Crediting it pays per accepted source,
   multiplied by criterion fan-out.
4. `CRITERION_REMOVED`.
5. Any function of snapshot cardinality — counts, ratios, per-round deltas. It
   rises with traversal as a numerator and falls with it as a denominator.
6. `len(CriterionState.values)` or any per-value or per-source unit count.
7. `basis_strength` as a weight, summand, or average, and any floor at rung 3
   or 6. **It is non-monotone in trustworthiness and exploitable:**
   `ROW_REF_UNCHECKED: 3` outranks `ROW_REF_UNMATCHED: 2`, and
   `accepted_source_ids` is an optional argument (`criteria.py:502`) — so a
   strength-weighted reward is *raised by omitting it*. Reward would go up for
   declining to verify. Threshold predicate only, and only at an ACCEPTED rung
   (4, 7, 8).
8. `ROW_REF_ACCEPTED` and below as verified support. 0.450 agreement against
   unresolved's 0.417 — 0.033 of discrimination, inside noise at n=45. Also
   directly hackable: 22,461 `row_ref_unmatched` states sit one source
   acceptance away from credited support **with no new data**, and SUB-8
   measured that conversion happening.
9. `SUPPORT_GAINED` qualified only by non-empty `gained_source_ids` (above).
10. Any table reaching `project_rows` that is not a declared deliverable —
    named specifically, `best_guess_candidates` and `best_guess_context`.
11. Producer self-verdict fields (`completeness`, `evidence_gap`) re-admitted by
    any route.

**Creditable:** `SUPPORT_GAINED` where the after-basis is at or above
`FIELD_REF_ACCEPTED` **and** the round-scoped new-source intersection is
non-empty. On this corpus that yields **zero**. Report the zero.

**There is no negative term.** `SUPPORT_LOST` was observed zero times across all
six round pairs, and with no `CONFLICTING` state a criterion cannot leave
`SUPPORTED` on being discovered wrong. Supported count is monotone: 3A must not
read "supported went up" as "the answer got better," only "bigger."

**The one honest route to a non-zero reward** before the registry lands is a
version-bumped `criteria_projection_v2` adding a producible judged-best-guess
basis gated on `best_guess.accepted`, carrying `source_ids` and the operator
decision — the second datapoint kind in `reward-design-steward`'s charter, which
`EvidenceBasis` currently has no member for. Lowering the floor to
`ROW_REF_ACCEPTED` is tuning to green. **The two will be proposed in the same
breath and they are opposites.** Write the distinction into the 3A log before the
pressure arrives, because an identically-zero reward makes every 3B arm tie and
that phase's headline comparison unrunnable. The correct response then is the
best-guess basis or the registry — never the lowered floor. If neither is
available, 3B reports that its comparison could not be made.

**Cost granularity (F2).** `CriterionTransition` carries no `action_id`,
`decision_id`, `task_id`, or round index. Source-attributable actions have an
exact ID path via `gained_source_ids`; everything else — searches returning
nothing, traversal, extraction, best-guess operators — joins only through
`after_snapshot_id` to 1C's ledger, which every action in the round shares. That
is attribution by timing coincidence and is forbidden. **Round-level
yield-per-cost is the finest granularity honestly available** for non-source
actions. Do not divide a transition by one action's cost and call it costed.

**Version in the ID is deliberate.** `CRITERIA_PROJECTION_VERSION` is folded into
criterion and subject IDs, so no v1↔v2 join will match. That breaks cross-version
continuity for 2C — and is correct: it makes incomparability visible as a failed
join rather than invisible as a comparable number. Do not hoist the version out.

### From 0E — for 3B, with the evidence strength separated

The allowlist handoff bundles two claims of very different strength. 3B must not
treat them alike.

**Established (n ≥ 5): the allowlist collapses each query to a 2-3 item pool.**
Every condition in r1 and r2 landed on 2-3 allowlisted results, plus two screened
queries returning 15 raw / 0 allowlisted each. Independent of how any single
query was chosen. `paper_fetching/firecrawl_client.py:search_papers` keeps only
thirteen hard-coded domains.

**Indicative only (n = 1): a related query saturates to 1.00 overlap once
filtered.** Measured on one query, drawn under a screening rule that biases
overlap upward. The direction is right; the magnitude is not established.

What this means for 3B: arm contrast compares duplicate yield between prompt
arms, and under the current allowlist two arms searching the same subfield are
quantized onto the same 2-3 papers — so they may look identical whether or not
the arms differ. Treat that as a live threat to the C-versus-B comparison and
measure the pool size in the run rather than assuming it. Do not quote the 1.00
saturation figure as if it were established.

### From 1C review — for 2C, 3A, 3B

**Stop logic now lives in two places.** The round loop's own `if` statements and
`StaticTableFillPolicy.decide_stop` both decide stops; 1C duplicated the
*reading*, not the logic, and all three `_record_stop_decision` call sites
(`pipeline.py:4302`, `4401`, `4580`) discard their return value so the ledger
cannot steer the run. Correct for 1C's charter — but the two can drift, and
`control.py:1113-1115` says why that matters: "a ledger that disagrees with the
run is worse than no ledger." The end state that removes the duplication is the
loop branching on `decision.stop`, leaving `control.py` sole owner. Whoever
takes that on should.

**Nothing guards the `action_origin`/`strategy_origin` wiring.** A test that
once existed (`test_action_origin_and_strategy_origin_never_disagree`, deleted
with `tests/`) pinned only the vocabulary: it built both sides itself and
paired them by parametrization, so it never exercised the production pairings
at `pipeline.py:2540`/`2556` and `:2600`/`:2618`. Both are correct as written
and nothing reads `action_origin` today, so this is a coverage gap rather
than a defect. It closes the only way anything closes here — a live run whose
ledger is read back and the two keys compared — not by a replacement test.

**For 3A: ledger joins at `CATALOG_SEARCH` inherit the `evidence_gap` chain's
instability.** Gap-task queries are that prose concatenated at
`search.py:970-982`, and 1C hashes the query into the candidate ID — so a
reworded gap yields a different `control_action_id`. 1C adds no new branch on
the prose and does not widen the chain; the instability resolves when 3A closes
it.

**For whoever adds the next ledger surface:** the ~90 lines of seed-resolution
and write logic (`load_seed_control_decisions` at `pipeline.py:296-341`,
`_write_control_ledger` at `:4833-4855`) sit on the orchestrator only because
1C's charter confined it to `pipeline.py`. If 2C or 3B add ledger surfaces, that
block wants its own owner.

### From 2A — standing requirement and a version coupling

**v1 artifacts stay labelled v1 and are not regenerated.** `experiments/runs/2A/`
holds scores produced under `path_features_v1`; the module is now v2 because the
subject-key fix restored 28% of a family's prior-row joins and moves scores. Any
future re-measurement is a **new registered prediction under v2**, registered
before that run, with the v1 result retained beside it. Regenerating v1 numbers
under v2 would make the log's conclusions unreproducible from its own evidence
while appearing to confirm them.

**A version coupling the version constant does not cover.**
`relation_sequence` and `terminal_type` spell their types through
`criteria.normalize_key_value`, and those buckets are built and read entirely
inside `path_features.py` — they are not joins into the projection. So a change
to `criteria.MAX_VALUE_LENGTH` moves path scores through a path unrelated to
criterion identity, and `PATH_FEATURES_VERSION` would not trip. This is named in
the version constant's contract: a change to that limit is a path-features bump
as well as a criteria one. The rejected alternative — a path-features-owned
spelling — buys version independence by reintroducing the duplicate normalizer
that caused the v1 defect.

### From 1C — for 1B and everyone

**(Resolved 2026-08-17.)** This handoff said `run_question_pipeline.py` raised
`TypeError` before any search. It no longer does — `AGENTS.md` §"Question
pipeline runs" records the re-verification — and the launch scripts under
`experiments/runs/` use the runner directly. Kept because a later reader may
find the old claim quoted elsewhere.

**Instrumentation is inert in behaviour but not in wall time.** The criteria
projection supplying each ledger record's snapshot ID costs **~13.3 s per
refresh** on this corpus (448,869 criteria). 1B's cost accounting must not treat
recording as free, and any phase adding a per-round snapshot refresh should
price it.

**Ledger read order is decision time, not round index.**
`_expand_unfulfilled_table_goal` mints round *N+1* candidates before round *N*'s
stop record. That is correct and append-only, but a later per-round join that
assumes round-ordered records will silently get it wrong.

**Static behaviour was verified on an offline instrument, not a real run**, and
1C says so rather than narrowing the claim. Providers are nondeterministic, so
the identical-action-sequence assertion cannot be made against live runs. The
round-record half of C1 is reported untested.

### From 0M review — for 1B

**Never aggregate spend from `pipeline.llm.usage`.** `ArgoBridgeLLM` keeps a
per-instance `usage` accumulator, and `llm_utils.for_tier` memoizes a *separate*
client per model. Spend on a FAST clone accumulates on the clone, not on
`pipeline.llm`. Nothing reads `.usage` in `question_pipeline/` today and no call
site is FAST, so nothing is broken now — but the first site that moves to FAST
becomes free. Aggregate from per-call events.

Second: `for_tier` returns the client unchanged when it has no `clone`, silently
serving REASONING while `describe_tiers` reports the intended fast model.
Unreachable today. Record what *served*, not what was *configured*.

**One provider bypass remains in the package.** `schema_synthesis.py:282` passes
`llm_func=llm.call_async` directly — the only provider call in
`question_pipeline/` that never passes through `llm_utils`, and therefore the
only one that cannot be tiered or recorded by call site. Pre-existing, not 0M's.

### From 0M review — for 2B and 1A

`control.py:628-629` still declares `path_selection_reason` and
`path_exclusion_reason` as bare `str`, coerced at `:679-680`. 2A closed the
producing end with real enums; the receiving field still accepts anything, so
the closure is a convention rather than a constraint. Type those fields to
`PathSelectionReason` / `PathExclusionReason`.

### Line numbers for the `evidence_gap` chain have shifted

Production is now `pipeline.py:237`, the branch is `goals.py:1714`, prompt
assembly is `search.py:977-983`. There is also a **second, pre-existing
assembly** at `pipeline.py:2054-2055` concatenating the same prose into a gaps
list. Still 3A's to close.

### From 0M's manual audit — cross-cutting, and possibly a common cause

Found by reading items by hand after every metric came back uninterpretable.
Observational and unblinded: it licenses no model switch, and the proportions
below are characterisation, not measurement.

*(Editorial note, 2026-08-25: this section originally quoted extracted entity
strings verbatim from the earlier epidemiological table task. Those quotes are
paraphrased below — a measure name and its value stand in for the original
text — because agents reading this file in full were being killed by a
model-level safeguard false-positive on that vocabulary. Every number, ratio,
and finding is unchanged; only the illustrative domain strings moved. The
originals remain in `experiments/log/0M-extraction.md` for anyone auditing the
0M campaign itself.)*

**Extraction silently returns empty on some chunks.** On one of six audited
chunks the reference model returned `{"entities": [], "relationships": []}`
with status `ok`, 3 calls, **28,058 completion tokens and 331 seconds** of work.
No error, no retry, no signal. The cheap model on the same chunk produced the
actual deliverable — a measure entity carrying the measure name, a numeric
range, and populated `country` and `reported_range` attributes.

The comparator scored that chunk **0.000 with 66 unmatched**, which reads as a
catastrophic cheap-model failure and is the exact opposite of what happened.

**This is a candidate common cause for two other phases' findings, and it should
be tested rather than assumed.** 1D found its projection agreed with blind
re-derivation at chance because the rows simply lacked the fields, and located
the gap "upstream in extraction". 2A found four of six features have no inputs
on 89% of routes. Silent whole-chunk extraction loss would produce both. No
phase has tested this link; whichever phase touches extraction next should.

**Leiden community detection fails as an entity matcher here — proven, not
assumed.** Per-chunk similarity graphs over token Jaccard, containment, and
`observation_quote` span overlap produced 52 mixed communities that
systematically over-merge. Two mechanisms: a shared head noun swallowed five
distinct items sharing one high-frequency subject token, hiding a real loss;
and **source-span co-location is not identity** — a dataset name and version, a
count of interventions, a count of territories, and a date merged because all
four are quoted from one sentence. The disproof is that it merged items which
had *already* matched 1:1 by name. Useful for localising granularity, unusable
as the matcher.

**The residue is not one thing.** Hand-classified over 108 unmatched entities:
40% is noise (enumeration split/merge, near-synonym duplication, surface
variants, type disagreement on the same referent) and **50% is real content
difference**. Neither the granularity hypothesis nor the substance hypothesis
wins.

**Duplication is the reference model's, not the cheap model's** — five
CONTEXT_FACTOR entities for one idea against cheap's one, where the schema says
"avoid duplicates". The reference model's higher item count is partly inflation,
which inverts the naive reading of any count-based comparison.

**Excluding the empty chunk, ref-only real content is 38 against cheap-only 2** —
the first quality evidence in the campaign, favouring the reference model on
five of six chunks. Real cheap-model loss concentrates in methodology and
provenance: a whole truncation protocol, six named sources, every `LOCATION` in
one chunk.

**A comparison unit derived from content, satisfying both conditions:** the
association tuple, matched on (measure, value, country, time). Only 26 of 198
entities carry structured attributes and 7 are measure-valued. The
discursive remainder is where all the noise lives and is not what the deliverable
table is built from. `extraction` has **no input-supplied key at all** — the
model chooses both what to emit and how many — which is why its residue is the
worst of nine sites, and why it cannot arbitrate forced-emission versus
segmentation for other sites.

### From 0E re-review — for 1B, blocking and structural

*(The `experiments/harness/` package these two 0E sections refer to —
`runner.py`, `attach_recorders`, `experiments/harness/tests/` — was pruned
and no longer exists; `experiments/README.md` §"The apparatus was pruned".
The pipeline-side findings below still stand; the harness-side ones are
history.)*

**Make `_probe_search` emit a `SearchOutcome` with cost fields BEFORE adding cost
fields anywhere else.** Probe spend is currently invisible through *both*
available routes, not one: the harness no longer wraps `_probe_search`, and
`grep -n "search_outcomes" question_pipeline/estimator.py` returns **no matches**,
so probe searches produce no `SearchOutcome` either. When `_uses_default_search`
is true, `_probe_search` issues its own `search_papers` at `pipeline.py:527-533`,
bypassing `_search_fn` entirely.

If 1B adds cost fields to `SearchOutcome` without making `_probe_search` produce
one, **probe spend becomes structurally invisible to reward** — not merely
unrecorded by the harness — and no test anywhere would show it. 1B exists to make
reward prefer cheap yield; a path whose provider calls are free in the record and
expensive in reality is exactly the bias that makes reward prefer the wrong
thing.

Two further consequences of the same gap: resume silently re-spends, because
`_search_fn` calls are served from the record while probe calls are re-issued
against the provider on every resumed run; and replay is not provider-free, since
replaying a run that used the estimator would reach a live provider.

The fix is in the pipeline, not the harness — emitting the outcome row means
`record_search_outcomes` picks it up with no harness change, and probe spend
becomes visible to reward rather than only to the capture.

**Any phase touching `pipeline.py:803` is on notice.** A test that once
guarded it (`test_attach_recorders_intercepts_the_real_pipeline_fetch_path`,
deleted with the harness and `tests/`) was the only thing that noticed if
`SearchHarvester` construction was hoisted out of that line. Nothing guards it
now; a phase that moves that construction says so in its log and shows on a
live run that search capture still records.

### From 0E review — for 1B, blocking

**The harness's one-way-dependency guard does not work.**
`experiments/harness/tests/test_harness_plumbing.py:309-331` shells out to
`git grep`, which searches tracked files only — and every deliverable in this
build is currently untracked. A violation in a new module passes the check.
Proven with a probe file. Also misses `importlib.import_module("experiments...")`.

**`attach_recorders` double-records through `_probe_search`.**
`runner.py:322-324` wraps `pipeline._probe_search`, which is a bound method, not
a dependency. When a `search_fn` is injected, `pipeline.py:521` routes through
`_search_fn` — already wrapped — so one call records twice against a shared
occurrence counter, desyncing the recorded prefix on resume. The dedup
experiment missed it because `_fetch_papers` never reaches `_probe_search`; the
estimator does, at `pipeline.py:2236`. 1B's cost accounting is where it bites.

**Named silent-breakage trigger.** `attach_recorders` works only because
`pipeline.py:803` reads `search_fn=self._search_fn` inside `_fetch_papers`, per
call. Any phase that hoists `SearchHarvester` construction into `__init__`
leaves the harvester bound to the unwrapped function: attachment still succeeds,
and every capture silently records zero searches. No exception, no failed
assertion. There is currently no test that `attach_recorders` intercepts a real
pipeline's search path.

### From 1A review — for 2B

`path_selection_reason` and `path_exclusion_reason` (`control.py:628-629`) are
bare `str` on the exact surface where 2B records why a row was excluded. Every
other vocabulary in the module is closed, including `ExecutionErrorRef.reason`,
whose docstring requires "class labels from the raising subsystem, not prose for
a human." Hold to that standard or close the pair into an enum.

### From 1A review — for 3B and `prompt-mutation-steward`

**Dedupe starves duplicate arms, and it touches 3B's central claim.**
`_base_identity` (`control.py:1292-1298`) includes `prompt_arm.id` in the action
ID, but `SearchCandidate.dedupe_key` (`:588`) omits it. Two arms proposing the
same query for the same target therefore collapse in `_admissible`, and the
first-seen arm takes all outcome attribution — so arm credit depends on proposal
order. Defensible as cost control, but 3B predicts contrast-routed mutation beats
randomized routing, and an order-dependent credit assignment is exactly the kind
of artifact that could produce or destroy that difference. 3B's identical-query
attribution requirement lands directly on this.

## Review gates

Standing stewards review by concern, not by phase. Each returns a verdict with a
quoted citation.

| Steward | Concern |
| --- | --- |
| `experiment-steward` | Falsifiability, controls, predictions registered in advance, two routes, no tuning to green, scaffolding torn down |
| `gasl-design-steward` | Generic commands; schema coupling; expressive narrowing |
| `prompt-mutation-steward` | Arm mechanism; provenance by ID; contrast semantics |
| `reward-design-steward` | Real datapoints; cost terms; attribution joins |
| `modularity-steward` | Data-not-text boundaries; module isolation |

`evidence-verifier` is not a steward. It is a blind measuring instrument, run as
part of an experiment's ground-truth route, and it never sees the pipeline's
answer.

No phase closes on a green suite alone, and none closes without
`experiment-steward` review of its experiment — twice: once on the design,
before any provider call, and once on the result.

| Phase | Required verdicts |
| --- | --- |
| 0E | `experiment-steward`, `modularity-steward` |
| 0M | `experiment-steward`, `modularity-steward` |
| 1A | `modularity-steward` (no experiment; confirmed via 1C and 2C) |
| 1B | `experiment-steward`, `modularity-steward`, `reward-design-steward` |
| 1C | `experiment-steward`, `modularity-steward` |
| 1D | `experiment-steward`, `modularity-steward`, `reward-design-steward` |
| 2A | `experiment-steward`, `modularity-steward` |
| 2B | `experiment-steward`, `modularity-steward`, `reward-design-steward` |
| 2C | `experiment-steward`, `modularity-steward`, `reward-design-steward` |
| 3A | `experiment-steward`, `modularity-steward`, `reward-design-steward` |
| 3B | `experiment-steward`, `modularity-steward`, `reward-design-steward`, `prompt-mutation-steward` |
| 1D-a | `experiment-steward`, `modularity-steward`, `reward-design-steward` (amendment to 1D; same verdicts) |
| 4A | `modularity-steward` (no experiment of its own; closes via 4B/4C consumer runs, which carry `experiment-steward`) |
| 4B | `experiment-steward`, `modularity-steward`, `gasl-design-steward` |
| 4C | `experiment-steward`, `modularity-steward`, `reward-design-steward` |
| 4D | `experiment-steward`, `modularity-steward`, `reward-design-steward`, `prompt-mutation-steward` |
| 4E-a | `modularity-steward` on the template design **before code** (the class, its slots, the nesting contract), then again on the code; no experiment of its own — closes through 4E-b/4E-c |
| 4E-b | `experiment-steward`, `modularity-steward`, `gasl-design-steward` |
| 4E-c | `experiment-steward`, `modularity-steward`, `reward-design-steward`, `prompt-mutation-steward` (the `run` source is the switch edge) |
| 4G-a | `modularity-steward`, `reward-design-steward` on the isolated estimator boundary; no experiment of its own and no live-path wiring |
| 4G-b | `experiment-steward`, `modularity-steward`, `reward-design-steward`; its registered live run supplies the evidence for the complete amended method |
| 4G-c | `experiment-steward` on the foundational live design and result; independent modularity and evidence/reward reviews are already PASS |

This table is authoritative; where a charter's "Done when" disagrees, this wins.
`modularity-steward` reviews every phase — including any change the
orchestrator itself makes to unblock a run; a fix in a steward's domain that
the steward is told about afterward has not been reviewed.
`reward-design-steward` reviews any phase that could turn operational volume
into a score — which includes 2B and 2C, where survival counts and outcome
classes are the temptation, and 4C/4D, where episode ledgers and strategy
verdicts are. `gasl-design-steward` reviews anything touching `gasl/`; the
0–3 series was not expected to touch it, and 4B does.

**Verdicts come from dispatched steward agents, not from the orchestrator
reading a steward's charter file.** A review conducted "against the charter"
by the orchestrator or the phase agent is a self-review and does not satisfy
this table. The log records which agent returned each verdict.

## Phase gates

A phase closes at `Confirmed` or `Diagnosed`, never at `Coded`. The experiment
contracts in `docs/CONTROL_LAYER_EXPERIMENTS.md` define what each phase must
show; the gates below are the headline claim each one is making.

- **Phase 0** — tree at baseline, result recorded here.
- **Phase 0E** — the harness reproduces the deduplication ordering on real
  search: identical query near 100%, unrelated topics near 0%, related-but-
  distinct between. The apparatus is not trusted until it recovers an answer
  already known.
- **Phase 0M** — every LLM call site has an equivalence result with its own
  sensitivity control and a threshold registered in advance; tiering the results
  support is implemented, and sites needing reasoning are recorded as such.
- **Phase 1** — costs match provider-reported ground truth and instrumentation
  is inert; the ledger reconstructs real decisions and survives resume; the
  criteria projection agrees with blind re-derivation from chunks in **both**
  directions.
- **Phase 2** — `path_score` predicts the LLM's later `evidence_gap` verdict;
  the gate preserves partial records; all five path outcomes occur and agree
  with a blind reading.
- **Phase 3** — reward prefers yield over volume when the two are decoupled on
  real runs; contrast-routed mutation beats randomized routing, or the negative
  result is diagnosed to a verified cause.
- **Phase 4** — the acquisition loop is one class (`rarefaction/episode.py`
  over `driver.py`), and every surface is a composition of it with no loop of
  its own: the GASL walk, the provider search (run ⊃ strategy ⊃ search ⊃
  item), and the strategy grain, each grain declaring its unit and credit;
  Firecrawl and GASL are peer search types with separate scope paths, epochs,
  incidence histories, estimates, controllers, and verdict records;
  on real runs each verdict fires at the registered arithmetic point and the
  nested records recompute offline to the same verdicts from the leaves up;
  the per-search verdict cuts result-list consumption with a disclosed
  reason; the strategy verdict ends its episode and the run's source
  proposes the next; the 1D-a declared identity makes crediting join.

## Standing constraints

- The GASL command set is fixed at the existing 29.
- Canonical literals only in generic paths: `id`, `name`, `entity_type`,
  `relation_type`, `source`, `target`, `src_id`, `tgt_id`.
- Modules exchange typed data, never generated prose as control input.
- Deterministic policies only. No learned models, no bandits.
- Decisions are numerical; models do string work. Every stop, continue,
  switch, when-to-mutate, and what-counts decision is a rule over measured
  counts with a written threshold — not numerical plus a model
  (`docs/ACQUISITION_LOOP.md` §"Decisions are numerical").
- Configuration and credentials resolve through one owner
  (`gasl/llm/runtime_config.py`); a call site re-deriving the fallback chain
  is a modularity defect.
- Phase 1 preserves static behavior: recording a decision does not change
  which decision is made.

## Run protocol

### The orchestrator

The orchestrator is `.claude/agents/build-orchestrator.md`, dispatched as a
**fresh agent** by the launching session. Two of its rules are the
**operator's explicit instructions** (2026-08-23), recorded here so a later
reader treats them as given:

- **Dispatch a fresh agent that runs a team.** The instruction was an
  orchestrator that "spins up subagents" so stewards catch defects inside the
  team's own conversation. A fresh agent holds the `Agent` tool and does
  that. Why it is spelled out: the harness defines a fork as a direct
  executor, and two fork-orchestrators in this build reviewed their own work
  against steward charters, one also relaunching a run already in flight.
- **Work serially.** "Work with these parts in serial, not massive parallel
  tasks; care taken over each part." One phase resolves before the next
  opens.

The launching session writes the brief, dispatches once, and relays the
report; the orchestrator runs the team. The orchestrator owns:

- **Sequencing.** Walk the dependency graph **serially**: one phase at a
  time, fully resolved before the next starts. The graph shows where
  parallelism would be possible; this build does not use it. One live
  pipeline process at a time; before any launch, check for a running
  `run_question_pipeline.py` and adopt it rather than starting a second.
- **Gate evaluation.** Run `tools/check_runtime_invariants.py` (static analysis, not a test)
  itself after each phase. A phase agent's self-report is a claim, not
  evidence — the orchestrator verifies before writing a row.
- **Steward dispatch.** Invoke the required stewards from the table above, with
  the phase diff and the files touched. Phase agents do not invoke their own
  reviewers; an agent that grades its own work has no gate at all.
- **Tracker writes.** The orchestrator is the only writer of the phase table in
  this file. Phase agents report status in their final message and never edit
  it, so the table has one writer and one point of verification regardless of
  who is working.
- **Commits.** One commit per closed phase.

### Phase loop

Per phase:

1. Phase agent implements. `tools/check_runtime_invariants.py` passes (the
   only mechanical check; there is no suite). State → `Coded`.
2. Phase agent registers its experiment in `experiments/log/<id>.md`: claim,
   conditions, predicted direction per condition, falsifying result, and the
   two confirmation routes. **Before any provider call.**
3. Orchestrator dispatches `experiment-steward` on the design. Non-PASS returns
   for redesign — an unfalsifiable or uncontrolled experiment must not be paid
   for.
4. Run it. Real providers, real search, real data.
5. Orchestrator dispatches `experiment-steward` on the result, plus the phase's
   other required stewards.
6. Prediction held on both routes → `Confirmed`. Prediction failed → the failure
   protocol below, ending at `Diagnosed`.
7. Tear down diagnostic scaffolding, then commit. The remaining
   diff carries only the permanent change the finding justified.

**Three revision cycles maximum on implementation defects** — a steward citing a
modularity or reward defect, or an invariant-checker failure. On the fourth, revert the
phase, mark it Blocked with the verdict quoted, and continue with every phase
whose dependencies are still satisfied. A blocked phase blocks its dependents,
marked Blocked-upstream. It does not block the run.

**The cycle cap does not apply to failed predictions.** A prediction that does
not hold is not a defect and does not consume a revision cycle. It starts an
investigation.

### When a prediction fails

Never fix the cause you thought of first. Enumerate several candidate causes,
design a sub-experiment for each whose result differs depending on which is
real, run them cheapest-and-most-invalidating first — as small live runs, never
as replay against recorded data — and record the verified cause before applying
any fix. Full protocol and a worked example in
`docs/CONTROL_LAYER_EXPERIMENTS.md` §"When an experiment fails".

**Never tune to green.** Adjusting weights, thresholds, quintile boundaries, or
conditions and re-running until the direction flips produces a number with no
information in it. `experiment-steward` returns TUNED for this and it is not
recoverable by re-running. A parameter that genuinely needs to change is a new
prediction, registered before the new run, with the old result kept in the log.

A phase whose claim is disconfirmed and whose cause is verified reaches
`Diagnosed` and closes successfully.

Conflicting steward verdicts: any single non-PASS is a non-PASS. Stewards do not
negotiate, and a PASS from one never overrides a rejection from another.

### Failure handling

| Condition | Action |
| --- | --- |
| The phase's registered falsifier trips on a real run | Revert the phase, retry once from the reverted tree. Second occurrence → Blocked, continue the run. |
| Steward non-PASS | Revision loop above, max three cycles. |
| A run ends by anything other than its own completion (session cutoff, kill, provider refusal mid-run, a second copy launched) | Invalid. Record it in the experiment log with the cause, delete the partial output directory, never cite it. The registered predictions stand for a clean relaunch. |
| A dependency named in a charter does not exist at baseline | Do not reconstruct it from `cd44ebb` and do not invent a local substitute. Mark Blocked citing the missing name, and continue. If it is the criteria projection, it is 1D's deliverable — wait for 1D, do not build your own. |
| Phase agent reports done with an unmet contract | Orchestrator's verification catches it. Treat as a non-PASS cycle. |
| Ambiguity in a charter | Resolve it against this document, then `docs/CONTROL_LAYER_EXPERIMENTS.md`, then the whitepaper, in that order. Record the reading in the phase commit message. |
| A prediction fails | Not a defect. Run the failure protocol to `Diagnosed`. Does not consume a revision cycle. |
| Provider returns out-of-budget | Record what was collected, mark that experiment incomplete in its log with the conditions that did complete, and continue the run. There is no pre-set spend cap — the provider's refusal is the only limit. |
| Diagnostic scaffolding still present at phase close | Not done. Tear it down, then commit. |

### Terminal condition

The run ends when every row reads `Confirmed`, `Diagnosed`, or `Blocked`. No row
ends at `Coded` or `Open` — the first means an implementation nobody tested, the
second an investigation nobody finished.

The orchestrator then reports: each row's state, the claim and the result for
every experiment, every verified cause for every `Diagnosed` row, the blind
verification agreement rates, which steward agents were dispatched and their
verdicts quoted, invalid runs recorded and removed, that `experiments/`
teardown is complete, and the commit range. Negative results are reported as
findings, in the same register as positive ones.
