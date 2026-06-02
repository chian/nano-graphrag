# Enzyme GASL Demo Storyboard

## Scope

This storyboard is the first reviewable asset for the two enzyme queries:

1. Substrate scope and validation mode for `verA`, `vanA`, and `gdmA`
2. Potential assay confounds from native `VanB` (`UniProt O05617`) cross-reactivity

## Slide 1

Title: `Rieske O-demethylases: one family, three substrate stories`

Story:
- Open on the three oxygenase anchors: `verA`, `vanA`, `gdmA`
- Show that the graph groups them under a Rieske oxygenase frame, but the substrate evidence is distributed across in vitro activity, in vivo growth, and homolog-comparison contexts
- The claim is not just “what do these enzymes hit?” but “how was each substrate relationship established?”

Visual:
- Left: enzyme trio
- Center: substrate branches
- Right: validation badges (`in vitro`, `in vivo`, `both`)

Key evidence to cite:
- `SWGDMAB IN VITRO-IN VIVO MISMATCH EVIDENCE`
- `PURIFIED GDMA-GDMB IN VITRO ASSAY`
- `NATIVE UNTAGGED VANA-VANB COEXPRESSION IN E. COLI BL21 STAR (DE3)`
- `VANB PARTNER REDUCTASE SEQUENCE (UNIPROTKB O05617)`

## Slide 2

Title: `Where the graph weakens: normalized enzyme names hide the anchors`

Story:
- The raw GASL trace misses `verA/vanA/gdmA` as exact node anchors because the graph stores more normalized names like `VANA RIESKE MONOOXYGENASE ASSIGNMENT`
- This is a graph usability issue, not a biology issue
- The cinematic version should therefore use the graph neighborhoods as evidence, but a hand-shaped replay for the anchors

Visual:
- Left: raw GASL trace finding empty anchor searches
- Right: manual neighborhood recovery around VanA / GdmA evidence nodes

## Slide 3

Title: `Assay confounds: native VanB can rescue the wrong oxygenase`

Story:
- The host retains native `VanB (O05617)`
- In the homolog-screening assay, some oxygenase/reductase readings can be confounded because the native reductase can stand in for the intended `vanB` homolog
- The slide should focus on the difference between “enzyme works with its paired reductase” and “enzyme appears to work because the host already supplies a compatible reductase”

Visual:
- Central electron-transfer chain
- Native `O05617` highlighted as a competing reductase source
- Confounded assay pairs called out in red

Key evidence to cite:
- `VANB PARTNER REDUCTASE SEQUENCE (UNIPROTKB O05617)`
- `GDMB AND VANB PHYLOGENETIC CLUSTERING EVIDENCE`
- `SWGDMAB IN VITRO-IN VIVO MISMATCH EVIDENCE`

## Slide 4

Title: `Conclusion: tell the story through evidence mode, not just topology`

Story:
- The graph is strongest when it links enzyme -> substrate -> evidence mode
- The slide close should emphasize the distinction between:
  - in vitro biochemical support
  - in vivo host-behavior support
  - assay confounds due to electron-partner promiscuity

Deliverable direction:
- Build the final deck from hand-shaped cinematic frames plus exact evidence callouts
- Do not use the raw q001 replay as the hero asset
