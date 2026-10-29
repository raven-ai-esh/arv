"""Real stdio transport and SQLite preserve multilingual text and paths."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class UnicodeIOTests(unittest.IsolatedAsyncioTestCase):
    async def test_method_and_persisted_observation_are_utf8(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        with tempfile.TemporaryDirectory(prefix="arv workspace Пример ") as temporary:
            env = {key: value for key, value in os.environ.items() if not key.startswith("ARV_")}
            env["ARV_DB"] = str(Path(temporary) / "граф.sqlite3")
            params = StdioServerParameters(command=sys.executable, args=[str(ROOT / "scripts/arv.py")], env=env)

            async def call(session, name, **arguments):
                result = await session.call_tool(name, arguments)
                self.assertFalse(result.isError, result.content)
                return result.structuredContent or json.loads(result.content[0].text)

            passage = "Наблюдение — 北极星"
            async with stdio_client(params) as (reader, writer):
                async with ClientSession(reader, writer) as session:
                    await session.initialize()
                    method = await session.read_resource("arv://method")
                    expected = (ROOT / "skills/assumption-research-verification/SKILL.md").read_bytes().decode("utf-8")
                    self.assertEqual(method.contents[0].text, expected)
                    research = await call(session, "arv_begin", goal="Multilingual source", scope="synthetic:utf8", request_key="utf8")
                    observation = await call(session, "arv_observe", research_id=research["id"], content=passage,
                                             source_uri="synthetic://utf8", origin_id="utf8", locator="строка/1", scope="synthetic:utf8")
            async with stdio_client(params) as (reader, writer):
                async with ClientSession(reader, writer) as session:
                    await session.initialize()
                    graph = await call(session, "arv_inspect", research_id=research["id"], view="graph", focus_id=observation["id"])
                    saved = next(node for node in graph["nodes"] if node["id"] == observation["id"])
                    self.assertEqual(saved["content"], passage)
                    self.assertEqual(saved["locator"], "строка/1")


if __name__ == "__main__":
    unittest.main()
