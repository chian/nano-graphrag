"""
Archived reference for the former single-pass planner path.

This file is intentionally not imported by the live runtime. It preserves the
previous executor-side plan generation branch in case a historical comparison is
needed without keeping two active planner modes in the main execution path.
"""

ARCHIVED_SINGLE_PHASE_PLANNER_PATH = """
plan_prompt = self.llm_func.create_plan_prompt(query, schema, current_state, history)
plan_obs_id = self.prompt_obs.record_invocation(
    prompt_name="plan_generation",
    prompt_text=plan_prompt,
    model=getattr(self.llm_func, "model", None),
    metadata={
        "iteration": iteration,
        "query": query,
        "history_len": len(history),
        "state_var_count": len(current_state.get("variables", {})),
    },
)
self.trace.log("planner_prompt", {
    "iteration": iteration,
    "query": query,
    "prompt": plan_prompt,
    "schema": schema,
    "state": current_state.get("variables", {}),
    "history": history,
})
plan_response = self.llm_func.call(plan_prompt)
self.trace.log("planner_response", {
    "iteration": iteration,
    "raw_response": plan_response,
    "extracted_json": _extract_json(plan_response),
})
plan_json = json.loads(_extract_json(plan_response))
"""
