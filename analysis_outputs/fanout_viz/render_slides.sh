#!/usr/bin/env bash
# Render every slide of the fan-out deck to a PNG, one image per run per slide.
#
# Chromium under snap confinement cannot read /tmp, so the page is staged in a
# directory under $HOME and the images are written back beside this script.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
out="$here/slides"
stage="$HOME/fanout_render_stage"

runs=(
  "amr_mic_incremental"
  "quake_v22_learning"
  "quake_v25_relaxed"
  "quake_v17_continue"
  "quake_argo_v01"
  "quake_v15"
)
slides=("1_tree" "2_funnel" "3_verdict")

mkdir -p "$out" "$stage"
cp "$here/index.html" "$here/data.js" "$stage/"

for r in "${!runs[@]}"; do
  for s in "${!slides[@]}"; do
    for theme in light dark; do
      q=""; [ "$theme" = dark ] && q="?theme=dark"
      name="$out/${runs[$r]}__${slides[$s]}__${theme}.png"
      chromium --headless --disable-gpu --no-sandbox --hide-scrollbars \
        --force-device-scale-factor=2 --window-size=1600,900 \
        --virtual-time-budget=15000 \
        --screenshot="$name" \
        "file://$stage/index.html${q}#export/${r}/${s}" 2>/dev/null
      echo "  $(basename "$name")"
    done
  done
done

rm -rf "$stage"
echo "$(ls "$out" | wc -l) images in $out"
