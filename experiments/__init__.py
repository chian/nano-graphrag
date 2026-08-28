"""Diagnostic scaffolding for the control-layer build.

`experiments/` imports the pipeline. The pipeline never imports `experiments/`.
That one-way dependency is what makes teardown a deletion rather than a merge.
"""
