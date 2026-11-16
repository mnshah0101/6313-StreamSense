# Environment checkpoint

The stage 1 CPU environment is defined by `pyproject.toml`, `.python-version`, and
`uv.lock`. Run `uv sync --locked`; see the root README for optional dependency sets.
PACE module activation and scratch-cache setup are delivered in stage 7.
