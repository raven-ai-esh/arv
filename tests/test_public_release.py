"""Distribution acceptance at the file, real MCP and persistent data boundaries."""
import hashlib
import importlib.util
import json
import os
import re
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


class PublicReleaseTests(unittest.TestCase):
    def test_archive_allowlist_excludes_local_graph_env_and_private_artifacts(self):
        package = module("package_release", ROOT / "scripts/package_release.py")
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            first, second = folder / "first.zip", folder / "second.zip"
            package.build(first)
            package.build(second)
            self.assertEqual(first.read_bytes(), second.read_bytes(), "Archive must be reproducible")
            with self.assertRaises(FileExistsError):
                package.build(first)
            with zipfile.ZipFile(first) as archive:
                names = set(archive.namelist())
                expected = {"arv/" + name for name in package.PUBLIC_FILES} | {"arv/SHA256SUMS"}
                self.assertEqual(names, expected)
                for name in names:
                    self.assertFalse(any(part in name.split("/") for part in ("artifacts", ".venv", "validation", ".arv-demo")))
                    self.assertFalse(name.endswith((".sqlite3", ".db", ".env", ".pyc")))
                    data = archive.read(name)
                    pattern = rb"/" + rb"Users/[^\s/]+|(?:ghp_|glpat-)[A-Za-z0-9_-]{15,}|sk-[A-Za-z0-9_-]{24,}"
                    self.assertNotRegex(data, pattern)
                lines = archive.read("arv/SHA256SUMS").decode().splitlines()
                self.assertEqual(len(lines), len(package.PUBLIC_FILES))
                for line in lines:
                    digest, name = line.split("  ", 1)
                    self.assertEqual(digest, hashlib.sha256(archive.read("arv/" + name)).hexdigest())

    def test_packaged_skill_links_and_manifest_assets_exist(self):
        for filename in ("plugin.json", ".codex-plugin/plugin.json"):
            manifest = json.loads((ROOT / filename).read_text(encoding="utf-8"))
            interface = manifest.get("extensions", {}).get("com.openai", manifest)["interface"]
            for key in ("logo", "composerIcon"):
                self.assertTrue((ROOT / interface[key]).is_file())
        portable = json.loads((ROOT / "plugin.json").read_text(encoding="utf-8"))
        compat = json.loads((ROOT / ".codex-plugin/plugin.json").read_text(encoding="utf-8"))
        for key in ("name", "version", "description", "license"):
            self.assertEqual(portable[key], compat[key])
        for path in (ROOT / "skills").rglob("*.md"):
            for target in re.findall(r"\]\(([^)]+)\)", path.read_text(encoding="utf-8")):
                if ":" not in target and not target.startswith("#"):
                    self.assertTrue((path.parent / target).is_file(), f"Missing skill reference: {target}")


class PublicDemoTests(unittest.IsolatedAsyncioTestCase):
    async def test_scripted_demo_revises_and_persists_the_real_graph(self):
        demo = module("quickstart_demo", ROOT / "examples/quickstart/run.py")
        with tempfile.TemporaryDirectory() as tmp:
            result = await demo.run_demo(Path(tmp))
            self.assertEqual(result["status"], "passed")
            snapshots = json.loads((Path(tmp) / "snapshots.json").read_text(encoding="utf-8"))
            self.assertEqual([item["step"] for item in snapshots],
                             ["one_record", "two_records", "copy_and_summary", "initial_conclusion", "counterfact_reopens_model", "restart"])
            final = json.loads((Path(tmp) / "model.json").read_text(encoding="utf-8"))
            selected = {claim["id"]: claim for claim in final["claims"] if claim["id"] in final["suggested_claim_ids"]}
            self.assertEqual({claim["object"] for claim in selected.values()}, {"a signal cluster", "14"})
            self.assertEqual(final["research"]["conclusion"]["completion_state"], "working_model")
            self.assertTrue((Path(tmp) / "graph.sqlite3").is_file())

    async def test_compatibility_manifest_launches_from_its_package_root(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        with tempfile.TemporaryDirectory() as tmp:
            config = json.loads((ROOT / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]["arv"]
            env = {k: v for k, v in os.environ.items() if not k.startswith("ARV_")}
            env["ARV_DB"] = str(Path(tmp) / "graph.sqlite3")
            params = StdioServerParameters(command=config["command"], args=config["args"], cwd=str(ROOT), env=env)
            async with stdio_client(params) as (reader, writer):
                async with ClientSession(reader, writer) as session:
                    await session.initialize()
                    result = await session.call_tool("arv_begin", dict(goal="Portable launch", scope="synthetic", request_key="compat"))
                    self.assertFalse(result.isError, result.content)
            self.assertTrue((Path(tmp) / "graph.sqlite3").exists())


if __name__ == "__main__":
    unittest.main()
