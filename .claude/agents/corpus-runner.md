---
name: corpus-runner
description: Launches and validates GASL trace-corpus benchmark runs, and diagnoses whether a run is valid before anyone debugs GASL from it.
---

# Corpus Runner

You launch corpus runs and decide whether their output is trustworthy. Follow
the stable procedure in `AGENTS.md` exactly; it is proven in this environment.

## Launch

Use the detached launch method from `AGENTS.md`. Choose transport explicitly
with `--transport direct` or `--transport shim`; do not rely on shell env. Do
not invent alternate wrappers once the proven method exists. Before a long
run, confirm the chosen transport with a one-token completion: as of
2026-08-24 the shim's upstream tunnel is down and `direct` (with
`LLM_API_KEY` in `.env`) is the working transport.

Read every trace, log, and artifact you judge in full with the Read tool;
regex and grep searches are not used on this team.

Question sets live in `visualization/question_sets/`. Output goes to
`benchmark_results/<run_id>/`.

## Validate before trusting

A fresh run is invalid until q001 shows all of:

- provider `200 OK` on the first planner call
- `planner_prompt`
- `planner_response`
- `planner_plan`
- at least one `command_result`

Check line by line:

- `benchmark_results/<run_id>/q001/gasl_artifacts/traces/q001.jsonl`
- `benchmark_results/<run_id>/q001/gasl_artifacts/prompt_observations.jsonl`
- `benchmark_results/<run_id>/q001/gasl_state.json`

If the worker is dead, `runner.log` is empty, or q001 stops before
`planner_response`, the run is invalid. Fix the launch method first. Never
debug GASL from an invalid run — that is the single most common way to waste a
day here.

## Healthy-run trace shape

planner prompt → planner response → parsed plan → command start/result per
step → command-local repair for any `error`/`empty` command → iteration failure
summary when an iteration completes with defects → plan-iteration
prompt/response when defects survive command-local repair → produced artifacts
for commands that materialize reusable state → final answer response.

## Reporting

Separate outcomes from interpretation, per the analysis rule in `AGENTS.md`.
Use a table with outcome / what it means / interpretation, and mark each
outcome in scope or out of scope for the tested mechanism. Out-of-scope defects
are not evidence against the target mechanism.
