# ARV — research with an evidence graph

[![CI](https://github.com/raven-ai-esh/arv/actions/workflows/ci.yml/badge.svg)](https://github.com/raven-ai-esh/arv/actions/workflows/ci.yml)

[Русский](README.ru.md)

ARV (Assumption–Research–Verification) helps an AI agent build a working picture
from incomplete data and keep the grounds behind its conclusions inspectable.
It bundles a research skill with a local MCP server and a persistent SQLite graph.

The agent reads sources, proposes hypotheses and judges their meaning. ARV stores
the source trail, combines distinct grounds and revisits dependent conclusions
when a premise changes.

```text
Observation → hypothesis → new grounds or counterfacts → revised working model
```

## Technical quickstart

Targets Windows, macOS and Linux with Python 3.13 and
[uv](https://docs.astral.sh/uv/getting-started/installation/).
Use PowerShell on Windows or your terminal on macOS/Linux; the commands are the same.
Run these commands from the extracted repository folder. The first command
downloads Python 3.13 if needed and installs the locked dependencies.

```sh
uv sync --frozen
uv run --frozen --offline python examples/quickstart/run.py
```

No external source account or model API key is needed for the quickstart. It drives
the actual stdio MCP server with scripted calls and writes a new, separate demo
graph on every run. It does not exercise autonomous model reasoning.

| What happens | What you can inspect |
| --- | --- |
| Two synthetic recordings suggest a shared signal | One hypothesis gains a second distinct observation |
| The same record is copied and summarised | Its observation count stays at two |
| A task convention interprets a raw unit as centimetres | The rule remains visible as an assumption |
| A calibration record supplies a different scale | The old length and its dependent conclusion lose support |
| The server restarts | The revised working model and history remain available |

This fixture checks software behaviour, not comparative research quality.
The command prints the output folder. Open its `walkthrough.md`, `snapshots.json`,
`model.json` and `trace.json`. See [the example and agent prompt](examples/quickstart/README.md).

## Use with Codex

The repository includes a local plugin marketplace, portable `plugin.json` and
`mcp.json`, plus the Codex compatibility manifests. Run `uv sync --frozen` first;
the MCP launch uses cached dependencies in offline mode.

```sh
codex plugin marketplace add .
codex plugin add assumption-research-verification@arv-public
```

Alternatively, open the desktop Plugins Directory, select the ARV marketplace
and install the plugin there. Start a new local chat and invoke
`$assumption-research-verification` with your question and authorised sources.
See [installation, data location and troubleshooting](docs/installation.md).

## What ARV adds

- Observations retain source identity, locator, date and scope.
- Hypotheses can accumulate new grounds and preserve actual counterfacts.
- Copies, derived summaries and repeated inference paths share their original roots.
- User conventions and ordinary domain defaults remain distinguishable from facts.
- Revisions retain history; new material data reopens a saved conclusion.
- Equivalent meanings can be reused or merged explicitly by the agent.

Support is ordinal bookkeeping, not a calibrated probability. The agent still
judges source quality, semantic identity and which explanation makes sense.
ARV does not certify factual truth or guarantee better answers than a plain agent.
See [the method and its limits](docs/method.md).

## Data and access

The graph server runs locally and has no source adapters, model credentials or
telemetry. Source access comes from the host's separately authorised tools.
Source passages sent to ARV are stored in its graph. A connected AI host may
process tool calls and results under that host's own data policies.

The SQLite file is single-user storage, not a tenant isolation boundary. Use a
separate graph when a project needs separate data. [Details](docs/installation.md#data).

## Development

```sh
uv run --frozen --offline python -m unittest discover -s tests -v
uv run --frozen --offline python scripts/package_release.py
```

The release builder uses an explicit file list and excludes databases, dependency
environments and generated demo output. [Contributing](CONTRIBUTING.md) ·
[Changes](CHANGELOG.md) · [Verification scope](docs/verification.md) ·
[Release preparation](docs/release-plan.md).

ARV 0.4.2 is distributed under the [MIT licence](LICENSE).
[Source and releases](https://github.com/raven-ai-esh/arv).
