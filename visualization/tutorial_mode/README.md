# Tutorial Mode Workspace

This directory is intentionally separate from the shared demo/viewer pipeline.

Purpose:
- build an instructional GASL walkthrough
- preserve the existing cinematic demos untouched
- allow tutorial-specific overlays, timing, and rendering without modifying
  `visualization/templates/viewer.html` or `visualization/demo_catalog.py`

Copied starting points:
- `tutorial_viewer.html`
- `tutorial_demo_catalog.py`
- `render_tutorial_demo.sh`

Next step:
- implement the instructional walkthrough only inside this workspace
