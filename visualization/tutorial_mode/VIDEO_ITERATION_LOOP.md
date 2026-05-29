# Tutorial Video Iteration Loop

This workspace needs a durable review loop because "looks good" is not a
reliable quality-control test for symbolic instructional shots. The objective is
to preserve, for each iteration:

- the exact input assets and prompts
- the generated video outputs
- reviewer comments
- the distilled shot invariants that future iterations must satisfy
- the next actions that follow from those comments

## Why this exists

The failure mode is not just weak visuals. It is strategic drift:

- a shot can be aesthetically coherent but semantically wrong
- a generated clip can be visually rich but fail to teach the principle
- review comments often contain the real design constraints that the model did
  not infer on its own

So the loop must not only save "what was generated." It must save "what the
shot was supposed to prove."

## Core unit: a review record

Each iteration should produce a single JSON record with:

- `scene_id`
- `iteration_id`
- `goal`
- `inputs`
  - still plates
  - prompts
  - generator model and settings
- `outputs`
  - raw clips
  - stitched review clip
- `review_comments`
  - raw reviewer notes
- `self_critique`
  - what the system now believes is wrong
- `shot_invariants`
  - non-negotiable semantic conditions for the next pass
- `next_actions`
  - concrete generation / compositing changes
- `principle_sentence`
  - one sentence saying what the shot must teach
- `review_passes`
  - pass/fail on semantic, physical, style, overlay, and readability checks
- `error_origin`
  - where the failure originates
- `chosen_fix_strategy`
  - why the next fix is the right kind of fix

## Review rules

1. Do not approve a shot because it looks cinematic.
2. Ask first whether the physical or symbolic principle is visible.
3. Distill every good piece of feedback into one or more `shot_invariants`.
4. Keep raw reviewer comments; do not overwrite them with a paraphrase only.
5. Every new generation should cite the last iteration it is responding to.
6. Every review must use the editable protocol in `SHOT_REVIEW_PROTOCOL.md`.
7. The fill-in schema lives at `review_archive/review_protocol_template.json`.

## Shot invariants

These are the hard constraints that define whether a shot teaches its intended
principle. Examples:

- Archimedes shot:
  - crown enters water
  - displacement is visible
  - overflow is visible
  - insight follows from the physical effect

- Wegener ridicule shot:
  - claim is public and legible
  - ridicule is directed at the speaker
  - projectile paths obey the scene geometry
  - speaker remains the target and anchor

- Tharp compilation shot:
  - evidence becomes more organized over time
  - multiple compilation beats are visible
  - the shot reads as collation, not generic desk work

## Process

1. Generate rough still plates.
2. Generate rough motion clips.
3. Create a stitched review clip.
4. Run the protocol review passes.
5. Archive the review and comments.
6. Distill shot invariants.
7. Produce the next pass from those invariants, not from vague aesthetic memory.

## Storage

Review records live under:

- `visualization/tutorial_mode/review_archive/`

Suggested filenames:

- `YYYYMMDD_scene_slug_iteration.json`

The current opening-fragment trial should be stored there first so future work
starts with a concrete example.
