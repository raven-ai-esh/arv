"""Auditable stop gates. Semantic judgments stay attributed to their authors.

The host supplies identities and delivery receipts; neither is an investigator tool
argument. This is role separation in a local application, not an OS security boundary.
Source adapters must journal *every* delivered case, including search snippets.
"""
from __future__ import annotations

import json
import re
import uuid

from .store import canonical, digest, now, text


class Protocol:
    def __init__(self, store, actor="local-researcher", role="researcher", bound_research=""):
        if role not in {"researcher", "reviewer"}:
            raise ValueError("Invalid host role")
        self.store, self.actor, self.role, self.bound = store, text(actor, "actor", 200), role, bound_research
        with store.db(write=True) as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS arv_contracts (
                    research_id TEXT PRIMARY KEY REFERENCES research(id), data TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS arv_stop_objects (
                    id TEXT PRIMARY KEY, research_id TEXT NOT NULL REFERENCES research(id),
                    kind TEXT NOT NULL, data TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS arv_deliveries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    research_id TEXT NOT NULL REFERENCES research(id), actor TEXT NOT NULL, data TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS arv_case_aliases (
                    research_id TEXT NOT NULL REFERENCES research(id), left_key TEXT NOT NULL, right_key TEXT NOT NULL,
                    PRIMARY KEY(research_id,left_key,right_key)
                );
            """)

    def _access(self, db, rid, role=None):
        research = self.store._research(db, rid)
        if self.bound and self.bound != rid:
            raise ValueError("This process is bound to a different research")
        if role and self.role != role:
            raise ValueError(f"A separate {role} process is required")
        if self.role == "reviewer":
            if self.actor == research.get("investigator_id", "local-researcher"):
                raise ValueError("The independent reviewer must differ from the investigator")
        elif self.actor != research.get("investigator_id", "local-researcher"):
            raise ValueError("Research belongs to another investigator")
        if not research.get("stop_protocol"):
            raise ValueError("Legacy research has no stopping contract; start a new research for protocol verification")
        return research

    def _contract(self, db, rid):
        row = db.execute("SELECT data FROM arv_contracts WHERE research_id=?", (rid,)).fetchone()
        return json.loads(row[0]) if row else {}

    def _object(self, db, rid, oid, kind):
        row = db.execute("SELECT data FROM arv_stop_objects WHERE research_id=? AND id=? AND kind=?", (rid, oid, kind)).fetchone()
        if not row:
            raise ValueError(f"Unknown {kind} in this research")
        return json.loads(row[0])

    def _objects(self, db, rid, kind):
        return [json.loads(row[0]) for row in db.execute("SELECT data FROM arv_stop_objects WHERE research_id=? AND kind=? ORDER BY rowid", (rid, kind))]

    def _put(self, db, rid, kind, data):
        db.execute("INSERT INTO arv_stop_objects VALUES (?,?,?,?)", (data["id"], rid, kind, canonical(data)))

    def _log(self, db, rid, operation, data, model_change=False):
        # Reviewer records must not reopen/change the frozen investigator graph.
        if model_change:
            self.store._event(db, rid, None, operation, {"actor": self.actor, **data})
        else:
            db.execute("INSERT INTO events(research_id,node_id,operation,at,data) VALUES (?,?,?,?,?)",
                       (rid, None, operation, now(), canonical({"actor": self.actor, **data})))

    def contract(self, rid, requirements):
        """Append immutable questions, coverage dimensions, rivals and material next tests."""
        with self.store.db(write=True) as db:
            return self._declare(db, rid, requirements)

    def _declare(self, db, rid, requirements):
        if not isinstance(requirements, list) or not requirements:
            raise ValueError("requirements must be a nonempty list")
        self._access(db, rid, "researcher")
        current = self._contract(db, rid)
        if not current and db.execute("SELECT 1 FROM nodes WHERE research_id=? AND kind='check'", (rid,)).fetchone():
            raise ValueError("Declare the stopping contract before the first material check")
        additions = {}
        for raw in requirements:
            if not isinstance(raw, dict):
                raise ValueError("Each requirement must be an object")
            key = text(raw.get("key"), "key", 100)
            kind = raw.get("kind")
            if kind not in {"question", "coverage", "alternative", "frontier"}:
                raise ValueError("kind must be question, coverage, alternative or frontier")
            critical, validation = raw.get("critical", True), raw.get("validation", "source_recheck")
            if type(critical) is not bool or validation not in {"new_case", "source_recheck"}:
                raise ValueError("Use boolean critical and validation new_case/source_recheck")
            if kind == "frontier" and not critical:
                raise ValueError("A material frontier test cannot be downranked")
            item = dict(key=key, kind=kind, description=text(raw.get("description"), "description"),
                        critical=critical, validation=validation, dimension=raw.get("dimension", ""))
            if kind == "coverage" and item["dimension"] not in {"source", "time", "segment", "scenario"}:
                raise ValueError("coverage dimension must be source/time/segment/scenario")
            old = current.get(key) or additions.get(key)
            if old and old["definition"] != item:
                raise ValueError("Requirement definitions are immutable; append a newly discovered requirement instead")
            if not old:
                additions[key] = dict(definition=item, declared_at=now(), progress=dict(state="open", explanation="Unexamined", claim_ids=[], check_ids=[], next_query=""))
        if additions:
            current.update(additions)
            db.execute("INSERT INTO arv_contracts VALUES (?,?) ON CONFLICT(research_id) DO UPDATE SET data=excluded.data", (rid, canonical(current)))
            self._log(db, rid, "stop_contract", {"added": additions}, True)
        return {"requirements": current, "duplicate": not bool(additions)}

    def plan_check(self, rid, request_key, claim_ids, question, method, rationale,
                   requirement_keys=None, requirements=None):
        """Declare new requirements and bind their check in one rollback-safe transaction."""
        with self.store.db(write=True) as db:
            self._access(db, rid, "researcher")
            if requirements is not None:
                self._declare(db, rid, requirements)
            keys = sorted(set(requirement_keys or []) | {r["key"] for r in requirements or []})
            contract = self._contract(db, rid)
            if not keys or set(keys) - set(contract):
                raise ValueError("Plan needs declared requirement keys; missing: " + ",".join(sorted(set(keys) - set(contract))))
            return self.store._check(db, rid, "plan", request_key, claim_ids, question, method,
                                     rationale, requirement_keys=keys)

    def progress(self, rid, key, state, explanation, claim_ids=None, check_ids=None, next_query="", delivery_ids=None,
                 context_check_ids=None):
        if state not in {"addressed", "unavailable", "open", "not_applicable"}:
            raise ValueError("state must be addressed/unavailable/open/not_applicable")
        explanation = text(explanation, "explanation")
        with self.store.db(write=True) as db:
            research = self._access(db, rid, "researcher")
            contract = self._contract(db, rid)
            if key not in contract:
                raise ValueError("Unknown requirement")
            item = contract[key]
            claims = [self.store._node(db, rid, cid, "claim") for cid in sorted(set(claim_ids or []))]
            checks = [self.store._node(db, rid, cid, "check") for cid in sorted(set(check_ids or []))]
            context_ids = set(context_check_ids or [])
            # An open question makes no validation claim. Preserve old links as context,
            # including callers using the original check_ids parameter for an open state.
            if state in {"open", "not_applicable"}:
                context_ids.update(c["id"] for c in checks)
                checks = []
            for cid in context_ids:
                self.store._node(db, rid, cid, "check")
            if state == "addressed":
                if not checks or any(c["status"] != "completed" or c["outcome"] not in {"found", "no_result"} for c in checks):
                    raise ValueError("Addressed requirements need executed checks with found/no_result outcomes")
                if item["definition"]["kind"] == "question" and (not claims or not any(c["outcome"] == "found" for c in checks)):
                    raise ValueError("An answered question needs model claims and evidence-producing checks")
                if any(c["stale"] or c["status"] not in {"supported", "confirmed"} for c in claims):
                    raise ValueError("Addressed requirements need current positive claims")
            if state == "unavailable":
                if not next_query.strip() or not checks or not any(c["outcome"] == "unavailable" for c in checks):
                    raise ValueError("Unavailable needs an executed unavailable check and the missing next_query; no_result/error is insufficient")
                deliveries = {d["id"]: d for d in self._deliveries(db, rid)}
                ids = sorted(set(delivery_ids or []))
                if not ids or any(i not in deliveries for i in ids):
                    raise ValueError("Unavailable needs actual host delivery_ids proving attempted source access")
                for i in ids:
                    d = deliveries[i]
                    if d["actor"] != self.actor or d["scope"] != research["scope"] or d["status"] != "unavailable":
                        raise ValueError("Unavailable source proof must belong to this investigator/scope and record provider unavailability")
                    if not any(c["outcome"] == "unavailable" and c["planned_at"] <= d["at"] <= c["completed_at"] for c in checks):
                        raise ValueError("Unavailable source proof must be delivered during the linked executed check")
            if state == "not_applicable" and item["definition"]["critical"]:
                raise ValueError("A critical requirement cannot be dismissed by the investigator")
            invalid = [c for c in checks if c["planned_at"] < item["declared_at"]]
            if item["definition"]["kind"] in {"alternative", "frontier"} and invalid:
                details = "; ".join(f"{c['id']} planned_at={c['planned_at']}" for c in invalid)
                raise ValueError(f"Discriminating checks must be planned after declaring requirement {key} "
                                 f"at {item['declared_at']}; invalid: {details}. "
                                 "Keep these checks as context_check_ids with state=open; use arv_plan_check "
                                 "to bind a new plan before further retrieval. Retrying the same links cannot fix their dates.")
            values = dict(state=state, explanation=explanation, claim_ids=[c["id"] for c in claims],
                          claim_revisions={c["id"]: c["revision"] for c in claims}, check_ids=[c["id"] for c in checks], next_query=next_query.strip(),
                          delivery_ids=sorted(set(delivery_ids or [])), context_check_ids=sorted(context_ids))
            if item["progress"] == values:
                return {**item, "duplicate": True}
            item["progress"] = values
            db.execute("UPDATE arv_contracts SET data=? WHERE research_id=?", (canonical(contract), rid))
            self._log(db, rid, "stop_progress", {"key": key, **values}, True)
            return {**item, "duplicate": False}

    def deliver(self, rid, actor, source_uri, origin_id, scope, content, case_keys, status="ok"):
        """HOST ONLY. Journal a source response before returning any data to a model.

        case_keys must include shared client/parent identities, not just note UUIDs.
        Never expose this method as an investigator/reviewer MCP tool. An unavailable
        response describes the concrete attempted operation and its provider result.
        """
        if status not in {"ok", "unavailable", "error"}:
            raise ValueError("Unknown delivery status")
        data = dict(source_uri=text(source_uri, "source_uri", 2000), origin_id=text(origin_id, "origin_id", 1000),
                    scope=text(scope, "scope", 500), content=text(content, "content", 200000),
                    case_keys=sorted({text(k, "case_key", 1000) for k in case_keys}), status=status, at=now())
        data["content_hash"] = digest(data["content"])
        with self.store.db(write=True) as db:
            research = self.store._research(db, rid)
            cursor = db.execute("INSERT INTO arv_deliveries(research_id,actor,data) VALUES (?,?,?)", (rid, text(actor, "actor", 200), canonical(data)))
            # Even uncited new data invalidates a completed/frozen investigator result.
            if actor == research.get("investigator_id") and research["status"] in {"concluded", "partial"}:
                research.update(status="active", conclusion=None)
                self.store._save_research(db, research)
            return {"id": cursor.lastrowid, "actor": actor, **data}

    def alias(self, rid, keys):
        """HOST ONLY. Add source-proven identity links; never edit old receipt bodies."""
        keys = sorted({text(k, "case_key", 1000) for k in keys})
        if len(keys) < 2:
            return {"duplicate": True}
        with self.store.db(write=True) as db:
            self.store._research(db, rid)
            before = db.total_changes
            for key in keys[1:]:
                db.execute("INSERT OR IGNORE INTO arv_case_aliases VALUES (?,?,?)", (rid, keys[0], key))
            changed = db.total_changes != before
            if changed:
                self._log(db, rid, "source_identity_alias", {"keys": keys}, True)
            return {"duplicate": not changed}

    def _case_closure(self, db, rid, keys):
        found = set(keys)
        links = list(db.execute("SELECT left_key,right_key FROM arv_case_aliases WHERE research_id=?", (rid,)))
        while True:
            before = len(found)
            for left, right in links:
                if left in found or right in found:
                    found.update((left, right))
            if len(found) == before:
                return found

    def _freshness_error(self, db, rid, candidate, challenge, sources, all_deliveries):
        seen = [d for d in all_deliveries if d["actor"] == candidate["investigator"] or d["id"] <= candidate["delivery_boundary"] or
                (d["actor"] == challenge["actor"] and d["id"] <= challenge["after_delivery"])]
        seen_keys = self._case_closure(db, rid, {k for d in seen for k in d["case_keys"]})
        seen_origins = {d["origin_id"] for d in seen}
        seen_hashes = {d["content_hash"] for d in seen}
        evidence = [json.loads(r[0]) for r in db.execute("SELECT data FROM nodes WHERE research_id=? AND kind='evidence'", (rid,))]
        seen_origins |= {e["origin_id"] for e in evidence}
        seen_hashes |= {digest(e["content"]) for e in evidence}
        if any(not d["case_keys"] or self._case_closure(db, rid, d["case_keys"]) & seen_keys or d["origin_id"] in seen_origins or d["content_hash"] in seen_hashes for d in sources):
            return "Validation requires fresh cases; this case/origin/content was previously delivered, aliased to it, or has no canonical case identity"
        return ""

    def _deliveries(self, db, rid):
        return [{"id": row["id"], "actor": row["actor"], **json.loads(row["data"])} for row in db.execute("SELECT * FROM arv_deliveries WHERE research_id=? ORDER BY id", (rid,))]

    def _signature(self, db, rid):
        research = self.store._research(db, rid)
        nodes = [dict(row) for row in db.execute("SELECT id,kind,fingerprint,data,revision,stale FROM nodes WHERE research_id=? ORDER BY id", (rid,))]
        edges = [dict(row) for row in db.execute("SELECT source,target,relation FROM edges WHERE research_id=? ORDER BY source,target,relation", (rid,))]
        exposure = db.execute("SELECT MAX(id) FROM arv_deliveries WHERE research_id=? AND actor=?", (rid, research["investigator_id"])).fetchone()[0]
        return digest([research["goal"], research["scope"], self._contract(db, rid), nodes, edges, exposure, self._objects(db, rid, "response")])

    def freeze(self, rid, summary, selected_claim_ids, unresolved_claim_ids):
        with self.store.db(write=True) as db:
            self._access(db, rid, "researcher")
            if not self._contract(db, rid):
                raise ValueError("Declare a stopping contract first")
            conclusion = self.store._conclusion(db, rid, summary, selected_claim_ids, unresolved_claim_ids)
            data = dict(id="f_" + uuid.uuid4().hex[:16], signature=self._signature(db, rid), conclusion=conclusion,
                        investigator=self.actor, at=now(), delivery_boundary=db.execute("SELECT COALESCE(MAX(id),0) FROM arv_deliveries WHERE research_id=?", (rid,)).fetchone()[0],
                        answer_claims={k: p["progress"]["claim_ids"] for k, p in self._contract(db, rid).items()},
                        claim_revisions={r["id"]: r["revision"] for r in db.execute("SELECT id,revision FROM nodes WHERE research_id=? AND kind='claim'", (rid,))})
            previous = self._objects(db, rid, "candidate")
            if previous:
                old = previous[-1]
                if all(old[k] == data[k] for k in ("signature", "conclusion", "investigator")) and not self._status(db, rid, old["id"]).get("invalid_challenges"):
                    return {**old, "duplicate": True}
                data["supersedes"] = old["id"]
            self._put(db, rid, "candidate", data)
            self._log(db, rid, "stop_freeze", data, True)
            return {**data, "duplicate": False, "next": "Host must launch a separate reviewer with the same source scope and instrumented source access"}

    def _current_candidate(self, db, rid, cid):
        candidate = self._object(db, rid, cid, "candidate")
        if self._objects(db, rid, "candidate")[-1]["id"] != cid:
            raise ValueError("Frozen candidate was superseded; inspect the latest candidate")
        if candidate["signature"] != self._signature(db, rid):
            raise ValueError("Frozen candidate is stale: model, contract, progress or investigator source exposure changed; freeze and review again")
        return candidate

    def challenge(self, rid, candidate_id, requirement_keys, method, expected, counterexample, mode):
        with self.store.db(write=True) as db:
            self._access(db, rid, "reviewer")
            self._current_candidate(db, rid, candidate_id)
            if any(r["candidate_id"] == candidate_id for r in self._objects(db, rid, "review")):
                raise ValueError("Candidate is already reviewed; its validation record is immutable")
            contract = self._contract(db, rid)
            keys = sorted(set(requirement_keys))
            if not keys or any(k not in contract or contract[k]["definition"]["validation"] != mode for k in keys):
                raise ValueError("Challenge requirements must exist and use the declared validation mode")
            data = dict(id="v_" + uuid.uuid4().hex[:16], candidate_id=candidate_id, actor=self.actor, requirement_keys=keys,
                        method=text(method, "method"), expected=text(expected, "expected"), counterexample=text(counterexample, "counterexample"),
                        mode=mode, after_delivery=db.execute("SELECT COALESCE(MAX(id),0) FROM arv_deliveries WHERE research_id=?", (rid,)).fetchone()[0],
                        at=now(), result=None)
            self._put(db, rid, "challenge", data)
            self._log(db, rid, "stop_challenge", data)
            return data

    def challenge_result(self, rid, challenge_id, outcome, delivery_ids, explanation):
        if outcome not in {"supports", "refutes", "inconclusive", "unavailable"}:
            raise ValueError("Unknown challenge outcome")
        freshness_error = ""
        with self.store.db(write=True) as db:
            research = self._access(db, rid, "reviewer")
            challenge = self._object(db, rid, challenge_id, "challenge")
            candidate = self._current_candidate(db, rid, challenge["candidate_id"])
            if challenge["actor"] != self.actor:
                raise ValueError("Challenge belongs to another reviewer")
            all_deliveries = self._deliveries(db, rid)
            index = {d["id"]: d for d in all_deliveries}
            ids = sorted(set(delivery_ids))
            if not ids or any(i not in index for i in ids):
                raise ValueError("Use host-recorded source delivery IDs")
            sources = [index[i] for i in ids]
            if any(d["actor"] != self.actor or d["id"] <= challenge["after_delivery"] for d in sources):
                raise ValueError("Validation data must be delivered to this reviewer after the challenge plan")
            if any(d["scope"] != research["scope"] for d in sources):
                raise ValueError("Validation source scope differs from research scope")
            if outcome == "unavailable":
                if not all(d["status"] == "unavailable" for d in sources):
                    raise ValueError("Unavailable needs a host-recorded unavailable source result")
            elif any(d["status"] != "ok" for d in sources):
                raise ValueError("A source error/unavailable response cannot support or refute the model")
            if challenge["mode"] == "new_case" and outcome != "unavailable":
                error = self._freshness_error(db, rid, candidate, challenge, sources, all_deliveries)
                if error:
                    # Close this unusable attempt with source proof, then report an
                    # error after commit. It must not remain an unfinishable plan.
                    freshness_error, outcome = error, "invalid"
            result = dict(outcome=outcome, delivery_ids=ids, explanation=text(explanation, "explanation"))
            if freshness_error:
                result["invalid_reason"] = freshness_error
            if challenge["result"]:
                if all(challenge["result"][k] == v for k, v in result.items()):
                    return {**challenge, "duplicate": True}
                raise ValueError("Completed challenges are immutable; plan another challenge")
            if any(r["candidate_id"] == challenge["candidate_id"] for r in self._objects(db, rid, "review")):
                raise ValueError("Reviewed validation records are immutable")
            result["at"] = now()
            challenge["result"] = result
            db.execute("UPDATE arv_stop_objects SET data=? WHERE id=?", (canonical(challenge), challenge_id))
            self._log(db, rid, "stop_challenge_result", challenge)
            response = {**challenge, "duplicate": False}
        if freshness_error:
            raise ValueError(freshness_error + "; this attempt was recorded invalid; plan a different validation case")
        return response

    def _finding(self, db, rid, finding_id):
        for kind in ("challenge", "review"):
            for finding in self._objects(db, rid, kind):
                if finding["id"] == finding_id:
                    if kind == "challenge" and finding.get("result") and finding["result"]["outcome"] in {"refutes", "inconclusive"}:
                        return finding, kind, finding["result"]["at"]
                    if kind == "review" and finding["verdict"] == "continue":
                        return finding, kind, finding["at"]
        raise ValueError("Unknown material independent finding")

    def finding(self, rid, finding_id):
        """Expose original counterexample data to the investigator, journalling the read."""
        with self.store.db(write=True) as db:
            research = self._access(db, rid, "researcher")
            finding, kind, _ = self._finding(db, rid, finding_id)
            records = []
            if kind == "challenge":
                ids = set(finding["result"]["delivery_ids"])
                for source in self._deliveries(db, rid):
                    if source["id"] in ids:
                        data = {k: v for k, v in source.items() if k not in {"id", "actor"}}
                        data["at"] = now()
                        cursor = db.execute("INSERT INTO arv_deliveries(research_id,actor,data) VALUES (?,?,?)", (rid, self.actor, canonical(data)))
                        records.append({**data, "id": cursor.lastrowid, "actor": self.actor})
            if records and research["status"] in {"concluded", "partial"}:
                research.update(status="active", conclusion=None)
                self.store._save_research(db, research)
            return dict(finding=finding, sources=records)

    def _frozen_claim(self, db, rid, candidate, cid):
        revision = candidate["claim_revisions"].get(cid)
        current = self.store._node(db, rid, cid, "claim")
        if current["revision"] == revision:
            return current
        for row in db.execute("SELECT data FROM events WHERE research_id=? AND node_id=? AND operation IN ('assess','hypothesize') ORDER BY seq DESC", (rid, cid)):
            data = json.loads(row[0])
            assessment = data.get("assessment", data)
            if assessment.get("id") == cid and assessment.get("revision") == revision:
                return assessment
        raise ValueError("Frozen claim assessment is not reconstructible")

    def _support_evidence(self, db, rid, cid, candidate=None, seen=None):
        seen = set() if seen is None else seen
        if cid in seen:
            return set()
        node = self.store._node(db, rid, cid)
        if node["kind"] == "claim" and candidate is not None:
            node = self._frozen_claim(db, rid, candidate, cid)
        found = {cid} if node["kind"] == "evidence" else set()
        for child in node.get("derived_from", []) if node["kind"] == "evidence" else node.get("supports", []):
            found |= self._support_evidence(db, rid, child, candidate, seen | {cid})
        return found

    def _refutation_scope(self, db, rid, finding, candidate):
        """Conservative compatibility for a legacy, explicitly citation-only finding.

        Old tools named broad requirements, while the same independent author could
        identify an exact wrong support edge in their signed corrective query. Never
        let the investigator supply a narrower scope. Ambiguity keeps the old guard.
        """
        broad = {c for k in finding["requirement_keys"] for c in candidate["answer_claims"].get(k, [])}
        explanation = " ".join(finding["result"]["explanation"].casefold().split())
        if finding["mode"] != "source_recheck" or "this refutes the citation semantics, not the existence" not in explanation:
            return broad, None
        from .report import primary_source_match
        def refs(prefix, value):
            value = value.replace("claimc_", "claim c_")
            return set(re.findall(r"\b" + prefix + r"_[0-9a-f]{16}\b", value))
        reported_claims = refs("c", finding["method"] + " " + finding["result"]["explanation"])
        reported_evidence = refs("e", finding["result"]["explanation"])
        if len(reported_claims) != 1 or len(reported_evidence) != 1:
            return broad, None
        selected = set(candidate["conclusion"]["selected_claim_ids"] + candidate["conclusion"]["premise_claim_ids"])
        source_ids = set(finding["result"]["delivery_ids"])
        sources = [d for d in self._deliveries(db, rid) if d["id"] in source_ids]
        choices = []
        for review in self._objects(db, rid, "review"):
            if review["candidate_id"] != finding["candidate_id"] or review["actor"] != finding["actor"] or review["verdict"] != "continue":
                continue
            for index, query in enumerate(review["next_queries"]):
                value = query["query"]
                low = value.casefold()
                if not ("correct" in low and ("active_support" in low or "positive supports" in low) and ("context" in low or "alternative" in low)):
                    continue
                if refs("c", value) != reported_claims or refs("e", value) != reported_evidence or not reported_claims <= selected:
                    continue
                cid, eid = next(iter(reported_claims)), next(iter(reported_evidence))
                try:
                    evidence = self.store._node(db, rid, eid, "evidence")
                    if not evidence["in_scope"] or eid not in self._support_evidence(db, rid, cid, candidate):
                        continue
                    if not any(s["origin_id"] == evidence["origin_id"] and s["source_uri"] == evidence["source_uri"] and s["scope"] == evidence["scope"]
                               and primary_source_match(evidence["content"], s["content"]) for s in sources):
                        continue
                except ValueError:
                    continue
                choices.append(dict(kind="independent_citation_query", review_id=review["id"], query_index=index,
                                    claim_ids=[cid], evidence_ids=[eid], bad_origin=evidence["origin_id"], bad_source_uri=evidence["source_uri"]))
        if len(choices) != 1:
            return broad, None
        return reported_claims, choices[0]

    def respond(self, rid, finding_id, explanation, check_ids, delivery_ids):
        """Record executed work on a material finding; a new reviewer judges resolution."""
        with self.store.db(write=True) as db:
            research = self._access(db, rid, "researcher")
            finding, kind, after = self._finding(db, rid, finding_id)
            checks = [self.store._node(db, rid, cid, "check") for cid in sorted(set(check_ids))]
            if not checks or any(c["planned_at"] <= after or c["status"] != "completed" or c["outcome"] not in {"found", "no_result", "unavailable"} for c in checks):
                raise ValueError("Respond with actual completed checks planned after the independent finding")
            index = {d["id"]: d for d in self._deliveries(db, rid)}
            ids = sorted(set(delivery_ids))
            if not ids or any(i not in index for i in ids):
                raise ValueError("A response needs actual host source delivery_ids")
            for i in ids:
                d = index[i]
                if d["actor"] != self.actor or d["scope"] != research["scope"] or d["status"] == "error" or not any(c["planned_at"] <= d["at"] <= c["completed_at"] for c in checks):
                    raise ValueError("Response source proof must be delivered to this investigator/scope during the executed check")
            if kind == "challenge" and finding["result"]["outcome"] == "refutes":
                candidate = self._object(db, rid, finding["candidate_id"], "candidate")
                target_claims, precise_scope = self._refutation_scope(db, rid, finding, candidate)
                counter_origins = {index[i]["origin_id"] for i in finding["result"]["delivery_ids"]}
                if precise_scope and not any(index[i]["origin_id"] == precise_scope["bad_origin"] and index[i]["source_uri"] == precise_scope["bad_source_uri"] and index[i]["status"] == "ok" for i in ids):
                    raise ValueError("Citation correction needs an actual post-finding reread of the identified source")
                for cid in target_claims:
                    claim = self.store._node(db, rid, cid, "claim")
                    if claim["revision"] <= candidate["claim_revisions"][cid]:
                        raise ValueError("Reassess every refuted answer claim, explicitly accounting for the counterexample")
                    if not any(self.store._node(db, rid, eid)["kind"] == "evidence" and self.store._node(db, rid, eid).get("origin_id") in counter_origins for eid in claim["counterevidence"]):
                        raise ValueError("Refuted claims must retain the original counterexample in their counterevidence ledger")
                    if precise_scope:
                        retained = [eid for eid in claim["counterevidence"] if self.store._node(db, rid, eid).get("origin_id") == precise_scope["bad_origin"]]
                        if not retained or claim["status"] in {"supported", "confirmed"} and not any(eid in claim["resolutions"] for eid in retained):
                            raise ValueError("Keep the identified citation and its explicit resolution on a positive corrected claim")
                        active_origins = {origin for eid in self._support_evidence(db, rid, cid) for origin in self.store._node(db, rid, eid).get("root_origins", [])}
                        if precise_scope["bad_origin"] in active_origins:
                            raise ValueError("The identified contextual source still enters the corrected positive support closure")
            data = dict(id="response_" + uuid.uuid4().hex[:16], finding_id=finding_id, explanation=text(explanation, "explanation"),
                        check_ids=[c["id"] for c in checks], delivery_ids=ids, actor=self.actor, at=now())
            if kind == "challenge" and finding["result"]["outcome"] == "refutes" and precise_scope:
                data["refutation_scope"] = precise_scope
            for old in self._objects(db, rid, "response"):
                if all(old[k] == data[k] for k in ("finding_id", "explanation", "check_ids", "delivery_ids", "actor")):
                    return {**old, "duplicate": True}
            self._put(db, rid, "response", data)
            self._log(db, rid, "stop_response", data, True)
            return {**data, "duplicate": False}

    def retry_review(self, rid, candidate_id, request_key, reason):
        """HOST ONLY. Recover an interrupted context without changing the frozen model.

        Never discard a material counterexample or a completed verdict. The original
        model freeze and exposure boundary stay fixed; no new investigator data may
        enter. Old attempts and receipts remain in the trace.
        """
        request_key, reason = text(request_key, "request_key", 200), text(reason, "reason")
        with self.store.db(write=True) as db:
            self._access(db, rid)
            for old in self._objects(db, rid, "candidate"):
                if old.get("retry_key") == request_key:
                    if old.get("supersedes") != candidate_id:
                        raise ValueError("Retry request_key reused for a different candidate")
                    return {**old, "duplicate": True}
            candidate = self._current_candidate(db, rid, candidate_id)
            tests = [c for c in self._objects(db, rid, "challenge") if c["candidate_id"] == candidate_id]
            if any(r["candidate_id"] == candidate_id for r in self._objects(db, rid, "review")) or any(c["result"] and c["result"]["outcome"] in {"refutes", "inconclusive"} for c in tests):
                raise ValueError("A substantive finding/verdict requires research response, not a reviewer restart")
            data = {**candidate, "id": "f_" + uuid.uuid4().hex[:16], "supersedes": candidate_id, "retry_key": request_key, "retry_reason": reason}
            self._put(db, rid, "candidate", data)
            self._log(db, rid, "stop_review_retry", data, True)
            return {**data, "duplicate": False}

    def review(self, rid, candidate_id, verdict, explanation, reviewed_keys, next_queries):
        if verdict not in {"accept", "partial", "continue"}:
            raise ValueError("verdict must be accept/partial/continue")
        with self.store.db(write=True) as db:
            self._access(db, rid, "reviewer")
            self._current_candidate(db, rid, candidate_id)
            if set(reviewed_keys) != set(self._contract(db, rid)):
                raise ValueError("Review must explicitly cover all declared requirements, including newly discovered ones")
            queries = []
            for q in next_queries:
                queries.append(dict(query=text(q.get("query"), "query"), reason=text(q.get("reason"), "reason")))
            if verdict == "continue" and not queries:
                raise ValueError("A continue verdict needs concrete next queries/counterexample checks")
            if verdict != "continue" and queries:
                raise ValueError("Available material next queries require a continue verdict")
            challenges = [c for c in self._objects(db, rid, "challenge") if c["candidate_id"] == candidate_id]
            if any(c["actor"] != self.actor for c in challenges):
                raise ValueError("A candidate review must have one independent reviewer context; freeze a new candidate for a new reviewer")
            data = dict(id="review_" + uuid.uuid4().hex[:16], candidate_id=candidate_id, actor=self.actor, verdict=verdict,
                        explanation=text(explanation, "explanation"), reviewed_keys=sorted(set(reviewed_keys)), next_queries=queries, at=now(),
                        report_sha256=getattr(self, "report_sha256", ""))
            previous = [r for r in self._objects(db, rid, "review") if r["candidate_id"] == candidate_id]
            if previous:
                old = previous[-1]
                if all(old.get(k, "") == data[k] for k in ("actor", "verdict", "explanation", "reviewed_keys", "next_queries", "report_sha256")):
                    return {**old, "duplicate": True}
                raise ValueError("Review verdict is immutable; change the model or append research work and freeze again")
            if verdict != "continue":
                current = self._status(db, rid, candidate_id)
                remaining = [b for b in current["blockers"] if b != "Independent reviewer verdict missing"]
                if remaining:
                    raise ValueError("Review cannot close available work: " + "; ".join(remaining))
                if (verdict == "partial") != bool(current["gaps"]):
                    raise ValueError("Use partial only for evidenced essential gaps; accept requires all essential evidence")
            self._put(db, rid, "review", data)
            self._log(db, rid, "stop_review", data)
            return data

    def _status(self, db, rid, candidate_id):
        research = self._access(db, rid)
        contract = self._contract(db, rid)
        blockers, gaps = [], []
        if not candidate_id:
            candidates = self._objects(db, rid, "candidate")
            candidate_id = candidates[-1]["id"] if candidates else ""
        if not candidate_id:
            return dict(decision="continue", blockers=["No frozen candidate"], gaps=[], requirements=contract, candidate=None, review=None)
        candidate = self._object(db, rid, candidate_id, "candidate")
        latest = self._objects(db, rid, "candidate")[-1]["id"]
        if candidate_id != latest:
            blockers.append("Candidate was superseded by " + latest)
        if candidate["signature"] != self._signature(db, rid):
            blockers.append("Frozen candidate is stale: model/contract/progress/source exposure changed")
        definitions = [r["definition"] for r in contract.values()]
        if not any(d["kind"] == "question" and d["critical"] for d in definitions):
            blockers.append("No essential question declared")
        for dimension in ("source", "time"):
            if not any(d["kind"] == "coverage" and d["dimension"] == dimension and d["critical"] for d in definitions):
                blockers.append(f"No essential {dimension} coverage declared")
        selected = set(candidate["conclusion"]["selected_claim_ids"] + candidate["conclusion"]["premise_claim_ids"])
        for key, item in contract.items():
            definition, progress = item["definition"], item["progress"]
            if not definition["critical"]:
                continue
            if progress["state"] == "unavailable":
                gaps.append(dict(requirement=key, reason=progress["explanation"], missing_query=progress["next_query"], check_ids=progress["check_ids"]))
            elif progress["state"] != "addressed":
                blockers.append(f"{key}: essential requirement/material test remains open; {progress.get('next_query') or definition['description']}")
            if progress["state"] == "addressed":
                for cid, revision in progress.get("claim_revisions", {}).items():
                    claim = self.store._node(db, rid, cid, "claim")
                    if claim["stale"] or claim["revision"] != revision or claim["status"] not in {"supported", "confirmed"}:
                        blockers.append(f"{key}: answer uses a changed or stale claim {cid}; update progress")
                if definition["kind"] == "question" and not set(progress["claim_ids"]) <= selected:
                    blockers.append(f"{key}: answer claims are missing from the frozen model")
        if not any(d["actor"] == research["investigator_id"] for d in self._deliveries(db, rid)):
            blockers.append("No host delivery ledger for investigator sources; freshness cannot be verified")
        challenges = [c for c in self._objects(db, rid, "challenge") if c["candidate_id"] == candidate_id]
        all_deliveries = self._deliveries(db, rid)
        delivery_index = {d["id"]: d for d in all_deliveries}
        invalid = {}
        for c in challenges:
            if c["mode"] == "new_case" and c["result"] and c["result"]["outcome"] != "unavailable":
                error = self._freshness_error(db, rid, candidate, c, [delivery_index[i] for i in c["result"]["delivery_ids"]], all_deliveries)
                if error:
                    invalid[c["id"]] = error
        responses = {r["finding_id"] for r in self._objects(db, rid, "response")}
        material = [c for c in self._objects(db, rid, "challenge") if c["result"] and c["result"]["outcome"] in {"refutes", "inconclusive"}]
        material += [r for r in self._objects(db, rid, "review") if r["verdict"] == "continue"]
        for finding in material:
            if finding["id"] not in responses:
                blockers.append("Unresolved independent finding " + finding["id"] + "; execute and record arv_respond before another acceptance")
        for challenge in challenges:
            if not challenge["result"]:
                blockers.append(f"{challenge['id']}: independent challenge still pending")
            elif challenge["result"]["outcome"] in {"refutes", "inconclusive"}:
                blockers.append(f"{challenge['id']}: material independent result {challenge['result']['outcome']}; research must reopen")
        for key, item in contract.items():
            if not item["definition"]["critical"]:
                continue
            tests = [c for c in challenges if key in c["requirement_keys"] and c["result"] and c["id"] not in invalid]
            if not tests:
                blockers.append(f"{key}: independent validation missing")
            elif item["progress"]["state"] == "unavailable" and any(c["result"]["outcome"] == "supports" for c in tests):
                blockers.append(f"{key}: reviewer obtained essential data previously marked unavailable; reopen the answer")
            elif not any(c["result"]["outcome"] == "supports" for c in tests):
                if all(c["result"]["outcome"] == "unavailable" for c in tests):
                    gaps.append(dict(requirement=key, reason="Independent validation sources unavailable", challenge_ids=[c["id"] for c in tests]))
        reviews = [r for r in self._objects(db, rid, "review") if r["candidate_id"] == candidate_id]
        review = reviews[-1] if reviews else None
        if not review:
            blockers.append("Independent reviewer verdict missing")
        else:
            if review["verdict"] == "continue":
                blockers.extend("Reviewer requires: " + q["query"] + ": " + q["reason"] for q in review["next_queries"])
            elif review["verdict"] == "partial" and not gaps:
                blockers.append("Partial verdict requires evidenced unavailable essential data; available work must continue")
            elif review["verdict"] == "accept" and gaps:
                blockers.append("A full acceptance cannot hide essential evidence gaps; reviewer must record partial")
        decision = "continue" if blockers else "partial" if gaps else "complete"
        return dict(decision=decision, blockers=blockers, gaps=gaps, requirements=contract, candidate=candidate, latest_candidate_id=latest,
                    independent_findings=material, research_responses=self._objects(db, rid, "response"), challenges=challenges, invalid_challenges=invalid, review=review,
                    boundary="Protocol completion is for the declared goal. Source independence relies on canonical host identities and complete delivery instrumentation; semantics remain independent reviewer judgments.")

    def status(self, rid, candidate_id=""):
        with self.store.db() as db:
            return self._status(db, rid, candidate_id)

    def deliveries(self, rid, after_id=0, limit=50):
        if not 1 <= limit <= 100 or after_id < 0:
            raise ValueError("Use limit 1..100 and after_id >= 0")
        with self.store.db() as db:
            self._access(db, rid)
            rows = [d for d in self._deliveries(db, rid) if d["actor"] == self.actor and d["id"] > after_id]
            return dict(deliveries=rows[:limit], next_after_id=rows[limit-1]["id"] if len(rows) > limit else None)

    def finish(self, rid, candidate_id):
        with self.store.db(write=True) as db:
            research = self._access(db, rid, "researcher")
            candidate = self._current_candidate(db, rid, candidate_id)
            status = self._status(db, rid, candidate_id)
            if status["decision"] == "continue":
                raise ValueError("continue: " + "; ".join(status["blockers"]))
            conclusion = {**candidate["conclusion"], "candidate_id": candidate_id, "signature": candidate["signature"],
                          "completion_state": status["decision"], "gaps": status["gaps"], "review_id": status["review"]["id"],
                          "review_report_sha256": status["review"].get("report_sha256", ""),
                          "stop_reason": "verified_for_declared_goal" if status["decision"] == "complete" else "essential_evidence_unavailable"}
            if research["conclusion"] == conclusion and research["status"] in {"concluded", "partial"}:
                return {**research, "duplicate": True}
            research.update(status="concluded" if status["decision"] == "complete" else "partial", conclusion=conclusion)
            self.store._save_research(db, research)
            self._log(db, rid, "finish", conclusion)
            return {**research, "duplicate": False}
