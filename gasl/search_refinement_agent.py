from __future__ import annotations
"""
LLM-guided search refinement for GASL runtime probes.

This module does not validate execution truth. It looks at sampled output and
recommends a next-step search refinement for retrieval/filter stages.
"""

import json
import os
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, Optional

from .sampling import deterministic_sample


# Closed vocabulary for why a refinement decision was not the model's.
#: The provider call itself failed -- nothing was returned and nothing was paid
#: for a usable answer. The client instrumentation records this as an error.
TRIGGER_PROVIDER_ERROR = "provider_error"
#: The provider call SUCCEEDED and was paid for, and the response could not be
#: parsed. Kept apart from a provider error because no exception reaches the
#: client wrapper on this path, so it never lands in the error vector: a run
#: where every refinement response is malformed looks, to cost accounting,
#: exactly like a run where every one succeeded. Same money, no answer, and
#: previously no way to tell.
TRIGGER_PARSE_ERROR = "parse_error"
#: Retained as the general label for "no model decided this", for callers that
#: do not care which of the two happened.
TRIGGER_AGENT_UNAVAILABLE = "agent_unavailable"
#: The pilot walk produced no rows, so there was nothing to judge.
TRIGGER_EMPTY_PILOT = "empty_pilot"


def refinement_record(
    *,
    hint: str,
    available: bool,
    sample_size: int,
    caps: Dict[str, Any],
    trigger: str = "",
    requested_depth: Optional[int] = None,
    effective_depth: Optional[int] = None,
) -> Dict[str, Any]:
    """The one shape `contract["refinement"]` takes, for every command.

    FIND and GRAPHWALK each invented their own. FIND wrapped the agent payload
    in `{"refinement": ..., "sample_size": ...}` while the executor read the
    hint off the wrapper, so FIND's hint arrived as None and never reached a
    planner prompt -- `tighten` appears zero times in 4,950 recorded renderings.
    One shape, and `sample_size` is a field in it rather than a wrapper around
    it, so that read cannot miss again.

    Everything here is a value the engine already computed. In particular the
    model's prose `refinement_reason` is NOT here: it is still produced and
    still recorded in `prompt_observations.jsonl` for offline audit, but it is
    not transmitted to the planner. A recorded sentence claimed "no matching
    edges exist" when what had happened was an empty result under a 60-row cap
    -- a bound turned into a proven negative, in a channel the planner cannot
    tell from an engine fact.

    `sample_size` and `caps` travel WITH the hint because a bare hint
    reintroduces the same failure one level up: `keep` formed on 60 rows and
    `keep` formed on 3 are different claims, and an empty pilot is a third.
    """
    record: Dict[str, Any] = {
        "hint": str(hint or ""),
        # False means no model answered. A judged `keep` and a failed call are
        # different facts and must not share an observable.
        "available": bool(available),
        "trigger": trigger,
        "sample_size": int(sample_size),
        # The bounds in force when the sample was formed. Without them a hint
        # about breadth is uninterpretable: "the sample looked narrow" says
        # nothing if the sample was narrow because the cap made it so.
        "caps": dict(caps),
    }
    if requested_depth is not None:
        record["requested_depth"] = int(requested_depth)
        # Always equal to `requested_depth` now that the adaptive narrowing is
        # deleted. Carried anyway, as a positive assertion that the walk ran at
        # the depth asked for rather than the silence that used to mean it.
        record["effective_depth"] = int(
            effective_depth if effective_depth is not None else requested_depth
        )
    return record


@dataclass
class SearchRefinementRequest:
    search_name: str
    prompt_builder: Callable[[list[Dict[str, Any]], int], str]
    row_iterator: Iterable[Dict[str, Any]]
    seed_text: str
    default_payload: Dict[str, Any]
    sample_limit: int = 20
    model: str | None = None
    reasoning_effort: str | None = None
    prompt_name: str | None = None
    prompt_logger: Any = None
    prompt_metadata: Optional[Dict[str, Any]] = None
    label_builder: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None


