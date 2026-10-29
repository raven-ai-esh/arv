# Contributing

Start with the synthetic demo and the method description. Keep source provenance,
contradictions and the distinction between observation and inference intact.

```sh
uv sync --frozen
uv run --frozen --offline python -m unittest discover -s tests -v
```

For a behaviour change, add a regression case that fails before the fix. Exercise
the real stdio boundary when tool schemas, launch configuration or persistence
change. Use fictional fixtures and a separate temporary database.

Run the packaged acceptance journey locally with:

```sh
uv run --frozen --offline python scripts/check_release.py
```

It installs dependencies into a fresh cache, runs the demo twice, checks refusal
of an existing output and runs all tests from an archive path containing spaces
and non-ASCII characters. It needs network access for that fresh installation.
CI repeats this on Windows, Linux and macOS, then checks a native Codex plugin
installation in a fresh runner. No model call or model API key is used.

Include the problem, changed behaviour and executed checks in a contribution.
Do not upload private source exports, personal graphs, access tokens or private incident logs.
