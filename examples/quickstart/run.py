#!/usr/bin/env python3
"""A synthetic, scripted demonstration through the actual packaged MCP launch."""
import argparse
import asyncio
import json
import os
import tempfile
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[2]


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def parameters(root, db_path):
    """Resolve the public portable manifest; never use a host's existing graph."""
    config = json.loads((root / "mcp.json").read_text(encoding="utf-8"))["mcpServers"]["arv"]
    require(config["type"] == "stdio", "Demo requires a stdio server")
    expand = lambda value: value.replace("${PLUGIN_ROOT}", str(root))
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("ARV_") and k not in {"OPENAI_API_KEY", "CODEX_API_KEY"}}
    env["ARV_DB"] = str(db_path.resolve())
    return StdioServerParameters(command=config["command"],
                                 args=[expand(v) for v in config["args"]],
                                 cwd=expand(config["cwd"]), env=env)


async def tool(session, name, **arguments):
    result = await session.call_tool(name, arguments)
    require(not result.isError, f"{name} failed: {result.content}")
    if result.structuredContent is not None:
        return result.structuredContent
    return json.loads(result.content[0].text)


async def run_demo(output, root=ROOT):
    dataset = json.loads((root / "examples/quickstart/data.json").read_text(encoding="utf-8"))
    require(dataset.get("synthetic") is True, "Use only the bundled synthetic dataset")
    facts = {item["key"]: item for item in dataset["observations"]}
    params = parameters(root, output / "graph.sqlite3")
    snapshots = []

    async with stdio_client(params) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            names = {t.name for t in (await session.list_tools()).tools}
            require({"arv_begin", "arv_observe", "arv_hypothesize", "arv_model"} <= names,
                    "Working-model tools are unavailable")
            method = await session.read_resource("arv://method")
            require("working model" in method.contents[0].text.lower(), "Method resource is unavailable")
            research = await tool(session, "arv_begin", goal="Understand the synthetic recording and record R-7",
                                  scope=dataset["scope"], request_key="synthetic-quickstart")
            rid = research["id"]
            base = dict(research_id=rid)

            async def observe(key):
                record = facts[key]
                return await tool(session, "arv_observe", **base, content=record["content"],
                                  source_uri="synthetic://quickstart/data.json", origin_id=record["origin_id"],
                                  locator=record["locator"], scope=dataset["scope"], valid_at=record["valid_at"])

            first = await observe("channels:A")
            hypothesis = dict(**base, subject=dataset["dataset"], predicate="has", object="a signal cluster",
                              rationale="The distinct recordings suggest a shared signal; its physical cause remains open")
            cluster = await tool(session, "arv_hypothesize", **hypothesis, based_on=[first["id"]])
            snapshots.append(dict(step="one_record", claim=cluster))
            second = await observe("channels:B")
            reinforced = await tool(session, "arv_hypothesize", **hypothesis, based_on=[second["id"]])
            require(reinforced["id"] == cluster["id"], "Equivalent wording created a second claim")
            require(reinforced["plausibility"]["observation_count"] == 2, "Distinct roots were not accumulated")
            require(reinforced["plausibility"]["support"] > cluster["plausibility"]["support"],
                    "The new ground did not strengthen the hypothesis")
            snapshots.append(dict(step="two_records", claim=reinforced))

            copied = await tool(session, "arv_observe", **base, content=first["content"],
                                source_uri="synthetic://quickstart/copied-export", origin_id=first["origin_id"],
                                locator=first["locator"], scope=dataset["scope"], valid_at=first["valid_at"])
            require(copied["id"] == first["id"], "A copied record gained a new observation identity")
            derived = await tool(session, "arv_observe", **base, content="The first recording suggests a shared signal",
                                 source_uri="synthetic://quickstart/summary", origin_id="synthetic-summary",
                                 locator="paragraph/1", scope=dataset["scope"], source_kind="derived",
                                 derived_from=[first["id"]])
            deduplicated = await tool(session, "arv_hypothesize", **hypothesis,
                                      based_on=[copied["id"], derived["id"]])
            require(deduplicated["plausibility"]["support"] == reinforced["plausibility"]["support"],
                    "A copy or retelling inflated support")
            require(deduplicated["plausibility"]["observation_count"] == 2, "Repeated roots were counted twice")
            snapshots.append(dict(step="copy_and_summary", claim=deduplicated))

            rule = await tool(session, "arv_assume", **base, statement=dataset["demo_rule"], kind="user_rule",
                              reason="User-supplied interpretation of a synthetic unit", strength="strong")
            raw = await observe("rod:raw")
            length = await tool(session, "arv_hypothesize", **base, subject="R-7", predicate="length_cm", object="7",
                                rationale="Apply the initial unit convention", based_on=[raw["id"], rule["id"]])
            require(length["plausibility"]["band"] == "by_convention", "The unit convention was presented as direct evidence")
            fits = await tool(session, "arv_hypothesize", **base, subject="R-7", predicate="fits", object="10 cm slot",
                              rationale="Depends on the interpreted length", based_on=[length["id"]])
            await tool(session, "arv_finish", **base, summary="A recurring signal and a provisional length interpretation",
                       selected_claim_ids=[cluster["id"], length["id"], fits["id"]])
            snapshots.append(dict(step="initial_conclusion", model=await tool(session, "arv_model", **base)))
            counter = await observe("rod:calibrated")
            changed = await tool(session, "arv_assess", **base, claim_id=length["id"], basis_ids=[counter["id"]],
                                 effect="oppose", strength="strong", reason="The documented scale contradicts the provisional length",
                                 expected_revision=length["revision"])
            current = await tool(session, "arv_model", **base)
            require(current["research"]["status"] == "active" and current["research"]["conclusion"] is None,
                    "Material counterevidence failed to reopen the conclusion")
            require(length["id"] not in current["suggested_claim_ids"], "Old length remained selected")
            require(fits["id"] not in current["suggested_claim_ids"], "Dependent fit conclusion survived")
            require(changed["plausibility"]["balance"] < 0, "Calibration did not oppose the interpretation")
            snapshots.append(dict(step="counterfact_reopens_model", model=current))
            corrected = await tool(session, "arv_hypothesize", **base, subject="R-7", predicate="length_cm", object="14",
                                   rationale="Apply the documented scale", based_on=[counter["id"]], strength="strong")
            await tool(session, "arv_finish", **base, summary="The recordings suggest a recurring signal. Calibrated R-7 length is 14 cm.",
                       selected_claim_ids=[cluster["id"], corrected["id"]], open_questions=["What produces the recurring signal?"])
            before_restart = await tool(session, "arv_model", **base)

    # New process, same isolated SQLite graph, real stdio handshake.
    async with stdio_client(params) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            persisted = await tool(session, "arv_model", research_id=rid)
            require(persisted == before_restart, "Restart changed the saved model")
            trace = await tool(session, "arv_inspect", research_id=rid, view="trace", limit=100)
            while trace["events_next_offset"] is not None:
                page = await tool(session, "arv_inspect", research_id=rid, view="trace", limit=100,
                                  offset=trace["events_next_offset"])
                trace["events"].extend(page["events"])
                trace["events_next_offset"] = page["events_next_offset"]
            require(any(item["operation"] == "working_assess" for item in trace["events"]),
                    "The contradiction assessment is absent from history")
    snapshots.append(dict(step="restart", model=persisted))
    for filename, value in [("snapshots.json", snapshots), ("model.json", persisted), ("trace.json", trace)]:
        (output / filename).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output / "walkthrough.md").write_text(
        "# ARV synthetic demo\n\n"
        "Scripted calls through the real packaged MCP server and an isolated SQLite graph.\n\n"
        "| Step | Observed result |\n| --- | --- |\n"
        "| First synthetic recording | One observation supports an inferred signal cluster |\n"
        "| Second independent recording | The same claim has two distinct observations and stronger support |\n"
        "| Copy and derived summary | Two original observations; no extra support from repetition |\n"
        "| Raw length plus initial unit convention | A 7 cm interpretation is labelled convention-based |\n"
        "| Calibration supplies a different scale | Old length and dependent fit conclusion are excluded |\n"
        "| Revised conclusion and restart | Recurring-signal hypothesis and calibrated 14 cm length persist |\n\n"
        "Inspect snapshots.json, model.json and trace.json for the grounds and history.\n\n"
        "This verifies software behaviour; autonomous reasoning and comparative usefulness are unmeasured.\n",
        encoding="utf-8"
    )
    return dict(status="passed", research_id=rid, output=str(output.resolve()),
                checks=["manifest_launch", "method_resource", "distinct_grounds", "copy_deduplication",
                        "explicit_convention", "counterfact", "dependent_revision", "restart_persistence"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="New output directory; existing paths are refused")
    args = parser.parse_args()
    if args.output:
        output = args.output.resolve()
        output.mkdir(parents=True, exist_ok=False)
    else:
        parent = ROOT / ".arv-demo"
        parent.mkdir(exist_ok=True)
        output = Path(tempfile.mkdtemp(prefix="run-", dir=parent))
    print(json.dumps(asyncio.run(run_demo(output)), indent=2))


if __name__ == "__main__":
    main()