class LLMSearchRefinementAgent:
    """Use an LLM to inspect sampled output and recommend the next search move."""

    def __init__(self, llm_func, prompt_logger=None):
        self.llm_func = llm_func
        # Every refinement call is an LLM call that changes retrieval. Without a
        # logger it appears in no run record, so nobody -- including a reviewer
        # trying to measure how often it fails -- can see that it happened. The
        # corpus had 5,084 prompt observations and zero from this path.
        self.prompt_logger = prompt_logger

    def _llm_for_refinement(self, request: SearchRefinementRequest):
        if hasattr(self.llm_func, "clone"):
            current_model = getattr(self.llm_func, "model", "") or ""
            model = request.model or current_model
            reasoning_effort = request.reasoning_effort
            if not model and "mini" in current_model.lower():
                model = os.getenv("PROCESS_LARGE_MODEL", "gpt-5.5")
            return self.llm_func.clone(model=model, reasoning_effort=reasoning_effort)
        return self.llm_func

    def run_search_refinement(self, request: SearchRefinementRequest) -> Dict[str, Any]:
        initial_rows: list[Dict[str, Any]] = []
        for row in request.row_iterator:
            initial_rows.append(row)
            if len(initial_rows) >= request.sample_limit:
                break
        # The one sampler. `initial_rows` is already capped at `sample_limit`
        # by the loop above, so this is currently an identity -- which is
        # exactly what the deleted stratifier was silently doing while looking
        # like a tuning surface. Kept as a real call so that raising the cap
        # above the sample size starts sampling instead of starting to truncate.
        sampled_rows = deterministic_sample(
            initial_rows, seed_text=request.seed_text, k=request.sample_limit
        )
        prompt_text = request.prompt_builder(sampled_rows, len(sampled_rows))
        observation_id = None
        provider_succeeded = False
        try:
            llm = self._llm_for_refinement(request)
            if request.prompt_logger and request.prompt_name:
                observation_id = request.prompt_logger.record_invocation(
                    prompt_name=request.prompt_name,
                    prompt_text=prompt_text,
                    model=getattr(llm, "model", None),
                    metadata=request.prompt_metadata or {},
                )
            response = llm.call(prompt_text)
            provider_succeeded = True
            parsed = json.loads(self._extract_json(response))
            if request.prompt_logger and request.prompt_name and observation_id:
                request.prompt_logger.record_outcome(
                    observation_id,
                    prompt_name=request.prompt_name,
                    response_text=response,
                    parsed=parsed,
                    labels=request.label_builder(parsed) if request.label_builder else {},
                )
            return parsed
        except Exception:
            if request.prompt_logger and request.prompt_name and observation_id:
                request.prompt_logger.record_outcome(
                    observation_id,
                    prompt_name=request.prompt_name,
                    response_text=None,
                    parsed=request.default_payload,
                    labels={"parse_success": False},
                )
            # Which failure it was, recorded in the payload rather than only in
            # a logger that may be absent. A paid call that returned garbage and
            # a call that never reached the provider are different facts about
            # the run.
            failed = dict(request.default_payload)
            failed["refinement_unavailable_trigger"] = (
                TRIGGER_PARSE_ERROR if provider_succeeded else TRIGGER_PROVIDER_ERROR
            )
            return failed

    # KNOWN DEFECT IN THE QUESTION, NOT THE ANSWER -- left unfixed deliberately.
    #
    # Both prompts below ask whether a sample is "too broad". Breadth is a ratio
    # against a denominator, so this asks the model to perform a MEASUREMENT
    # with an instrument that cannot see the denominator: it is shown at most 20
    # rows and never how many exist. A model answering that question at all is
    # guessing, and the guess is what the engine used to act on.
    #
    # Not fixed here because changing the wording is a different prompt with a
    # different output distribution, which needs its own equivalence experiment
    # -- the same reason `refinement_reason` stays in the schema. The engine no
    # longer acts on the answer, so the defect is now bounded to a disclosure.
    # Supplying the denominator (the population size, which the caller knows) is
    # the obvious fix and belongs to whoever runs that experiment.
    def get_find_refinement(
        self,
        command_args: Dict[str, Any],
        row_iterator: Iterable[Dict[str, Any]],
    ) -> Dict[str, Any]:
        criteria = command_args.get("criteria", "")
        target = command_args.get("target", "nodes")
        return self.run_search_refinement(
            SearchRefinementRequest(
                search_name="find",
                row_iterator=row_iterator,
                seed_text=criteria,
                prompt_builder=lambda sampled_rows, sampled_count: f"""You are refining a FIND command strategy.

Command intent:
- target: {target}
- criteria: {criteria}

Observed output sample:
- sample_count: {sampled_count}
- sample_data: {self._format_sample_data(sampled_rows)}

Decide the next move based only on the sample:
1. keep current strategy if the sample already matches the requested semantics closely enough
2. tighten the strategy if the sample is too broad, weakly matched, or structurally off-target

Return strict JSON:
{{
  "refinement_hint": "keep|tighten",
  "refinement_reason": "short reason",
  "refinement_issues": ["optional issues"]
}}""",
                default_payload={
                    "refinement_hint": "keep",
                    "refinement_reason": "refinement agent unavailable",
                    "refinement_issues": [],
                    # A judged "keep" and a failed call must not be the same
                    # observable. The planner used to be told the model chose to
                    # keep the strategy when in fact no model ever answered.
                    "refinement_available": False,
                    "refinement_unavailable_trigger": TRIGGER_AGENT_UNAVAILABLE,
                },
                prompt_name="find_refinement",
                prompt_logger=self.prompt_logger,
            )
        )

    def get_graphwalk_refinement(
        self,
        args: Dict[str, Any],
        source_nodes: Any,
        row_iterator: Iterable[Dict[str, Any]],
        contract: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        from_variable = args.get("from_variable", "")
        relationship_types = args.get("relationship_types", "")
        depth = args.get("depth", "1")
        # Six fields are gone from this payload and from the prompt schema
        # below: three `*_strength` scores and three `*_hint` echoes. Every one
        # had zero production readers. The three echoes additionally restated
        # `payload_kind`, `grain_type` and `usable_by`, which the contract
        # already carries -- asking a model to repeat what the engine knows,
        # then storing the answer where nothing looks.
        #
        # `refinement_confidence` is gone too. It was compared against a
        # threshold by engine code, and an LLM-emitted number may be recorded as
        # a labelled self-report but never thresholded: doing so treats an
        # assertion as a measurement.
        default = {
            "refinement_hint": "keep",
            "refinement_reason": "graphwalk refinement agent unavailable",
            "refinement_available": False,
            "refinement_unavailable_trigger": TRIGGER_AGENT_UNAVAILABLE,
        }
        return self.run_search_refinement(
            SearchRefinementRequest(
                search_name="graphwalk",
                row_iterator=row_iterator,
                seed_text=f"{from_variable}:{relationship_types}:{depth}",
                prompt_builder=lambda sampled_rows, sampled_count: f"""You are refining a GRAPHWALK retrieval strategy.

Goal:
- walk from source variable '{from_variable}'
- follow relationship filter '{relationship_types}'
- depth {depth}

Source sample:
{self._format_path_sample(source_nodes)}

Walk result sample:
{self._format_path_sample(sampled_rows)}

Current contract:
{contract or {}}

Decide the next move based on the sample:
1. keep current depth/strategy if the sample is good enough
2. tighten depth/strategy if the sample is too broad or weakly anchored

Return strict JSON:
{{
  "refinement_hint": "keep|tighten_depth",
  "refinement_reason": "short reason"
}}""",
                default_payload=default,
                model=os.getenv("PATH_SEMANTICS_MODEL", "") or None,
                reasoning_effort=os.getenv("PATH_SEMANTICS_REASONING", "high"),
                prompt_name="graphwalk_refinement",
                prompt_logger=self.prompt_logger,
            )
        )

    @staticmethod
    def _format_sample_data(data: Any) -> str:
        if not data:
            return "No data"
        if isinstance(data, list):
            if len(data) == 0:
                return "Empty list"
            return f"List with {len(data)} items, sample: {data[:3]}"
        return str(data)

    @staticmethod
    def _format_path_sample(data: Any) -> str:
        if not data:
            return "No data"
        if isinstance(data, list):
            return json.dumps(data[:10], ensure_ascii=False, default=str)
        return json.dumps(data, ensure_ascii=False, default=str)

    @staticmethod
    def _extract_json(text: str) -> str:
        text = text.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            lines = lines[1:]
            if lines and lines[-1].strip().startswith("```"):
                lines = lines[:-1]
            text = "\n".join(lines).strip()
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end >= start:
            return text[start : end + 1]
        return text
