Aggregate Repair Phase
======================

Purpose
-------

This phase starts after planner-prompt tuning has been checkpointed and archived.
The goal is to collect **new traces only** and tune an aggregate-repair prompt
against those traces without contaminating the next dataset with planner-era data.

Working files
-------------

- `tmp/prompt_lab_cases.jsonl`
- `tmp/seeded_candidates.jsonl`
- `tmp/verifications.jsonl`
- `tmp/accepted_repairs.jsonl`
- `tmp/prompt_dataset.json`

These are reset when archiving the previous phase snapshot.

Prompt surface
--------------

The aggregate repair prompt lives at:

- `prompts/aggregate_repair.txt`

It should be optimized only against traces generated *after* the planner phase archive.

Archive
-------

Use:

```bash
.venv/bin/python tools/prompt_lab/archive_prompt_phase.py \
  --repo-root . \
  --phase-name planner_to_aggregate
```

This moves the current prompt-lab working files into a timestamped archive and
recreates clean working files in `tmp/`.
