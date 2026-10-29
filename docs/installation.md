# Installation

## Requirements

- `uv` on the PATH seen by your desktop app or terminal.
- Python 3.13, installed automatically by `uv sync` when needed.
- Windows, macOS or Linux, with a local Codex execution environment for the bundled plugin.
- Internet access for the first dependency installation. Subsequent MCP launches
  use `--frozen --offline`; ARV itself makes no network source requests.

Install uv using its [official instructions](https://docs.astral.sh/uv/getting-started/installation/).
Use PowerShell on Windows or a terminal on macOS/Linux. No Bash script or
platform-specific virtual-environment activation is required.
Extract the release archive, enter its `arv` directory, then run:

```sh
uv sync --frozen
uv run --frozen --offline python examples/quickstart/run.py
```

Keep the extracted repository in a stable location. There are no developer-machine
paths or required private source services in this package.

## Codex plugin

From the repository root:

```sh
codex plugin marketplace add .
codex plugin list --marketplace arv-public --available --json
codex plugin add assumption-research-verification@arv-public
```

If your CLI does not provide `plugin add`, use the desktop Plugins Directory:
restart the app after adding the marketplace, select ARV and install its plugin.
Start a new local chat, invoke `$assumption-research-verification` and provide
your question and authorised sources. Source connections remain separately authorised.

The catalogue name is `arv-public`; the plugin name is
`assumption-research-verification`. This package does not replace an existing
`arv-local` installation. Enable only the intended version in a research chat
to avoid presenting two copies of the same tools to the agent.

To use the Git distribution, register the repository instead of the local `.`:

```sh
codex plugin marketplace add raven-ai-esh/arv
codex plugin add assumption-research-verification@arv-public
```

The first `uv sync --frozen` is still required to prepare the locked runtime.
See the [official marketplace guide](https://developers.openai.com/plugins/build/plugins#add-a-marketplace-from-the-cli).

## Other MCP hosts

Use the host's stdio configuration with `uv` as the command and these arguments,
replacing `/absolute/path/to/arv` with your extracted folder:

```json
{
  "command": "uv",
  "args": ["run", "--frozen", "--offline", "--project", "/absolute/path/to/arv", "python", "/absolute/path/to/arv/scripts/arv.py"],
  "env": {"ARV_DB": "/absolute/path/to/private/project-graph.sqlite3"}
}
```

Supply the method in `skills/assumption-research-verification/SKILL.md` to the
agent, or read the MCP resource `arv://method`. This is a configuration recipe;
individual third-party host compatibility is unverified.

## Data

Default graph location:

- macOS: `~/Library/Application Support/assumption-research-verification/graph.sqlite3`
- Linux: `~/.local/share/assumption-research-verification/graph.sqlite3`
- Windows: `%LOCALAPPDATA%\assumption-research-verification\graph.sqlite3`
  (fallback: `~\AppData\Local\assumption-research-verification\graph.sqlite3`).

Explicit `ARV_DB`, `ARV_DATA_DIR` and `XDG_DATA_HOME` overrides retain their
precedence on all three platforms. Version 0.4.1 preserves the existing macOS and
Linux default locations. On Windows, an older 0.4.0 graph may be under
`~\.local\share\assumption-research-verification\graph.sqlite3`; point `ARV_DB`
at that file to continue it. The update does not move or delete an old graph.

Set `ARV_DB` to an explicit file, or `ARV_DATA_DIR` to a separate directory, for
project isolation. Declare it in the server's MCP `env` configuration: hosts may
filter variables exported only in the parent application's environment. For the
bundled plugin, add `env` to the `arv` entry in `mcp.json` and `.mcp.json` before
installation. Verify the selected file with a synthetic record first.
The file contains source passages, inferences and history.
Keep it outside a public repository. Back up a closed graph before migration.

The database is single-user local storage. Actor/research bindings do not make
it a multi-user security boundary. Removing the plugin does not remove the graph.
The synthetic demo always sets a separate `ARV_DB` for its own subprocesses.

## Troubleshooting

| Symptom | Action |
| --- | --- |
| `uv` not found | Install uv and ensure the app can see it on PATH; restart the app after changing PATH |
| Offline dependency error | Run `uv sync --frozen` from this repository with network access, then retry |
| Marketplace is absent | Run `marketplace add` from the extracted repository root; inspect the list output |
| Duplicate ARV tools | Enable one intended ARV installation for that chat |
| An existing experiment uses historical tools | It may be bound with `ARV_RESEARCH`; historical investigations retain their own method |

If uv uses a custom cache or Python-install directory, declare `UV_CACHE_DIR` or
`UV_PYTHON_INSTALL_DIR` in the server's `env` too; the host may filter them from
its parent process. The [CI workflow](https://github.com/raven-ai-esh/arv/actions/workflows/ci.yml)
distinguishes native CLI/MCP checks from desktop GUI or OpenAI-directory publication.
