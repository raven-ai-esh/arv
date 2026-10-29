"""Compatibility endpoint for historical validation-protocol research."""
import os
import sys
from pathlib import Path
from typing import Literal

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from .store import Store
from .stopping import Protocol


def data_path():
    if os.environ.get("ARV_DB"):
        return Path(os.environ["ARV_DB"])
    if os.environ.get("ARV_DATA_DIR"):
        return Path(os.environ["ARV_DATA_DIR"]) / "graph.sqlite3"
    if os.environ.get("XDG_DATA_HOME"):
        return Path(os.environ["XDG_DATA_HOME"]) / "assumption-research-verification" / "graph.sqlite3"
    if sys.platform == "win32":
        root = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData/Local")
    else:
        root = Path.home() / ("Library/Application Support" if sys.platform == "darwin" else ".local/share")
    return root / "assumption-research-verification" / "graph.sqlite3"


def build_server(path=None):
    store = Store(path or data_path())
    actor = os.environ.get("ARV_ACTOR", "local-researcher")
    role = os.environ.get("ARV_ROLE", "researcher")
    protocol = Protocol(store, actor, role, os.environ.get("ARV_RESEARCH", ""))
    protocol.report_sha256 = os.environ.get("ARV_REPORT_SHA256", "") if role == "reviewer" else ""
    if role == "reviewer" and (not protocol.bound or actor == "local-researcher"):
        raise ValueError("Host must give an independent reviewer a unique ARV_ACTOR and bound ARV_RESEARCH")

    def access(research_id, required=None):
        with store.db() as db:
            research = store._research(db, research_id)
            if research.get("stop_protocol"):
                protocol._access(db, research_id, required)
            elif role == "reviewer" or protocol.bound and protocol.bound != research_id:
                raise ValueError("Legacy research is readable only by the unbound investigator process")
    mcp = FastMCP("Assumption Research Verification", instructions=(
        "Persistent research graph. The agent chooses and executes source queries through separate authorized tools. "
        "Observe original passages, propose atomic claims, plan discriminating checks before retrieving, "
        "record outcomes, assess with evidence, and disclose unknowns when concluding. "
        "Assessments are attributed judgments, not calibrated probabilities or server-certified truth. "
        "The full bundled method is available as MCP resource arv://method when filesystem skill reading is unavailable."
    ))
    write = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False)
    read = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)

    @mcp.resource("arv://method", mime_type="text/markdown")
    def research_method() -> str:
        """Read the bundled investigative skill through MCP, with no arbitrary file access."""
        return (Path(__file__).resolve().parents[2] / "skills" / "assumption-research-verification" / "references" / "legacy-validation.md").read_text(encoding="utf-8")

    @mcp.tool(annotations=write)
    def arv_begin(goal: str, scope: str, request_key: str, max_checks: int | None = None) -> dict:
        """Start scoped research. No fixed check budget by default (max_checks=null). Set a positive budget only when the user requests one. Reuse request_key only for an identical retry. Scope identifies organization/domain and period."""
        if os.environ.get("ARV_FORCE_UNBOUNDED") == "1" and max_checks is not None:
            raise ValueError("This run requires no artificial check budget; use max_checks=null")
        if protocol.bound:
            raise ValueError("This process is bound to an existing research; use its ARV_RESEARCH id")
        return store.begin(goal, scope, request_key, max_checks, actor=actor, method="validation")

    @mcp.tool(annotations=write)
    def arv_observe(research_id: str, content: str, source_uri: str, origin_id: str,
                    locator: str, scope: str, source_kind: Literal["primary", "derived"] = "primary",
                    derived_from: list[str] | None = None, valid_at: str = "") -> dict:
        """Record an exact source passage. Preserve original origin_id across copies. Derived summaries require parent evidence IDs and inherit their origins. Out-of-scope observations are retained as context and cannot assess this research."""
        access(research_id, "researcher")
        return store.observe(research_id, content, source_uri, origin_id, locator, scope,
                             source_kind, derived_from, valid_at)

    @mcp.tool(annotations=write)
    def arv_hypothesize(research_id: str, subject: str, predicate: str, object: str,
                        rationale: str, based_on: list[str] | None = None,
                        alternatives: list[str] | None = None) -> dict:
        """Propose an atomic entity-existence or relationship claim. Exact normalized triples merge without increasing confidence. based_on records discovery provenance, not proof. alternatives are mutually exclusive claim IDs."""
        access(research_id, "researcher")
        return store.hypothesize(research_id, subject, predicate, object, rationale, based_on, alternatives)

    @mcp.tool(annotations=read)
    def arv_inspect(research_id: str, view: Literal["frontier", "graph", "trace"] = "frontier",
                    focus_id: str = "", limit: int = 50, offset: int = 0) -> dict:
        """Read a graph page, unresolved frontier, or audit trace. Follow next_offset/events_next_offset without a total-page limit. checks_remaining=null means no fixed check budget. Returns revisions and distinct original-source counts; those counts are not probabilities."""
        access(research_id)
        return store.inspect(research_id, view, focus_id, limit, offset)

    @mcp.tool(annotations=write)
    def arv_check(research_id: str, action: Literal["plan", "complete", "cancel"],
                  request_key: str = "", claim_ids: list[str] | None = None, question: str = "",
                  method: str = "", rationale: str = "", check_id: str = "", outcome: str = "",
                  evidence_ids: list[str] | None = None, result: str = "") -> dict:
        """Plan a check BEFORE source retrieval: include claim_ids, question, method, rationale explaining what distinguishes alternatives, and a retry-stable request_key. Then complete check_id with outcome found/no_result/unavailable/error and a result. found requires evidence_ids. cancel requires a reason in result. This tool records checks; the agent executes source tools separately."""
        access(research_id, "researcher")
        return store.check(research_id, action, request_key, claim_ids, question, method, rationale,
                           check_id, outcome, evidence_ids, result)

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False))
    def arv_assess(research_id: str, claim_id: str,
                   status: Literal["proposed", "supported", "confirmed", "contested", "rejected", "unknown"],
                   reason: str, expected_revision: int, supports: list[str] | None = None,
                   contradicts: list[str] | None = None, resolutions: dict[str, str] | None = None) -> dict:
        """Record an evidence-linked agent judgment using the current revision. supported/confirmed need support and no unresolved counterevidence; confirmed additionally needs direct primary evidence. rejected needs explicit counterevidence, not mere absence. resolves maps previously recorded counterevidence IDs to reasons. Changes invalidate dependent claims. The server checks provenance structure, not semantic truth."""
        access(research_id, "researcher")
        return store.assess(research_id, claim_id, status, reason, expected_revision, supports, contradicts, resolutions)

    @mcp.tool(annotations=write)
    def arv_finish(research_id: str, candidate_id: str = "", summary: str = "",
                   selected_claim_ids: list[str] | None = None, unresolved_claim_ids: list[str] | None = None,
                   stop_reason: str = "sufficient_evidence") -> dict:
        """New research: finish ONLY the frozen candidate_id after independent review; saves complete or partial with explicit gaps, rejects continue. The candidate's exact summary/model are used. Other parameters are legacy compatibility for pre-protocol research. Later model/source changes reopen the result."""
        access(research_id, "researcher")
        if candidate_id:
            return protocol.finish(research_id, candidate_id)
        return store.finish(research_id, summary, selected_claim_ids, unresolved_claim_ids, stop_reason)

    @mcp.tool(annotations=write)
    def arv_contract(research_id: str, requirements: list[dict]) -> dict:
        """BEFORE the first material check, declare essential questions and source/time coverage. Append discovered alternatives/frontier tests later. Each object: key, kind(question/coverage/alternative/frontier), description, critical(bool), validation(new_case/source_recheck), dimension(source/time/segment/scenario for coverage). Definitions are immutable: no removal/rewording/downranking. Generalizations require new_case; direct source facts use source_recheck. Describe what would distinguish alternatives in their definition."""
        return protocol.contract(research_id, requirements)

    @mcp.tool(annotations=write)
    def arv_plan_check(research_id: str, request_key: str, claim_ids: list[str], question: str,
                       method: str, rationale: str, requirement_keys: list[str] | None = None,
                       requirements: list[dict] | None = None) -> dict:
        """Atomically declare new questions/branches and plan their check BEFORE retrieval. Pass new requirements (same objects as arv_contract) and/or existing requirement_keys. Saves both or neither; retries with identical request_key return the same check. Prefer this for every new material branch. Execute source tools separately, then complete with arv_check."""
        return protocol.plan_check(research_id, request_key, claim_ids, question, method, rationale,
                                   requirement_keys, requirements)

    @mcp.tool(annotations=write)
    def arv_progress(research_id: str, key: str, state: Literal["addressed", "unavailable", "open", "not_applicable"],
                     explanation: str, claim_ids: list[str] | None = None, check_ids: list[str] | None = None,
                     next_query: str = "", delivery_ids: list[int] | None = None,
                     context_check_ids: list[str] | None = None) -> dict:
        """Credit executed checks/current claims, or preserve old checks as context_check_ids. In state=open, check_ids are retained as context and never credited as validation. unavailable needs an unavailable check, actual delivery_ids and concrete missing next_query. Critical requirements cannot be dismissed. An ordering error names offending checks/dates: preserve context and use arv_plan_check for new work."""
        return protocol.progress(research_id, key, state, explanation, claim_ids, check_ids, next_query, delivery_ids, context_check_ids)

    @mcp.tool(annotations=write)
    def arv_freeze(research_id: str, summary: str, selected_claim_ids: list[str], unresolved_claim_ids: list[str]) -> dict:
        """Freeze an exact coherent candidate before independent testing. Requires disclosed unknowns, compatible current selections and no pending checks. This does not finish research. A host must launch a fresh independent reviewer with instrumented source access. New investigator data, claim or contract/progress changes invalidate the candidate and its review."""
        return protocol.freeze(research_id, summary, selected_claim_ids, unresolved_claim_ids)

    @mcp.tool(annotations=read)
    def arv_stop_status(research_id: str, candidate_id: str = "") -> dict:
        """Read deterministic complete/partial/continue decision, concrete blockers, essential gaps, immutable contract, frozen model and reviewer findings. Missing independent review requires host handoff; never self-approve or poll indefinitely. Source delivery instrumentation is required to verify freshness."""
        return protocol.status(research_id, candidate_id)

    @mcp.tool(annotations=read)
    def arv_deliveries(research_id: str, after_id: int = 0, limit: int = 50) -> dict:
        """Read source receipts delivered to THIS process identity only. Receipts are written by the trusted source adapter, never by a model. Follow next_after_id. New cases use canonical shared client/parent identity and source content, including uncited earlier deliveries."""
        return protocol.deliveries(research_id, after_id, limit)

    @mcp.tool(annotations=read)
    def arv_finding(research_id: str, finding_id: str) -> dict:
        """INVESTIGATOR ONLY. Read an independent material finding and its original counterexample records. Journalled as investigator exposure, so plan the follow-up check before this read. These records retain their original scope/origins; another candidate or summary cannot erase the finding."""
        return protocol.finding(research_id, finding_id)

    @mcp.tool(annotations=write)
    def arv_respond(research_id: str, finding_id: str, explanation: str, check_ids: list[str], delivery_ids: list[int]) -> dict:
        """INVESTIGATOR ONLY. Account for a material challenge/refusal with executed checks planned AFTER it and actual same-scope source receipts. Refuted answer claims must be reassessed and retain original counterevidence (even if explicitly resolved). The next independent reviewer judges the resolution. All material findings persist across candidate/summary changes until a response is recorded."""
        return protocol.respond(research_id, finding_id, explanation, check_ids, delivery_ids)

    @mcp.tool(annotations=write)
    def arv_challenge(research_id: str, candidate_id: str, requirement_keys: list[str], method: str,
                      expected: str, counterexample: str, mode: Literal["new_case", "source_recheck"]) -> dict:
        """REVIEWER ONLY. Before querying validation sources, record targets, exact method, expected observation and a material counterexample. Mode must match the immutable requirement. new_case rejects previously delivered clients/cases/origins/content; source_recheck verifies literal source facts."""
        return protocol.challenge(research_id, candidate_id, requirement_keys, method, expected, counterexample, mode)

    @mcp.tool(annotations=write)
    def arv_challenge_result(research_id: str, challenge_id: str, outcome: Literal["supports", "refutes", "inconclusive", "unavailable"],
                             delivery_ids: list[int], explanation: str) -> dict:
        """REVIEWER ONLY. Link a challenge result to actual same-scope source deliveries after the plan. Newly discovered client aliases are checked against old receipts too. Invalid freshness closes the attempt as invalid and returns an error: inspect it and plan another case. refutes/inconclusive reopens research; unavailable requires source-adapter proof. Supports/refutes remain reviewer judgments."""
        return protocol.challenge_result(research_id, challenge_id, outcome, delivery_ids, explanation)

    @mcp.tool(annotations=write)
    def arv_review(research_id: str, candidate_id: str, verdict: Literal["accept", "partial", "continue"],
                   explanation: str, reviewed_keys: list[str], next_queries: list[dict]) -> dict:
        """REVIEWER ONLY. Audit the goal decomposition, coverage, material alternatives, actual tests, source independence, unknown impact and available next work. Cover ALL requirement keys. Accept only after executed tests pass; essential unavailable data permits partial. continue requires concrete next_queries [{query,reason}]. An available material query cannot be hidden behind partial. Verdict is immutable and bound to the frozen model."""
        return protocol.review(research_id, candidate_id, verdict, explanation, reviewed_keys, next_queries)

    if role == "researcher":
        for name in ("arv_challenge", "arv_challenge_result", "arv_review"):
            mcp.remove_tool(name)
    else:
        for name in ("arv_begin", "arv_observe", "arv_hypothesize", "arv_check", "arv_plan_check", "arv_assess", "arv_finish", "arv_contract", "arv_progress", "arv_freeze", "arv_finding", "arv_respond"):
            mcp.remove_tool(name)

    return mcp


def main():
    build_server().run(transport="stdio")


if __name__ == "__main__":
    main()
