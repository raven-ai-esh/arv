"""Execute the complete new workflow through the real stdio MCP and SQLite."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"src"))


class WorkingMCPTests(unittest.IsolatedAsyncioTestCase):
    async def test_new_default_accumulation_convention_finish_restart_and_review(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        with tempfile.TemporaryDirectory() as tmp:
            env = {k:v for k,v in os.environ.items() if not k.startswith("ARV_")}
            env.update(ARV_DB=str(Path(tmp)/"graph.sqlite3"))
            params = StdioServerParameters(command=sys.executable, args=[str(ROOT/"scripts/arv.py")], env=env)
            async def call(s, name, args):
                r = await s.call_tool(name, args)
                self.assertFalse(r.isError, r.content)
                return r.structuredContent or json.loads(r.content[0].text)
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as s:
                    await s.initialize()
                    names = {t.name for t in (await s.list_tools()).tools}
                    self.assertTrue({"arv_assume","arv_merge","arv_model"} <= names)
                    self.assertFalse({"arv_contract","arv_freeze","arv_challenge"} & names)
                    resource = await s.read_resource("arv://method")
                    self.assertIn("working", resource.contents[0].text.lower())
                    r = await call(s,"arv_begin",dict(goal="Understand the dataset",scope="dataset",request_key="new"))
                    self.assertEqual(r["method"],"working_model")
                    rid = r["id"]
                    facts = []
                    for who, description in [("A","Channel A records a recurring pulse"),("B","Channel B records the recurring pulse")]:
                        facts.append(await call(s,"arv_observe",dict(research_id=rid,content=description,source_uri="fixture://observations",origin_id="observations",locator=who,scope="dataset")))
                    args = dict(research_id=rid,subject="Dataset",predicate="has",object="Signal cluster",rationale="The readings suggest a shared signal")
                    a = await call(s,"arv_hypothesize",{**args,"based_on":[facts[0]["id"]]})
                    b = await call(s,"arv_hypothesize",{**args,"based_on":[facts[1]["id"]]})
                    self.assertEqual(a["id"],b["id"])
                    self.assertGreater(b["plausibility"]["support"],a["plausibility"]["support"])
                    rule = await call(s,"arv_assume",dict(research_id=rid,statement="Interpret U as centimetres",kind="user_rule",reason="User convention",strength="strong"))
                    success = await call(s,"arv_observe",dict(research_id=rid,content="R-7 raw length is 7 U",source_uri="fixture://observations",origin_id="observations",locator="R-7/raw",scope="dataset"))
                    length = await call(s,"arv_hypothesize",dict(research_id=rid,subject="R-7",predicate="length_cm",object="7",rationale="Apply convention",based_on=[success["id"],rule["id"]]))
                    self.assertEqual(length["plausibility"]["band"],"by_convention")
                    result = await call(s,"arv_finish",dict(research_id=rid,summary="Signal cluster and provisional 7 cm length",selected_claim_ids=[b["id"],length["id"]]))
                    self.assertEqual(result["conclusion"]["completion_state"],"working_model")
            # A new process sees exactly the persisted working model, not a fallback.
            params.env.update(ARV_RESEARCH=rid,ARV_ROLE="reviewer",ARV_ACTOR="independent-reviewer")
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as s:
                    await s.initialize()
                    names = {t.name for t in (await s.list_tools()).tools}
                    self.assertEqual(names,{"arv_model","arv_inspect","arv_review"})
                    model = await call(s,"arv_model",dict(research_id=rid))
                    self.assertEqual(model["research"]["status"],"concluded")
                    note = await call(s,"arv_review",dict(research_id=rid,verdict="reasonable",explanation="Recording inference and unit convention are coherent"))
                    self.assertEqual(note["actor"],"independent-reviewer")
                    self.assertEqual((await call(s,"arv_model",dict(research_id=rid)))["research"]["status"],"concluded")
                    self.assertTrue((await s.call_tool("arv_begin",dict(goal="x",scope="x",request_key="x"))).isError)

    async def test_default_process_can_read_but_not_reinterpret_historical_research(self):
        from arv.store import Store
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"graph.sqlite3"
            old=Store(path).begin("Historical goal","old","old")
            env={k:v for k,v in os.environ.items() if not k.startswith("ARV_")};env['ARV_DB']=str(path)
            params=StdioServerParameters(command=sys.executable,args=[str(ROOT/'scripts/arv.py')],env=env)
            async with stdio_client(params) as (read,write):
                async with ClientSession(read,write) as s:
                    await s.initialize()
                    r=await s.call_tool('arv_inspect',dict(research_id=old['id'],view='graph'))
                    self.assertFalse(r.isError)
                    r=await s.call_tool('arv_assume',dict(research_id=old['id'],statement='Change method',kind='user_rule',reason='Forbidden'))
                    self.assertTrue(r.isError)
                    self.assertEqual(Store(path).inspect(old['id'])['research']['stop_protocol'],1)


if __name__ == '__main__':
    unittest.main()
