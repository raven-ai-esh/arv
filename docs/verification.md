# Verification scope

The [CI workflow](https://github.com/raven-ai-esh/arv/actions/workflows/ci.yml)
runs on Windows, Ubuntu Linux and macOS with Python 3.13 and uv 0.9.27. Its native
host check uses Codex CLI 0.153.2. The linked run records establish actual pass or
failure status for each revision.

Each OS job exercises:

- A fresh release archive in a path containing spaces and non-ASCII characters.
- Dependency installation with an initially empty cache.
- Real stdio MCP calls, SQLite persistence and method-resource UTF-8 integrity.
- Two demo runs and refusal of an existing output without changing its graph.
- Working-model, provenance, contradiction, reviewer-access and historical-isolation tests.
- Native Codex catalogue registration, plugin installation and server loading.
- Native observe/hypothesise/finish calls, an explicit graph path and multilingual
  SQLite output. This check uses an empty CI account with no model call.
- Exact archive membership, per-file hashes and deterministic ZIP generation.

The 0.4.0 preparation was additionally reviewed independently on macOS. Version
0.4.1 preserves the research skill and graph algorithm; its runtime changes are
Windows default data location and explicit text encoding.

These checks cover the server and native CLI integration. Desktop GUI installation,
individual third-party MCP hosts and publication in OpenAI's directory remain
UNVERIFIED. A scripted demonstration does not establish autonomous-agent reasoning
quality, customer usefulness, comparative advantage, model cost or latency.

The historical `scripts/review.py` launcher is a separate integration with source
bindings and model authentication. The CI reviewer-access checks exercise the MCP
interface, not that launcher's account-dependent workflow.
