"""MCP surface for the observation -> hypothesis -> convergence loop."""
import os
from pathlib import Path
from typing import Literal

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from .store import Store, canonical, now, text, digest
from .working import WorkingModel


def build_server(path):
    store = Store(path)
    working = WorkingModel(store)
    actor = os.environ.get("ARV_ACTOR", "local-researcher")
    role = os.environ.get("ARV_ROLE", "researcher")
    bound = os.environ.get("ARV_RESEARCH", "")
    if role not in {"researcher", "reviewer"}:
        raise ValueError("Unknown ARV_ROLE")
    if role == "reviewer" and (not bound or actor == "local-researcher"):
        raise ValueError("Reviewer needs its own host identity and bound research")

    def access(rid, write=False, historical_read=False):
        with store.db() as db:
            r = store._research(db, rid) if historical_read else working._research(db, rid)
            if bound and rid != bound:
                raise ValueError("This process is bound to a different research")
            if role == "reviewer":
                if actor == r.get("investigator_id", "local-researcher") or write:
                    raise ValueError("Reviewer cannot change the investigator's model")
            elif actor != r.get("investigator_id", "local-researcher"):
                raise ValueError("Research belongs to another investigator")

    mcp = FastMCP("Assumption Research Verification", instructions=(
        "Build the most plausible coherent working model. Observe data, propose and semantically reuse hypotheses, "
        "accumulate meaningful new grounds, revise support on counterfacts, and synthesize the model. "
        "arv_hypothesize adds support automatically; arv_assess records new support, opposition or a reasoned withdrawal. "
        "Declare user conventions and ordinary domain defaults with arv_assume. Missing documents are not counterfacts. "
        "The server aggregates ordinal relevance and removes repeated roots; the agent judges semantics. "
        "An unrelated-dataset holdout, proof of every inference, and an independent-review certificate are not mandatory. "
        "Read arv://method for the complete method."
    ))
    read = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
    write = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False)

    @mcp.resource("arv://method", mime_type="text/markdown")
    def method():
        root = Path(__file__).resolve().parents[2]/"skills/assumption-research-verification"
        body = (root/"SKILL.md").read_text(encoding="utf-8")
        return body + ("\n\n" + (root/"references/working-review.md").read_text(encoding="utf-8") if role == "reviewer" else "")

    @mcp.tool(annotations=write)
    def arv_begin(goal: str, scope: str, request_key: str, max_checks: int | None = None) -> dict:
        """Begin a working-model investigation. Scope identifies subject/domain and period. No fixed check budget unless the user requests one. Identical request_key retries return the original research."""
        if bound or role != "researcher":
            raise ValueError("Use the research already bound to this process")
        if os.environ.get("ARV_FORCE_UNBOUNDED") == "1" and max_checks is not None:
            raise ValueError("Use max_checks=null")
        return working.begin(goal, scope, request_key, max_checks, actor)

    @mcp.tool(annotations=write)
    def arv_observe(research_id: str, content: str, source_uri: str, origin_id: str,
                    locator: str, scope: str, source_kind: Literal["primary", "derived"] = "primary",
                    derived_from: list[str] | None = None, valid_at: str = "") -> dict:
        """Save a source observation with its actual identity/date/scope. Copies preserve origin and locator. A derived retelling links its original evidence and creates no new observation weight."""
        access(research_id, True)
        return store.observe(research_id, content, source_uri, origin_id, locator, scope, source_kind, derived_from, valid_at)

    @mcp.tool(annotations=write)
    def arv_assume(research_id: str, statement: str, kind: Literal["user_rule", "domain_prior"],
                   reason: str, strength: Literal["weak", "moderate", "strong"] = "weak") -> dict:
        """Declare a user-approved interpretation or ordinary domain default, without inventing an observation. E.g. a user_rule can interpret an unspecified raw unit as centimetres; a documented different scale is a counterfact. Use the returned ID as a hypothesis basis."""
        access(research_id, True)
        return working.assume(research_id, statement, kind, reason, strength)

    @mcp.tool(annotations=write)
    def arv_hypothesize(research_id: str, subject: str, predicate: str, object: str, rationale: str,
                        based_on: list[str] | None = None, alternatives: list[str] | None = None,
                        same_as: str = "", strength: Literal["weak", "moderate", "strong"] = "moderate") -> dict:
        """Propose or strengthen a hypothesis with observations, accepted premises and defaults. New grounded facts automatically increase support; copies and repeated inference paths do not. Use same_as for an existing semantically equivalent claim even if its wording differs. Strength is ordinal diagnostic relevance, not a probability. Alternatives are mutually exclusive."""
        access(research_id, True)
        return working.hypothesize(research_id, subject, predicate, object, rationale, based_on, alternatives, same_as, strength)

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False))
    def arv_assess(research_id: str, claim_id: str, basis_ids: list[str], effect: Literal["support", "oppose", "withdraw"],
                   strength: Literal["weak", "moderate", "strong"], reason: str, expected_revision: int) -> dict:
        """Weigh actual grounds; support/plausibility and dependent claims recompute automatically. Oppose needs a meaningful counterfact/alternative basis, not an absent document. Withdraw retains history and needs a reason. Use the current revision to avoid overwriting a concurrent assessment."""
        access(research_id, True)
        return working.assess(research_id, claim_id, basis_ids, effect, strength, reason, expected_revision)

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False))
    def arv_merge(research_id: str, keep_id: str, duplicate_id: str, reason: str,
                  expected_keep_revision: int, expected_duplicate_revision: int) -> dict:
        """Merge already-created semantically equivalent claims after comparing their meaning. Preserve both histories and all grounds, redirect dependents, and count each root once. This is an agent's equivalence judgment, not automatic string-based truth."""
        access(research_id, True)
        return working.merge(research_id, keep_id, duplicate_id, reason, expected_keep_revision, expected_duplicate_revision)

    @mcp.tool(annotations=read)
    def arv_model(research_id: str) -> dict:
        """Inspect current plausibility, distinct observations/defaults and a suggested consistent selection. Equal rivals remain visible for an explicit semantic choice. Ranking is ordinal support, not calibrated probability or globally certified truth."""
        access(research_id)
        return working.model(research_id)

    @mcp.tool(annotations=read)
    def arv_inspect(research_id: str, view: Literal["frontier", "graph", "trace"] = "frontier",
                    focus_id: str = "", limit: int = 50, offset: int = 0) -> dict:
        """Read the graph, a focused hypothesis or history. Follow pagination as needed; no fixed total-page budget. Ordinary unresolved details do not prevent selecting a working picture."""
        access(research_id, historical_read=True)
        return store.inspect(research_id, view, focus_id, limit, offset)

    @mcp.tool(annotations=write)
    def arv_check(research_id: str, action: Literal["plan", "complete", "cancel"], request_key: str = "",
                  claim_ids: list[str] | None = None, question: str = "", method: str = "", rationale: str = "",
                  check_id: str = "", outcome: str = "", evidence_ids: list[str] | None = None, result: str = "") -> dict:
        """Optionally record a targeted inquiry that can change the model or resolve a meaningful conflict. There is no mandatory per-observation contract. Preserve error/unavailable/no_result honestly; absence alone is not a counterfact."""
        access(research_id, True)
        return store.check(research_id, action, request_key, claim_ids, question, method, rationale, check_id, outcome, evidence_ids, result)

    @mcp.tool(annotations=write)
    def arv_finish(research_id: str, summary: str, selected_claim_ids: list[str] | None = None,
                   open_questions: list[str] | None = None) -> dict:
        """Save the most plausible working picture, including its assumptions and residual questions. Optional explicit choices override the suggested selection but must be coherent and currently supported. No external receipts/unrelated-dataset holdout/reviewer certificate is required. Material new graph data reopens the result."""
        access(research_id, True)
        return working.finish(research_id, summary, selected_claim_ids, open_questions)

    @mcp.tool(annotations=write)
    def arv_review(research_id: str, verdict: Literal["reasonable", "revise"], explanation: str,
                   issues: list[str] | None = None) -> dict:
        """Optional reviewer note on plausibility, coherent inference, real contradictions and user conventions. Missing documentary proof of a normal accepted inference is not itself a defect. This is attributed feedback, not a mandatory completion certificate."""
        access(research_id)
        if role != "reviewer":
            raise ValueError("Use a separate reviewer identity for review feedback")
        with store.db(write=True) as db:
            model = working._model(db, research_id)[0]
            data = dict(actor=actor, verdict=verdict, explanation=text(explanation, "explanation"), issues=issues or [],
                        signature=digest(dict(claims=model["claims"], assumptions=model["assumptions"], conclusion=model["research"]["conclusion"])), at=now())
            db.execute("INSERT INTO events(research_id,node_id,operation,at,data) VALUES (?,NULL,?,?,?)",
                       (research_id, "working_review", data["at"], canonical(data)))
            return data

    if role == "reviewer":
        for name in ("arv_begin", "arv_observe", "arv_assume", "arv_hypothesize", "arv_assess", "arv_merge", "arv_check", "arv_finish"):
            mcp.remove_tool(name)
    else:
        mcp.remove_tool("arv_review")
    return mcp
