"""Transactional, single-user graph. Assessments remain attributed agent judgments."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def normalized(value):
    return " ".join(value.split()).casefold()


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat()


def text(value, field, maximum=12000):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"{field} must be nonempty text of at most {maximum} characters")
    return value.strip()


class Store:
    def __init__(self, path):
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.db(write=None) as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS research (
                    id TEXT PRIMARY KEY, request_key TEXT UNIQUE NOT NULL,
                    data TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS nodes (
                    id TEXT PRIMARY KEY, research_id TEXT NOT NULL REFERENCES research(id),
                    kind TEXT NOT NULL, fingerprint TEXT NOT NULL, data TEXT NOT NULL,
                    revision INTEGER NOT NULL DEFAULT 1, stale INTEGER NOT NULL DEFAULT 0,
                    UNIQUE(research_id,kind,fingerprint)
                );
                CREATE TABLE IF NOT EXISTS edges (
                    research_id TEXT NOT NULL REFERENCES research(id),
                    source TEXT NOT NULL REFERENCES nodes(id),
                    target TEXT NOT NULL REFERENCES nodes(id), relation TEXT NOT NULL,
                    PRIMARY KEY(source,target,relation)
                );
                CREATE TABLE IF NOT EXISTS events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    research_id TEXT NOT NULL REFERENCES research(id),
                    node_id TEXT, operation TEXT NOT NULL, at TEXT NOT NULL, data TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS arv_contracts (
                    research_id TEXT PRIMARY KEY REFERENCES research(id), data TEXT NOT NULL
                );
            """)

    @contextmanager
    def db(self, write=False):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        if write is not None:
            # A graph read must see node bodies, provenance roots, edges and conclusion
            # from the same commit. WAL permits concurrent writers during this snapshot.
            db.execute("BEGIN IMMEDIATE" if write else "BEGIN")
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def _research(self, db, research_id):
        row = db.execute("SELECT data FROM research WHERE id=?", (research_id,)).fetchone()
        if not row:
            raise ValueError("Unknown research_id")
        return {"id": research_id, **json.loads(row["data"])}

    def _node(self, db, research_id, node_id, kind=None):
        row = db.execute("SELECT * FROM nodes WHERE id=? AND research_id=?", (node_id, research_id)).fetchone()
        if not row or (kind and row["kind"] != kind):
            raise ValueError(f"Unknown {kind or 'node'} in this research: {node_id}")
        return {"id": row["id"], "kind": row["kind"], "revision": row["revision"],
                "stale": bool(row["stale"]), **json.loads(row["data"])}

    def _save(self, db, node):
        data = {k: v for k, v in node.items() if k not in {"id", "kind", "revision", "stale"}}
        db.execute("UPDATE nodes SET data=?,revision=?,stale=? WHERE id=?",
                   (canonical(data), node["revision"], int(node["stale"]), node["id"]))

    def _insert(self, db, research_id, kind, fingerprint, data):
        node_id = kind[0] + "_" + uuid.uuid4().hex[:16]
        db.execute("INSERT INTO nodes(id,research_id,kind,fingerprint,data) VALUES (?,?,?,?,?)",
                   (node_id, research_id, kind, fingerprint, canonical(data)))
        return self._node(db, research_id, node_id)

    def _edge(self, db, research_id, source, target, relation):
        db.execute("INSERT OR IGNORE INTO edges VALUES (?,?,?,?)", (research_id, source, target, relation))

    def _event(self, db, research_id, node_id, operation, data):
        db.execute("INSERT INTO events(research_id,node_id,operation,at,data) VALUES (?,?,?,?,?)",
                   (research_id, node_id, operation, now(), canonical(data)))
        research = self._research(db, research_id)
        if operation != "finish" and research["status"] in {"concluded", "partial"}:
            research.update(status="active", conclusion=None)
            self._save_research(db, research)

    def _save_research(self, db, research):
        db.execute("UPDATE research SET data=? WHERE id=?",
                   (canonical({k: v for k, v in research.items() if k != "id"}), research["id"]))

    def _reachable(self, db, research_id, start):
        found, pending = set(), [start]
        while pending:
            source = pending.pop()
            for row in db.execute("SELECT target FROM edges WHERE research_id=? AND source=? "
                                  "AND relation IN ('supports','contradicts')", (research_id, source)):
                if row["target"] not in found:
                    found.add(row["target"])
                    pending.append(row["target"])
        return found

    def _invalidate(self, db, research_id, node_id):
        affected = self._reachable(db, research_id, node_id)
        for child in affected:
            db.execute("UPDATE nodes SET stale=1,revision=revision+1 WHERE id=? AND kind='claim'", (child,))
        return sorted(affected)

    def _roots(self, db, research_id, node_id, visited=None):
        visited = set() if visited is None else visited
        if node_id in visited:
            raise ValueError("Circular support is not evidence")
        node = self._node(db, research_id, node_id)
        if node["kind"] == "evidence":
            return set(node["root_origins"]) if node["in_scope"] else set()
        if node["kind"] != "claim" or node["stale"] or node["status"] not in {"supported", "confirmed"}:
            return set()
        roots = set()
        for source in node.get("supports", []):
            roots |= self._roots(db, research_id, source, visited | {node_id})
        return roots

    def begin(self, goal, scope, request_key, max_checks=None, actor="local-researcher", method="validation"):
        goal, scope, request_key = text(goal, "goal"), text(scope, "scope", 500), text(request_key, "request_key", 200)
        if max_checks is not None and (type(max_checks) is not int or max_checks < 1):
            raise ValueError("max_checks must be null for no fixed budget, or a positive integer explicitly requested by the user")
        if method not in {"validation", "working_model"}:
            raise ValueError("Unknown research method")
        with self.db(write=True) as db:
            old = db.execute("SELECT id FROM research WHERE request_key=?", (request_key,)).fetchone()
            if old:
                research = self._research(db, old["id"])
                old_method = research.get("method", "validation")
                if (research["goal"], research["scope"], research["max_checks"], old_method) != (goal, scope, max_checks, method):
                    raise ValueError("request_key already used with different arguments")
                return {**research, "duplicate": True}
            research_id = "r_" + uuid.uuid4().hex[:16]
            data = dict(goal=goal, scope=scope, max_checks=max_checks, status="active", created_at=now(),
                        conclusion=None, stop_protocol=1 if method == "validation" else 0,
                        method=method, investigator_id=text(actor, "actor", 200))
            db.execute("INSERT INTO research VALUES (?,?,?)", (research_id, request_key, canonical(data)))
            self._event(db, research_id, None, "begin", data)
            return {"id": research_id, **data, "duplicate": False}

    def observe(self, research_id, content, source_uri, origin_id, locator, scope,
                source_kind="primary", derived_from=None, valid_at=""):
        content, source_uri = text(content, "content", 50000), text(source_uri, "source_uri", 2000)
        origin_id, locator, scope = text(origin_id, "origin_id", 1000), text(locator, "locator", 1000), text(scope, "scope", 500)
        if source_kind not in {"primary", "derived"}:
            raise ValueError("source_kind must be primary or derived")
        derived_from = sorted(set(derived_from or []))
        with self.db(write=True) as db:
            research = self._research(db, research_id)
            roots, in_scope = set(), scope == research["scope"]
            if source_kind == "primary":
                if derived_from:
                    raise ValueError("A derived observation cannot be declared primary")
                roots = {origin_id} if in_scope else set()
            else:
                if not derived_from:
                    raise ValueError("Derived observations require source evidence IDs")
                for parent_id in derived_from:
                    parent = self._node(db, research_id, parent_id, "evidence")
                    roots |= set(parent["root_origins"])
                    in_scope = in_scope and parent["in_scope"]
            fingerprint = digest([source_kind, scope, origin_id if source_kind == "primary" else derived_from,
                                  normalized(locator), normalized(content), valid_at])
            old = db.execute("SELECT id FROM nodes WHERE research_id=? AND kind='evidence' AND fingerprint=?",
                             (research_id, fingerprint)).fetchone()
            if old:
                return {**self._node(db, research_id, old["id"]), "duplicate": True}
            node = self._insert(db, research_id, "evidence", fingerprint,
                                dict(content=content, source_uri=source_uri, origin_id=origin_id, locator=locator,
                                     scope=scope, source_kind=source_kind, derived_from=derived_from,
                                     root_origins=sorted(roots), in_scope=bool(in_scope), valid_at=valid_at, recorded_at=now()))
            for parent_id in derived_from:
                self._edge(db, research_id, parent_id, node["id"], "derived_from")
            self._event(db, research_id, node["id"], "observe", node)
            return {**node, "duplicate": False}

    def hypothesize(self, research_id, subject, predicate, object, rationale, based_on=None, alternatives=None):
        with self.db() as db:
            working = self._research(db, research_id).get("method") == "working_model"
        if working:
            from .working import WorkingModel
            return WorkingModel(self).hypothesize(research_id, subject, predicate, object, rationale, based_on, alternatives)
        subject, predicate, object = (text(v, n, 1000) for v, n in
                                      [(subject, "subject"), (predicate, "predicate"), (object, "object")])
        rationale = text(rationale, "rationale")
        based_on, alternatives = sorted(set(based_on or [])), sorted(set(alternatives or []))
        with self.db(write=True) as db:
            self._research(db, research_id)
            for source in based_on:
                if self._node(db, research_id, source)["kind"] not in {"claim", "evidence"}:
                    raise ValueError("Hypothesis bases must be claims or evidence")
            for alternative in alternatives:
                self._node(db, research_id, alternative, "claim")
            fingerprint = digest([normalized(subject), normalized(predicate), normalized(object)])
            old = db.execute("SELECT id FROM nodes WHERE research_id=? AND kind='claim' AND fingerprint=?",
                             (research_id, fingerprint)).fetchone()
            if old:
                node = self._node(db, research_id, old["id"])
                if node["id"] in based_on + alternatives:
                    raise ValueError("A hypothesis cannot be its own basis or alternative")
                added_basis = set(based_on) - set(node["based_on"])
                added_alternatives = set(alternatives) - set(node["alternatives"])
                if not added_basis and not added_alternatives:
                    return {**node, "duplicate": True}
                node["based_on"] = sorted(set(node["based_on"]) | set(based_on))
                node["alternatives"] = sorted(set(node["alternatives"]) | set(alternatives))
                node["revision"] += 1
                self._save(db, node)
            else:
                node = self._insert(db, research_id, "claim", fingerprint,
                                    dict(subject=subject, predicate=predicate, object=object, rationale=rationale,
                                         based_on=based_on, alternatives=alternatives, status="proposed", supports=[],
                                         contradicts=[], counterevidence={}, resolutions={}, assessment_reason=""))
            for source in based_on:
                self._edge(db, research_id, source, node["id"], "suggested_by")
            for alternative in alternatives:
                self._edge(db, research_id, node["id"], alternative, "alternative")
                self._edge(db, research_id, alternative, node["id"], "alternative")
            for label, relation in [(subject, "subject"), (object, "object")]:
                fp = digest(normalized(label))
                term = db.execute("SELECT id FROM nodes WHERE research_id=? AND kind='term' AND fingerprint=?",
                                  (research_id, fp)).fetchone()
                term_id = term["id"] if term else self._insert(db, research_id, "term", fp, {"label": label})["id"]
                self._edge(db, research_id, term_id, node["id"], relation)
            self._event(db, research_id, node["id"], "hypothesize", node)
            return {**node, "duplicate": bool(old)}

    def assess(self, research_id, claim_id, status, reason, expected_revision,
               supports=None, contradicts=None, resolutions=None):
        with self.db() as db:
            if self._research(db, research_id).get("method") == "working_model":
                raise ValueError("Working-model status is derived from grounds; use WorkingModel.assess")
        reason = text(reason, "reason")
        if status not in {"proposed", "supported", "confirmed", "contested", "rejected", "unknown"}:
            raise ValueError("Unknown assessment status")
        supports, contradicts, resolutions = sorted(set(supports or [])), sorted(set(contradicts or [])), resolutions or {}
        if set(supports) & set(contradicts):
            raise ValueError("The same reference cannot both support and contradict in one assessment")
        with self.db(write=True) as db:
            self._research(db, research_id)
            claim = self._node(db, research_id, claim_id, "claim")
            if claim["revision"] != expected_revision:
                raise ValueError(f"Revision conflict: expected {expected_revision}, current {claim['revision']}; inspect and reconcile")
            counters = dict(claim["counterevidence"])
            counters.update({ref: True for ref in contradicts})
            old_resolutions = dict(claim["resolutions"])
            for ref, explanation in resolutions.items():
                if ref not in counters or ref in contradicts:
                    raise ValueError("Resolve only previously recorded counterevidence, excluding current contradictions")
                old_resolutions[ref] = text(explanation, "resolution")
            # Reintroduced counterevidence is active again, even if an earlier assessment resolved it.
            for ref in contradicts:
                old_resolutions.pop(ref, None)
            active_counters = sorted(set(counters) - set(old_resolutions))
            if set(supports) & set(active_counters):
                raise ValueError("Resolve prior counterevidence explicitly before using it as support")
            direct_primary = False
            # Validate the effective assessment, including counterclaims retained from history.
            # Otherwise omitting contradicts could silently revive a rejection with a stale premise.
            for ref_id in supports + active_counters:
                ref = self._node(db, research_id, ref_id)
                if ref_id == claim_id or ref_id in self._reachable(db, research_id, claim_id):
                    raise ValueError("Circular support or contradiction is not allowed")
                if ref["kind"] == "evidence":
                    if not ref["in_scope"]:
                        raise ValueError("Out-of-scope evidence cannot assess this research")
                    direct_primary |= ref_id in supports and ref["source_kind"] == "primary"
                elif ref["kind"] == "claim":
                    if ref["stale"] or ref["status"] not in {"supported", "confirmed"}:
                        raise ValueError("A premise must have a current supported or confirmed assessment")
                else:
                    raise ValueError("Assessment references must be evidence or claims")
            if status in {"supported", "confirmed"} and (not supports or active_counters):
                raise ValueError("Positive assessments require support and no unresolved counterevidence")
            if status == "confirmed" and not direct_primary:
                raise ValueError("Confirmed requires direct primary evidence; derived summaries and premises are insufficient")
            if status in {"contested", "rejected"} and not active_counters:
                raise ValueError("Contested/rejected requires explicit counterevidence; absence alone is unknown")
            next_fields = dict(status=status, supports=supports, contradicts=active_counters,
                               counterevidence=counters, resolutions=old_resolutions, assessment_reason=reason)
            if all(claim.get(k) == v for k, v in next_fields.items()) and not claim["stale"]:
                return {**claim, "duplicate": True, "invalidated": []}
            db.execute("DELETE FROM edges WHERE target=? AND relation IN ('supports','contradicts')", (claim_id,))
            for ref in supports:
                self._edge(db, research_id, ref, claim_id, "supports")
            for ref in active_counters:
                self._edge(db, research_id, ref, claim_id, "contradicts")
            claim.update(next_fields, revision=claim["revision"] + 1, stale=False)
            self._save(db, claim)
            invalidated = self._invalidate(db, research_id, claim_id)
            self._event(db, research_id, claim_id, "assess", {"assessment": claim, "invalidated": invalidated})
            return {**claim, "duplicate": False, "invalidated": invalidated}

    def check(self, research_id, action, request_key="", claim_ids=None, question="", method="", rationale="",
              check_id="", outcome="", evidence_ids=None, result=""):
        with self.db(write=True) as db:
            return self._check(db, research_id, action, request_key, claim_ids, question, method,
                               rationale, check_id, outcome, evidence_ids, result)

    def _check(self, db, research_id, action, request_key="", claim_ids=None, question="", method="", rationale="",
               check_id="", outcome="", evidence_ids=None, result="", requirement_keys=None):
        research = self._research(db, research_id)
        if action == "plan":
            if research.get("stop_protocol") and not db.execute("SELECT 1 FROM arv_contracts WHERE research_id=?", (research_id,)).fetchone():
                raise ValueError("Declare arv_contract before the first material check; no check has been saved")
            request_key, question = text(request_key, "request_key", 200), text(question, "question")
            method, rationale = text(method, "method"), text(rationale, "rationale")
            claim_ids = sorted(set(claim_ids or []))
            if not claim_ids:
                raise ValueError("A check needs at least one target claim")
            for claim_id in claim_ids:
                self._node(db, research_id, claim_id, "claim")
            data = dict(request_key=request_key, claim_ids=claim_ids, question=question, method=method,
                        rationale=rationale, status="planned", outcome="", evidence_ids=[], result="", planned_at=now())
            if requirement_keys is not None:
                data["requirement_keys"] = requirement_keys
            fp = digest(request_key)
            old = db.execute("SELECT id FROM nodes WHERE research_id=? AND kind='check' AND fingerprint=?", (research_id, fp)).fetchone()
            if old:
                existing = self._node(db, research_id, old["id"])
                if any(existing[k] != data[k] for k in ("claim_ids", "question", "method", "rationale")):
                    raise ValueError("Check request_key reused with different plan")
                if requirement_keys is not None and existing.get("requirement_keys") != requirement_keys:
                    raise ValueError("Check request_key reused with different requirement binding; use a new plan")
                return {**existing, "duplicate": True}
            count = db.execute("SELECT COUNT(*) FROM nodes WHERE research_id=? AND kind='check'", (research_id,)).fetchone()[0]
            if research["max_checks"] is not None and count >= research["max_checks"]:
                raise ValueError("Research check budget exhausted; preserve remaining unknowns")
            node = self._insert(db, research_id, "check", fp, data)
            for claim_id in claim_ids:
                self._edge(db, research_id, node["id"], claim_id, "tests")
        elif action in {"complete", "cancel"}:
            node = self._node(db, research_id, check_id, "check")
            result = text(result, "result")
            if action == "cancel":
                outcome = "cancelled"
            elif outcome not in {"found", "no_result", "unavailable", "error"}:
                raise ValueError("Outcome must be found, no_result, unavailable, or error")
            evidence_ids = sorted(set(evidence_ids or []))
            for evidence_id in evidence_ids:
                self._node(db, research_id, evidence_id, "evidence")
            if outcome == "found" and not evidence_ids:
                raise ValueError("A successful check needs recorded evidence")
            if outcome != "found" and evidence_ids:
                raise ValueError("Only found checks attach evidence; failures must be explicit")
            values = dict(status="cancelled" if action == "cancel" else "completed", outcome=outcome,
                          evidence_ids=evidence_ids, result=result)
            if node["status"] != "planned":
                if all(node[k] == v for k, v in values.items()):
                    return {**node, "duplicate": True}
                raise ValueError("Completed/cancelled checks are immutable; plan a new check")
            node.update(values, completed_at=now(), revision=node["revision"] + 1)
            self._save(db, node)
            for evidence_id in evidence_ids:
                self._edge(db, research_id, node["id"], evidence_id, "found")
        else:
            raise ValueError("Check action must be plan, complete, or cancel")
        self._event(db, research_id, node["id"], "check_" + action, node)
        return {**node, "duplicate": False}

    def inspect(self, research_id, view="frontier", focus_id="", limit=50, offset=0):
        if view not in {"frontier", "graph", "trace"} or not 1 <= limit <= 100 or offset < 0:
            raise ValueError("Use frontier/graph/trace; limit 1..100 and offset >= 0")
        with self.db() as db:
            research = self._research(db, research_id)
            rows = db.execute("SELECT id FROM nodes WHERE research_id=? ORDER BY rowid", (research_id,)).fetchall()
            nodes = [self._node(db, research_id, row["id"]) for row in rows]
            for node in nodes:
                if node["kind"] == "claim":
                    node["root_origins"] = sorted(self._roots(db, research_id, node["id"]))
                    node["independent_origin_count"] = len(node["root_origins"])
            checks = [node for node in nodes if node["kind"] == "check"]
            edges = [dict(row) for row in db.execute("SELECT source,target,relation FROM edges WHERE research_id=? ORDER BY rowid", (research_id,))]
            if focus_id:
                self._node(db, research_id, focus_id)
                relevant = {focus_id}
                relevant |= {e["source"] for e in edges if e["target"] == focus_id}
                relevant |= {e["target"] for e in edges if e["source"] == focus_id}
                nodes = [n for n in nodes if n["id"] in relevant]
            if view == "frontier":
                nodes = [n for n in nodes if (n["kind"] == "claim" and (n["stale"] or n["status"] in {"proposed", "unknown", "contested"}))
                         or (n["kind"] == "check" and n["status"] == "planned")]
            page = nodes[offset:offset + limit]
            page_ids = {n["id"] for n in page}
            response = dict(research=research, nodes=page, total_nodes=len(nodes),
                            next_offset=offset + limit if offset + limit < len(nodes) else None,
                            checks_used=len(checks), checks_remaining=(research["max_checks"] - len(checks)) if research["max_checks"] is not None else None,
                            pending_checks=[n["id"] for n in checks if n["status"] == "planned"],
                            edges=[e for e in edges if e["source"] in page_ids or e["target"] in page_ids],
                            assessment_boundary="Agent judgments with provenance; origin counts are not calibrated probabilities.")
            if view == "trace":
                query = "SELECT * FROM events WHERE research_id=?"
                args = [research_id]
                if focus_id:
                    query += " AND node_id=?"
                    args.append(focus_id)
                events = db.execute(query + " ORDER BY seq LIMIT ? OFFSET ?", (*args, limit + 1, offset)).fetchall()
                response["events"] = [{**dict(e), "data": json.loads(e["data"])} for e in events[:limit]]
                response["events_next_offset"] = offset + limit if len(events) > limit else None
            return response

    def finish(self, research_id, summary="", selected_claim_ids=None, unresolved_claim_ids=None,
               stop_reason="sufficient_evidence", candidate_id=""):
        # Existing v0.1/v0.2 records remain readable and retain their original semantics.
        # New research cannot opt out of the stopping protocol through a model argument.
        with self.db() as db:
            research = self._research(db, research_id)
        if research.get("method") == "working_model":
            from .working import WorkingModel
            return WorkingModel(self).finish(research_id, summary, selected_claim_ids)
        if research.get("stop_protocol"):
            from .stopping import Protocol
            if not candidate_id:
                raise ValueError("A frozen candidate and independent reviewer are required; use arv_freeze then arv_stop_status")
            return Protocol(self).finish(research_id, candidate_id)
        return self._legacy_finish(research_id, summary, selected_claim_ids, unresolved_claim_ids, stop_reason)

    def _conclusion(self, db, research_id, summary, selected_claim_ids, unresolved_claim_ids):
        summary = text(summary, "summary", 30000)
        selected, unresolved = set(selected_claim_ids or []), set(unresolved_claim_ids or [])
        if selected & unresolved:
            raise ValueError("Selected and unresolved claims must be disjoint")
        rows = db.execute("SELECT id FROM nodes WHERE research_id=? AND kind='claim'", (research_id,)).fetchall()
        claims = {r["id"]: self._node(db, research_id, r["id"]) for r in rows}
        if (selected | unresolved) - set(claims):
            raise ValueError("Conclusion references unknown claims")
        weak = {key for key, c in claims.items() if c["stale"] or c["status"] in {"proposed", "contested", "unknown"}}
        if weak - unresolved:
            raise ValueError("Disclose all unresolved/stale claims: " + ",".join(sorted(weak - unresolved)))
        closure, pending = set(), list(selected)
        while pending:
            key = pending.pop()
            if key in closure:
                continue
            closure.add(key)
            c = claims[key]
            if c["stale"] or c["status"] not in {"supported", "confirmed"}:
                raise ValueError("Only current supported/confirmed claims can enter the selected model")
            pending.extend(ref for ref in c["supports"] if ref in claims)
        for key in closure:
            alternatives = {r["target"] for r in db.execute("SELECT target FROM edges WHERE source=? AND relation='alternative'", (key,))}
            if alternatives & closure:
                raise ValueError("Mutually exclusive alternatives cannot enter one selected model")
        checks = [self._node(db, research_id, r["id"]) for r in db.execute("SELECT id FROM nodes WHERE research_id=? AND kind='check'", (research_id,))]
        if any(c["status"] == "planned" for c in checks):
            raise ValueError("Complete or cancel pending checks before concluding")
        return dict(summary=summary, selected_claim_ids=sorted(selected), premise_claim_ids=sorted(closure - selected),
                    unresolved_claim_ids=sorted(unresolved))

    def _legacy_finish(self, research_id, summary, selected_claim_ids, unresolved_claim_ids, stop_reason):
        if stop_reason not in {"sufficient_evidence", "no_accessible_sources", "budget_exhausted", "cancelled"}:
            raise ValueError("Unknown stop_reason")
        with self.db(write=True) as db:
            research = self._research(db, research_id)
            conclusion = self._conclusion(db, research_id, summary, selected_claim_ids, unresolved_claim_ids)
            checks = [self._node(db, research_id, r["id"]) for r in db.execute("SELECT id FROM nodes WHERE research_id=? AND kind='check'", (research_id,))]
            if stop_reason == "budget_exhausted":
                if research["max_checks"] is None:
                    raise ValueError("This research has no fixed check budget; conclude by evidence sufficiency or unavailable sources")
                if len(checks) < research["max_checks"]:
                    raise ValueError("The check budget has not been exhausted")
            if stop_reason == "sufficient_evidence" and (not selected_claim_ids or not any(c["outcome"] == "found" for c in checks)):
                raise ValueError("Sufficient evidence requires selected claims and at least one completed evidence-producing check")
            conclusion.update(stop_reason=stop_reason, completion_state="legacy_unverified")
            if research["status"] == "concluded" and research["conclusion"] == conclusion:
                return {**research, "duplicate": True}
            research.update(status="concluded", conclusion=conclusion)
            self._save_research(db, research)
            self._event(db, research_id, None, "finish", conclusion)
            return {**research, "duplicate": False}
