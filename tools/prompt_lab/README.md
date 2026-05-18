Prompt Lab
==========

Offline, reusable prompt-repair tooling. This is intentionally outside the main runtime.

Workflow
--------

1. Collect standardized prompt cases from any `prompt_observations.jsonl` files:

   `python tools/prompt_lab/collect_prompt_cases.py --root benchmark_results --out tmp/cases.jsonl`

2. Generate repair candidates with a template:

   `python tools/prompt_lab/generate_repair_candidates.py --cases tmp/cases.jsonl --template-file my_repair_prompt.txt --out tmp/candidates.jsonl`

   Or bootstrap positives directly from existing successful prompt outcomes:

   `python tools/prompt_lab/seed_candidates_from_cases.py --cases tmp/cases.jsonl --only-positive --out tmp/seeded_candidates.jsonl`

3. Verify candidates with an external verifier:

   `python tools/prompt_lab/verify_repair_candidates.py --cases tmp/cases.jsonl --candidates tmp/candidates.jsonl --verifier-cmd 'python my_verifier.py --case {case_path} --candidate {candidate_path}' --out tmp/verifications.jsonl`

   Repo-specific verifier for this codebase:

   `python tools/prompt_lab/verify_repair_candidates.py --cases tmp/cases.jsonl --candidates tmp/seeded_candidates.jsonl --verifier-cmd '.venv/bin/python tools/prompt_lab/verifiers/nano_graphrag_verifier.py --case {case_path} --candidate {candidate_path}' --out tmp/verifications.jsonl --accepted-repairs-out tmp/accepted_repairs.jsonl`

   Notes:
   - verification rows are appended incrementally and flushed after each candidate
   - `accepted_repairs.jsonl` stores the high-value cases where the original prompt output failed verification but a repaired candidate passed

4. Build a reusable labeled dataset:

   `python tools/prompt_lab/build_labeled_prompt_dataset.py --cases tmp/cases.jsonl --candidates tmp/candidates.jsonl --verifications tmp/verifications.jsonl --out tmp/prompt_dataset.json`

Verifier contract
-----------------

The external verifier command must print JSON to stdout:

```json
{
  "pass": true,
  "score": 0.91,
  "labels": {"variable_flow_valid": true},
  "notes": "why this candidate passed or failed"
}
```

Design notes
------------

- Generic across systems: the verifier is external and system-specific.
- Generic across prompts: the repair generator only needs standardized cases plus a template.
- Defaults to the direct OpenAI path by clearing `NANOGRAPHRAG_LLM_TRANSPORT` in the candidate generator.
