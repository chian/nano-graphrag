# Shot Review Protocol

This protocol exists to improve shot review by separating:

- **what the shot must teach**
- **what the shot actually shows**
- **where the failure originates**
- **what kind of fix is appropriate**

It is deliberately editable. The goal is to refine it over time using review
feedback, especially where the user is acting as the labeler of semantic
correctness.

## 0. Principle lock

Before reviewing a shot, write one sentence for the intended principle:

- `What must the viewer understand because of this shot?`

Examples:
- Archimedes: `Insight follows from visible displacement and overflow.`
- Wegener: `A strong public claim can still attract ridicule and fail to persuade.`
- Tharp: `Compilation makes structure visible through cumulative alignment.`

If the principle sentence is unclear, do not review the shot yet.

## 1. Required review artifacts

Every review must include:

1. the stitched review clip
2. a contact sheet or keyframe strip
3. the intended principle sentence
4. a filled review record

## 2. Review passes

Each shot must pass through these review passes in order.

### A. Principle / semantic pass

Question:
- Does the shot actually communicate the intended principle?

Failure examples:
- nice-looking motion but wrong symbol
- atmosphere instead of argument
- a reaction without the causal cue that motivates it

### B. Physical / causal pass

Question:
- Do the motions obey the basic causal logic the shot depends on?

Failure examples:
- overflow without brim contact
- projectiles traveling toward the camera when they are meant to hit a speaker
- cause and effect reversed

### C. Style coherence pass

Question:
- Do all visual layers feel like they belong to the same visual regime?

Failure examples:
- comic overlays on painterly base
- high-fidelity scene with deliberately crude graphics
- different line weights or rendering languages fighting each other

### D. Overlay integration pass

Question:
- Are text boxes, bubbles, arrows, and other overlays integrated rather than pasted on?

Failure examples:
- bubble tails not anchored to mouths
- poor reading order
- overlays covering the key action
- overlay treatment incompatible with base art

### E. Readability / timing pass

Question:
- Can a viewer read and understand the shot without pausing?

Failure examples:
- action and text compete for attention
- key motion is too fast to notice
- the sequence creates visual uncertainty rather than clarity

## 3. Diagnose error origin

If a shot fails, identify where the error originates:

- `base_art`
- `motion`
- `overlay`
- `transition`
- `tool_limit`
- `sequence_context`

This matters because the fix should target the source, not just the symptom.

## 4. Fix-selection rules

### Rule 1: Principle-first scenes

If the scene exists to teach a principle or mechanism:

- prefer simplification over richness
- prefer designed action over generative ambiguity
- if the base and overlay disagree, **stylize the base down**

### Rule 2: Atmosphere-first scenes

If the scene exists mainly to set mood or context:

- richer base art is acceptable
- overlays should harmonize with the base rather than dominate it
- if the base and overlay disagree, **stylize overlays up** or reduce them

### Rule 3: Tool limit escalation

If the model fails a principle-critical mechanic twice:

- stop asking the model to invent the mechanic
- switch to authored/composited action

### Rule 4: Speech-bubble layout

If using bubbles:

- tails should anchor near the speaking mouth line
- bubble order should follow reading order
- bubbles should not obscure the principal action
- bubble styling must match the scene's broader visual regime

## 5. Review outcome

Each shot must end with one of these outcomes:

- `approve`
- `revise_local`
- `switch_strategy`
- `needs_user_label`

`needs_user_label` should be used sparingly, only when the visual ambiguity
cannot be resolved internally from the protocol and existing feedback.

## 6. What to archive

Each iteration archive should preserve:

- raw reviewer comments
- the principle sentence
- pass/fail on all five review passes
- error origin
- chosen fix strategy
- resulting action items

This protocol should be refined whenever a reviewer identifies a failure that
the current passes did not surface.
