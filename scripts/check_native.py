#!/usr/bin/env python3
"""Check native Codex installation in a fresh GitHub Actions runner, without a model call."""
import argparse
import asyncio
import json
import os
import platform
import shutil
import sqlite3
import subprocess
import tempfile
import zipfile
from pathlib import Path

from package_release import build

ROOT = Path(__file__).resolve().parents[1]


async def check(codex_js, work):
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise RuntimeError("This native-host check is intended for a fresh GitHub Actions runner")
    config_root = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
    if (config_root / "config.toml").exists() or (config_root / "auth.json").exists():
        raise RuntimeError("Refusing to test against an existing Codex configuration or account")
    command_prefix = [shutil.which("node") or "node", str(codex_js.resolve())]
    archive = work / "release.zip"
    package = build(archive)
    with zipfile.ZipFile(archive) as bundle:
        bundle.extractall(work / "workspace Пример with spaces")
    root = work / "workspace Пример with spaces/arv"
    database = work / "тестовый граф.sqlite3"
    marketplace = "arv-ci"
    plugin_id = "assumption-research-verification@" + marketplace
    catalogue = root / ".agents/plugins/marketplace.json"
    data = json.loads(catalogue.read_text(encoding="utf-8"))
    data["name"] = marketplace
    catalogue.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    server_env = {"ARV_DB": str(database)}
    for key in ("UV_CACHE_DIR", "UV_PYTHON_INSTALL_DIR"):
        if os.environ.get(key):
            server_env[key] = os.environ[key]
    for filename in ("mcp.json", ".mcp.json"):
        path = root / filename
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["mcpServers"]["arv"]["env"] = server_env
        path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    commands = []

    def cli(name, arguments):
        result = subprocess.run(command_prefix + arguments, cwd=root, capture_output=True,
                                text=True, encoding="utf-8", errors="replace")
        (work / (name + ".stdout")).write_text(result.stdout, encoding="utf-8")
        (work / (name + ".stderr")).write_text(result.stderr, encoding="utf-8")
        commands.append(dict(name=name, exit_code=result.returncode))
        if result.returncode:
            raise RuntimeError(f"{name}: {result.stderr}")
        return json.loads(result.stdout)

    process = None
    try:
        cli("marketplace-add", ["plugin", "marketplace", "add", str(root), "--json"])
        installed = cli("plugin-add", ["plugin", "add", plugin_id, "--json"])
        installed_root = Path(installed["installedPath"])
        if (installed_root / ".venv").exists():
            raise RuntimeError("Native install unexpectedly contains a prebuilt environment")
        with (work / "app-server.stderr").open("w", encoding="utf-8") as errors:
            process = await asyncio.create_subprocess_exec(*command_prefix, "-c", "features.apps=false", "app-server",
                         cwd=installed_root, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=errors)
            sequence = 0

            async def rpc(method, params):
                nonlocal sequence
                sequence += 1
                request_id = sequence
                process.stdin.write((json.dumps(dict(id=request_id, method=method, params=params)) + "\n").encode("utf-8"))
                await process.stdin.drain()
                while True:
                    line = await asyncio.wait_for(process.stdout.readline(), 45)
                    if not line:
                        raise RuntimeError(f"Codex closed during {method}")
                    response = json.loads(line)
                    if response.get("id") == request_id and "method" not in response:
                        if "error" in response:
                            raise RuntimeError(f"{method}: {response['error']}")
                        return response["result"]
                    if "id" in response and "method" in response:
                        process.stdin.write((json.dumps(dict(id=response["id"], error=dict(code=-32601, message="No interactive actions in CI"))) + "\n").encode("utf-8"))
                        await process.stdin.drain()

            await rpc("initialize", dict(clientInfo=dict(name="arv_portability_check", version="1"), capabilities=dict(experimentalApi=True)))
            process.stdin.write(b'{"method":"initialized"}\n')
            await process.stdin.drain()
            started = await rpc("thread/start", dict(cwd=str(installed_root), ephemeral=True))
            thread_id = started["thread"]["id"]
            for attempt in range(30):
                inventory = await rpc("mcpServerStatus/list", dict(threadId=thread_id))
                servers = [item for item in inventory["data"] if item.get("pluginId") == plugin_id]
                if len(servers) == 1 and servers[0].get("runtimeStatus") == "connected" and "arv_begin" in servers[0]["tools"]:
                    break
                await asyncio.sleep(1)
            (work / "inventory.json").write_text(json.dumps(servers, indent=2) + "\n", encoding="utf-8")
            if len(servers) != 1 or servers[0].get("runtimeStatus") != "connected":
                raise RuntimeError("Installed native MCP did not connect")
            server = servers[0]

            async def tool(name, **arguments):
                result = await rpc("mcpServer/tool/call", dict(threadId=thread_id, server=server["name"], tool=name, arguments=arguments))
                if result.get("isError"):
                    raise RuntimeError(f"{name}: {result['content']}")
                return result.get("structuredContent") or json.loads(result["content"][0]["text"])

            research = await tool("arv_begin", goal="Native cross-platform check", scope="synthetic:ci", request_key="native-ci")
            if not database.is_file():
                raise RuntimeError("MCP did not select the explicitly configured graph")
            passage = "Наблюдение — 北极星"
            fact = await tool("arv_observe", research_id=research["id"], content=passage, source_uri="synthetic://native-ci",
                              origin_id="native-ci", locator="role/1", scope="synthetic:ci")
            claim = await tool("arv_hypothesize", research_id=research["id"], subject="Synthetic recording", predicate="has",
                               object="recurring pulse", rationale="Pattern inference", based_on=[fact["id"]])
            await tool("arv_finish", research_id=research["id"], summary="A recurring pulse is plausible.", selected_claim_ids=[claim["id"]])
            model = await tool("arv_model", research_id=research["id"])
            if claim["id"] not in model["suggested_claim_ids"]:
                raise RuntimeError("Native tool result lost the selected claim")
            with sqlite3.connect(database) as connection:
                saved = connection.execute("SELECT data FROM nodes WHERE id=?", (fact["id"],)).fetchone()
                if json.loads(saved[0])["content"] != passage:
                    raise RuntimeError("Native SQLite effect differs from the tool result")
            receipt = dict(status="passed", os=platform.system(), machine=platform.machine(), archive=package,
                           native_tools=sorted(server["tools"]), explicit_graph_path=True, multilingual_sqlite=True,
                           no_model_call=True, commands=commands)
            (work / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
            print(json.dumps(receipt, indent=2))
    finally:
        if process is not None and process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), 10)
            except TimeoutError:
                process.kill()
                await process.wait()
        # This helper refuses existing user state and runs only in an ephemeral CI runner.
        # Failed jobs still retain logs; runner teardown owns all temporary installation data.


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex-js", type=Path, required=True, help="Installed @openai/codex/bin/codex.js")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = args.output.resolve() if args.output else Path(tempfile.mkdtemp(prefix="arv native Пример "))
    if args.output:
        output.mkdir(parents=True, exist_ok=False)
    asyncio.run(check(args.codex_js, output))


if __name__ == "__main__":
    main()
