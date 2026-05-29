# Opening Fragment Implementation: Wegener, Tharp, and the GASL Bridge

This brief turns the approved opening storyline into a concrete implementation
plan for the first tutorial fragment only. It does not modify the shared demo
pipeline. All work remains inside `visualization/tutorial_mode/`.

## Objective

Teach the viewer, before any command-family explanation, that:

- science is popularly imagined as a Eureka moment and a bold declaration
- modern scientific acceptance usually depends on compilation and legibility
- GASL belongs to the compilation side of that story

The fragment should not argue this abstractly. It should make the viewer feel
the difference by watching one claim-first sequence and one compilation-first
sequence.

## Runtime target

- total length: 60-75 seconds
- pace: slower than the demo videos; every major text block readable without
  pausing
- no sound

## Scene grammar

The fragment should alternate among four visual modes:

1. **myth mode**
   - simple cartoon language
   - bright and immediate
   - centered composition

2. **claim mode**
   - assertive, sparse, high-contrast
   - one bold line of thought at a time
   - skeptical audience reaction shown clearly

3. **compilation mode**
   - layered, cumulative, slower
   - data strips, repeated passes, map assembly
   - increasing clarity over time

4. **bridge mode**
   - the human-story visual language morphs into the system-story visual
     language
   - no abrupt cut to generic software diagrams

## Shot list

### 00. Prologue: the popular myth of science
- duration: 8-10s
- visual:
  - cartoon Archimedes-style Eureka image
  - idea-bulb / bath / running-out proclamation silhouette
- on-screen text:
  - headline: `We like to imagine science as a breakthrough moment.`
  - body: `One person sees the truth, announces it, and the world changes.`
- purpose:
  - establish the audience's default picture before complicating it

### 01. Wegener makes the claim
- duration: 12-14s
- visual:
  - real portrait of Alfred Wegener
  - cut to a stylized lecture scene
  - continent/puzzle-fit motif flashes behind him
- motion:
  - his claim arrives quickly and elegantly
  - the hall reacts with stylized ridicule: tossed tomatoes or ink-blot
    dismissals, dismissive gestures, skeptical faces
- on-screen text:
  - headline: `Wegener could state the pattern.`
  - body: `The idea was bold. But a bold idea is not yet an evidence structure
    others can inspect.`
- purpose:
  - make the claim-first mode emotionally legible

### 02. Why the claim does not land
- duration: 8-10s
- visual:
  - the single elegant continent-fit image remains on one side
  - around it, observations stay scattered and unassembled
- motion:
  - the central idea stays crisp, but the surrounding evidence never coheres
- on-screen text:
  - headline: `A compelling claim can still remain arguable.`
  - body: `Without organized support, the field still sees room to dismiss it.`
- purpose:
  - show that the problem is not "wrong idea" but "insufficient compiled
    legibility"

### 03. Tharp begins the compilation work
- duration: 14-18s
- visual:
  - real portrait/photo of Marie Tharp
  - drafting table / desk
  - sounding profiles, earthquake strips, hand-drawn contour layers
- motion:
  - traces accumulate in passes
  - overlays align
  - the map becomes clearer with each pass
- on-screen text:
  - headline: `Tharp changed the argument by changing the evidence.`
  - body: `She did not make the claim louder. She made the hidden structure
    more legible.`
- purpose:
  - establish compilation mode as patient, visual, cumulative work

### 04. Pattern becomes difficult to ignore
- duration: 10-12s
- visual:
  - assembled bathymetric structure or ridge-like map emerges from the previous
    strips
  - the earlier scattered traces are now clearly part of one structure
- motion:
  - clarity increases
  - annotations settle
  - the image stabilizes
- on-screen text:
  - headline: `Acceptance changes when the structure becomes visible.`
  - body: `Compilation turns many arguable traces into one inspectable form.`
- purpose:
  - make the legibility shift visible before introducing GASL

### 05. Bridge into systems
- duration: 10-12s
- visual:
  - the compiled map morphs into graph evidence bins / rows / answer-view tiles
  - one-shot LLM answer flashes briefly as the "claim-first" analogue
  - then the compiled evidence view replaces it
- on-screen text:
  - headline: `GASL exists to move AI answers from claim-like to science-like.`
  - body: `Not by making the model louder, but by making the evidence compiled,
    checkable, and legible before the answer is spoken.`
- purpose:
  - bridge the human story into the system story without mixing them too early

## Asset plan

### Real-image assets
- Alfred Wegener portrait/photo
- Marie Tharp portrait/photo
- optional archival texture/backgrounds for lecture hall and drafting table

Prefer public-domain or permissively licensed archival imagery so the fragment
is shareable.

### Generated / illustrated assets
- Archimedes-style Eureka cartoon
- stylized ridicule audience tableau
- contour-strip / sounding-profile paper elements
- morph frames from compiled map into GASL evidence shapes

These should be generated or illustrated so the fragment can exaggerate action
cleanly without pretending to be historical footage.

## Motion plan

### Claim-side motion
- faster timing
- fewer layers
- centered subject
- sudden declarative text reveals
- ridicule arrives as a quick punctuation mark

### Compilation-side motion
- slower timing
- more layers
- repeated passes
- progress visible through accumulation, not through one "aha" reveal
- every overlay should leave the scene more structured than before

## Text rules

- text should stay in fixed-width boxes
- each major beat gets one headline and one short body block
- no full-paragraph captions
- no command names yet in the opening, except the final bridge if absolutely
  necessary

## Technical implementation

1. create still-plate assets first
   - portraits
   - eureka cartoon
   - ridicule scene
   - desk/collation scene
   - compiled-map scene
   - GASL bridge scene

2. animate the fragment in the tutorial compositor
   - pan/zoom/parallax on still plates
   - layered reveal masks for traces and contours
   - morph transition into the system bridge

3. render one opening fragment only
   - review pacing and readability
   - adjust before touching other fragments

## Why this fragment matters

If this opening works, later command-family chapters no longer feel arbitrary.
They become the specific ways GASL performs evidence compilation:

- access commands gather traces
- assembly commands align heterogeneous evidence
- compilation commands make structure visible
- answer views preserve that structure long enough for final synthesis
