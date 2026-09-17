# Rollout fan-out deck

Three slide readings of the nested acquisition-episode tree recorded by six of
the longest-standing runs in `question_runs/`.

**The slides are the PNGs in `slides/`** — 1600x900 at 2x, one image per run per
slide per theme, viewable directly on GitHub. Names read
`<run>__<slide>__<theme>.png`, so `quake_v22_learning__1_tree__light.png` is the
tree slide for `earthquake_firecrawl_live_20260904_v22_learning`.

`index.html` is the same deck as an interactive page, with a run selector and
hover detail on every band. It loads `data.js` from the same directory, so keep
the two together and open them from disk — GitHub shows the HTML as source text.

These files are force-added past the `/analysis_outputs/` rule in `.gitignore`
so the deck can be shared through the repo. The directory as a whole is still
untracked — add nothing else here without the same deliberate `git add -f`.

## The slides

1. **Tree** — an icicle of the real episode nesting,
   `run → strategy → search → page → {lexical probe | table query} → chunk`.
   Band width is the work underneath, so the uneven widths are the stop rule's
   doing rather than a fixed batch size. Grey bands are pages dropped before
   extraction.
2. **Funnel** — provider hits → pages walked → chunks read → pages that
   yielded → attributions, with per-search yield and a Pareto curve against an
   even-spread reference.
3. **Verdict** — the per-page controller trace: observed distinct results and
   estimated remaining on one log axis, with search boundaries marked. The
   curve resets at each boundary because saturation is judged per scope.

## Re-rendering the slides

    ./render_slides.sh

Drives headless Chromium over `index.html#export/<run>/<slide>` — a mode that
hides the chrome and fixes the stage at 1600x900 — and writes every combination
into `slides/`. The page is staged under `$HOME` first because Chromium here is
a snap and cannot read `/tmp` or dotted directories.

## Rebuilding the data

Run from the repository root, against whichever runs you want in the deck:

    .venv/bin/python analysis_outputs/fanout_viz/extract_tree.py <run> [<run> ...]
    .venv/bin/python analysis_outputs/fanout_viz/build_payload.py
    .venv/bin/python analysis_outputs/fanout_viz/build_data_js.py

`extract_tree.py` writes one tree per run under `data/`, `build_payload.py`
reduces them to `payload.json`, and `build_data_js.py` emits the `data.js` the
page loads. The intermediates are large and regenerable, so only `data.js` is
tracked; edit the run list at the bottom of `build_payload.py` to change which
runs appear in the selector.

## What the sources carry

Every figure comes from two artifacts each run already writes:
`answers/acquisition_page_detail.jsonl` (one record per page unit, in
processing order, carrying the estimator snapshot and controller verdict taken
after that unit) and the `checkpoint_state/*/frontier.json` records (search
queries, provider hit counts, accepted source IDs).

Episode records carry no timestamps and no cost fields, so the deck has no
time or spend axis — volume and yield are what the artifacts actually record.

Two gaps worth knowing when reading the slides:

- `earthquake_firecrawl_live_20260901_v15` has no surviving frontier
  checkpoints, so its searches show as task IDs rather than query strings.
- `earthquake_firecrawl_argo_20260913_v01` mints 78,503 chunk credits, of which
  62,986 come from a single page. That total is visible in the icicle tooltips
  and deliberately kept out of the headline tiles, where it would swamp the
  cross-run comparison.
