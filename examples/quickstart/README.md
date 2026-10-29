# Technical quickstart: synthetic observations

All recordings, lengths and calibration records are invented. The script drives the actual stdio
MCP server with fixed calls and checks persistence, source identity, conventions
and dependent-claim revision. It does not run an autonomous agent or demonstrate
an advantage over another research workflow.

```sh
uv sync --frozen
uv run --frozen --offline python examples/quickstart/run.py
```

Each run creates a new folder under `.arv-demo/`. An explicit `--output` must name
a new directory; existing paths are refused. The script always supplies a separate
ARV_DB and does not open a personal research graph.

The two recording roots strengthen one candidate signal interpretation. Repeated
copies retain their roots. A task-specific unit convention interprets a raw rod length; a calibration record
then changes that interpretation and invalidates its dependent fit conclusion. These conventions belong only
to this fixture.

Inspect `walkthrough.md`, `snapshots.json`, `model.json`, `trace.json` and the
synthetic SQLite file in the output directory. Comparative usefulness requires
separate evaluation; storage assertions alone do not establish it.
