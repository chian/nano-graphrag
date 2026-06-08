# AGENTS

This file is for repository-local agent instructions. It is not end-user
documentation.

## Validation labels

Do not say a change is "fixed" unless all four are true:

1. coded
2. focused-tested
3. committed
4. corpus-validated

Use those labels explicitly in status updates.

## Demo safety

For visualization demo work in this repo, use the exact safe launcher and do not improvise:

- Use `./launch_demo_viz_safe.sh` only.
- Do not run `launch_viz.sh` or `python -m visualization.examples.demo` directly unless the user explicitly overrides the demo-safe path.
- The safe launcher precomputes and serves a single engineering-controls subset graph at `.viz_cache/graphs/haiqu_engineering_controls_topdeg1500.graphml`.
- Do not disable or bypass the subset path for demo launches.
- If a demo-safe visualization restart is requested, restart via the safe launcher instead of changing graphs in place.

## Video generation

Use only long-form cinematic pipelines as final video makers.

- Curated final demos:
  - single demo: `visualization/scripts/record_demo.sh <demo-id> ...`
  - batch demos: `visualization/scripts/render_demo_batch.py`, `visualization/scripts/render_paper_style_batch.py`, `visualization/scripts/render_symbolism_shortlist_batch.py`
- On-demand final demos from committed artifacts:
  - `visualization/scripts/render_cinematic_demo.py <run_id> <qid> --graph-path ... --target-seconds 90`
- Low-level capture tools:
  - `visualization/scripts/record_viewer_url.sh` is a capture tool, not a final demo maker.
- Any artifact run without `answer_views` is not a demo maker and must fail instead of producing a static/non-cinematic video.
- If a committed replay video already exists under `benchmark_results/<run_id>/captures/`, prefer that asset over re-recording.
- If the request is for the “same video as before”, verify the exact source asset or final cinematic pipeline first instead of assuming a generic replay URL recreates the previous choreography.

## Stable corpus run procedure

In this environment, use this exact detached launch method unless the repo
itself changes in a way that invalidates it. Choose transport explicitly with
`--transport direct` or `--transport shim`; do not rely on shell env:

```bash
run_id=corpus_YYYYMMDD_view_balanced_72
mkdir -p benchmark_results/$run_id
setsid .venv/bin/python visualization/scripts/run_trace_corpus.py \
  --transport shim \
  --per-graph 18 \
  --question-file visualization/question_sets/haiqu_view_balanced_18_per_graph.json \
  --run-id "$run_id" \
  > benchmark_results/$run_id/runner.log 2>&1 < /dev/null &
echo $! > benchmark_results/$run_id/worker.pid
```

Do not invent alternate wrappers once this has been proven in-session.

## Evo-devo graph build procedure

Evo-devo graph construction uses the existing typed-corpus builder. Do not
create or restore an evo-devo-specific graph builder, and do not hard-code
evo-devo paths in code:

```bash
corpus_dir=data/evo_devo_corpus
out_dir=evo_devo_graphs/v1
log=$out_dir/build_direct.log
pidfile=$out_dir/build_direct.pid
mkdir -p "$out_dir"

groups=()
for metadata in "$corpus_dir"/*/metadata.json; do
  group=$(basename "$(dirname "$metadata")")
  state="$out_dir/$group/${group}_state.json"
  if ! jq -e '.completed == true' "$state" >/dev/null 2>&1; then
    groups+=("$group")
  fi
done

groups_json=$(printf '%s\n' "${groups[@]}" | jq -R . | jq -s .)
EVO_DEVO_GROUPS="$groups_json" .venv/bin/python - <<'PY'
import json
import os
import subprocess
from pathlib import Path

groups = json.loads(os.environ["EVO_DEVO_GROUPS"])
log_path = Path("evo_devo_graphs/v1/build_direct.log")
pid_path = Path("evo_devo_graphs/v1/build_direct.pid")
cmd = [
    ".venv/bin/python",
    "-u",
    "build_haiqu_graphs.py",
    "--corpus-dir",
    "data/evo_devo_corpus",
    "--output-dir",
    "evo_devo_graphs/v1",
    "--groups",
    *groups,
    "--model",
    "gpt55",
    "--transport",
    "direct",
    "--chunk-size",
    "1200",
    "--overlap",
    "100",
    "--paper-concurrency",
    "20",
    "--chunk-concurrency",
    "200",
    "--completion-threshold",
    "0.9",
    "--straggler-idle-sec",
    "900",
]
env = os.environ.copy()
env["NANOGRAPHRAG_LLM_TRANSPORT"] = "direct"
with log_path.open("wb") as log_file:
    proc = subprocess.Popen(
        cmd,
        cwd=Path.cwd(),
        stdin=subprocess.DEVNULL,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        env=env,
        close_fds=True,
        start_new_session=True,
    )
pid_path.write_text(f"{proc.pid}\n", encoding="utf-8")
print(f"pid={proc.pid}")
print(f"log={log_path}")
print(f"pidfile={pid_path}")
PY
```

For this repo on macOS, `setsid` is not available and shell-launched
`nohup ... &` did not leave a live graph-build process. Use Python
`subprocess.Popen(..., start_new_session=True)` for detached graph builds.
Keep `-u` so progress reaches the log immediately. After launch, verify the
PID in `build_direct.pid` is a live `build_haiqu_graphs.py` process and that
`build_direct.log` has passed import/startup.

## First-run validation

Before trusting a fresh corpus run, verify q001 has all of these:

- OpenAI `200 OK` on the first planner call
- `planner_prompt`
- `planner_response`
- `planner_plan`
- at least one `command_result`

Check these artifacts line by line:

- `benchmark_results/<run_id>/q001/gasl_artifacts/traces/q001.jsonl`
- `benchmark_results/<run_id>/q001/gasl_artifacts/prompt_observations.jsonl`
- `benchmark_results/<run_id>/q001/gasl_state.json`

If the worker is dead, `runner.log` is empty, or q001 stops before
`planner_response`, the run is invalid. Fix the launch method first. Do not
debug GASL from an invalid run.

## Runtime workflow checklist

For a healthy GASL run, the trace should show:

- planner prompt emitted
- planner response emitted
- planner plan parsed
- command start/result for each executed step
- command-local repair response for commands that return `error` or `empty`
- iteration failure summary when an iteration completes with defects
- plan-iteration prompt/response when iteration-level defects remain after
  command-local repair
- produced artifacts recorded when commands materialize reusable state
- final answer response emitted

## Analysis rule

For every analysis, separate outcomes from interpretation.

Use a compact table or equivalent structure with:

- outcome
- what it means
- interpretation

Also mark whether each observed outcome is:

- in scope for the tested mechanism
- out of scope for the tested mechanism

Do not treat out-of-scope defects as evidence against the target mechanism.

## Directory discipline

Before creating, using, or writing into any existing directory in this repo:

- Read every file already present in that directory first.
- Do not infer the directory's purpose from its name alone.
- Do not repurpose an existing directory unless its contents confirm the intended use.
- If the directory's purpose is unclear after reading all files already in it, create a new neutral directory instead.
- In status updates before writing files, state which directory will be used and what existing-file evidence justified that choice.
