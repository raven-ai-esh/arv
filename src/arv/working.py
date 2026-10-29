"""Abductive working models: accumulate distinct grounds, preserve their meaning.

Weights are ordinal relevance judgments, not measured probabilities. The agent
supplies semantic equivalence and relevance; the graph handles deduplication,
propagation, consistency and an inspectable history.
"""
from __future__ import annotations

from copy import deepcopy
from .store import canonical, digest, normalized, now, text

STRENGTH = {"weak": 1, "moderate": 2, "strong": 3}


class WorkingModel:
    def __init__(self, store):
        self.store = store

    def begin(self, goal, scope, request_key, max_checks=None, actor="local-researcher"):
        return self.store.begin(goal, scope, request_key, max_checks, actor, method="working_model")

    def _research(self, db, rid):
        r = self.store._research(db, rid)
        if r.get("method") != "working_model":
            raise ValueError("This is a historical validation research; its method is preserved")
        return r

    def _nodes(self, db, rid):
        return {row["id"]: self.store._node(db, rid, row["id"])
                for row in db.execute("SELECT id FROM nodes WHERE research_id=? ORDER BY rowid", (rid,))}

    @staticmethod
    def _weight(strength):
        if strength not in STRENGTH:
            raise ValueError("Use weak, moderate or strong relevance")
        return STRENGTH[strength]

    def assume(self, rid, statement, kind, reason, strength="weak"):
        statement, reason = text(statement, "statement"), text(reason, "reason")
        if kind not in {"user_rule", "domain_prior"}:
            raise ValueError("Assumptions are user_rule or domain_prior, never primary observations")
        self._weight(strength)
        with self.store.db(write=True) as db:
            self._research(db, rid)
            fp = digest([kind, normalized(statement)])
            old = db.execute("SELECT id FROM nodes WHERE research_id=? AND kind='assumption' AND fingerprint=?", (rid, fp)).fetchone()
            if old:
                return {**self.store._node(db, rid, old["id"]), "duplicate": True}
            n = self.store._insert(db, rid, "assumption", fp, dict(statement=statement, assumption_kind=kind,
                    reason=reason, strength=strength, recorded_at=now()))
            self.store._event(db, rid, n["id"], "assume", n)
            return {**n, "duplicate": False}

    def _basis(self, db, rid, ids):
        out = []
        for key in sorted(set(ids or [])):
            n = self.store._node(db, rid, key)
            while n.get("merged_into"):
                n = self.store._node(db, rid, n["merged_into"], "claim")
            if n["kind"] not in {"claim", "evidence", "assumption"}:
                raise ValueError("A basis must be an observation, hypothesis or declared assumption")
            if n["kind"] == "evidence" and not n["in_scope"]:
                raise ValueError("Out-of-scope evidence cannot support this model")
            out.append(n["id"])
        return sorted(set(out))

    def hypothesize(self, rid, subject, predicate, object, rationale, based_on=None,
                    alternatives=None, same_as="", strength="moderate"):
        subject, predicate, object = (text(v, k, 1000) for v, k in [(subject, "subject"), (predicate, "predicate"), (object, "object")])
        rationale = text(rationale, "rationale")
        self._weight(strength)
        with self.store.db(write=True) as db:
            self._research(db, rid)
            basis = self._basis(db, rid, based_on)
            rivals = self._basis(db, rid, alternatives)
            for key in rivals:
                self.store._node(db, rid, key, "claim")
            fp = digest([normalized(subject), normalized(predicate), normalized(object)])
            old = db.execute("SELECT id FROM nodes WHERE research_id=? AND kind='claim' AND fingerprint=?", (rid, fp)).fetchone()
            canonical_old = self._basis(db, rid, [old["id"]])[0] if old else ""
            if same_as and canonical_old and canonical_old != same_as:
                raise ValueError("Equivalent wording already has another claim: use arv_merge to preserve both histories")
            old_id = same_as or canonical_old
            triple = dict(subject=subject, predicate=predicate, object=object)
            if old_id:
                n = self.store._node(db, rid, old_id, "claim")
                if n.get("merged_into"):
                    raise ValueError("Claim merged; reuse " + n["merged_into"])
                before = deepcopy(n)
            else:
                n = self.store._insert(db, rid, "claim", fp, dict(**triple, rationale=rationale,
                    based_on=[], alternatives=[], aliases=[], signals={}, status="proposed", supports=[],
                    contradicts=[], counterevidence={}, resolutions={}, assessment_reason=""))
                before = None
            if n["id"] in basis + rivals:
                raise ValueError("A hypothesis cannot support or oppose itself")
            if same_as and any(n[k] != triple[k] for k in triple) and triple not in n["aliases"]:
                n["aliases"].append(triple)
            n["based_on"] = sorted(set(n["based_on"]) | set(basis))
            n["alternatives"] = sorted(set(n["alternatives"]) | set(rivals))
            introduced = now()
            for key in basis:
                # Repeating a proposal cannot silently change an earlier assessment.
                if key not in n["signals"]:
                    n["signals"][key] = dict(effect="support", strength=strength, reason=rationale, active=True, introduced_at=introduced)
            if before and all(n[k] == before[k] for k in ("based_on", "alternatives", "aliases", "signals")):
                return {**n, "duplicate": True}
            if before:
                n["revision"] += 1
            self.store._save(db, n)
            for label, relation in [(subject, "subject"), (object, "object")]:
                tfp = digest(normalized(label))
                term = db.execute("SELECT id FROM nodes WHERE research_id=? AND kind='term' AND fingerprint=?", (rid, tfp)).fetchone()
                tid = term["id"] if term else self.store._insert(db, rid, "term", tfp, {"label": label})["id"]
                self.store._edge(db, rid, tid, n["id"], relation)
            for key in basis:
                self.store._edge(db, rid, key, n["id"], "suggested_by")
            self._refresh(db, rid)
            n = self.store._node(db, rid, n["id"])
            self.store._event(db, rid, n["id"], "working_hypothesize", n)
            return {**n, "duplicate": bool(before)}

    def assess(self, rid, claim_id, basis_ids, effect, strength, reason, expected_revision):
        reason = text(reason, "reason")
        self._weight(strength)
        if effect not in {"support", "oppose", "withdraw"}:
            raise ValueError("Use support, oppose or withdraw")
        with self.store.db(write=True) as db:
            self._research(db, rid)
            n = self.store._node(db, rid, claim_id, "claim")
            if n.get("merged_into"):
                raise ValueError("Claim merged; reuse " + n["merged_into"])
            if n["revision"] != expected_revision:
                raise ValueError("Revision conflict: inspect the current hypothesis")
            ids = self._basis(db, rid, basis_ids)
            if not ids:
                raise ValueError("An assessment needs actual basis IDs")
            if claim_id in ids:
                raise ValueError("Circular support is not allowed")
            for key in ids:
                if effect == "withdraw":
                    if key not in n["signals"]:
                        raise ValueError("Cannot withdraw an unknown basis")
                    n["signals"][key] = {**n["signals"][key], "active": False, "withdrawal_reason": reason}
                else:
                    introduced = n["signals"].get(key, {}).get("introduced_at", now())
                    n["signals"][key] = dict(effect=effect, strength=strength, reason=reason, active=True, introduced_at=introduced)
                    if effect == "oppose":
                        n["counterevidence"][key] = True
            n["revision"] += 1
            self.store._save(db, n)
            self._refresh(db, rid)
            n = self.store._node(db, rid, claim_id)
            self.store._event(db, rid, claim_id, "working_assess", dict(claim=n, effect=effect, reason=reason))
            return n

    def _profiles(self, nodes):
        memo = {}

        def profile(key, trail=()):
            if key in trail:
                raise ValueError("Circular support or contradiction is not allowed")
            if key in memo:
                return memo[key]
            n = nodes[key]
            if n.get("merged_into"):
                return profile(n["merged_into"], (*trail, key))
            positive, negative, priors, counterpriors, origins, blocked = {}, {}, {}, {}, set(), set()
            if n["kind"] == "evidence":
                if not n["in_scope"]:
                    raise ValueError("Out-of-scope evidence in working model")
                if n["source_kind"] == "primary":
                    positive[n["id"]] = 3
                    origins.update(n["root_origins"])
                else:
                    for parent in n["derived_from"]:
                        p = profile(parent, (*trail, key))
                        positive.update({k: max(v, positive.get(k, 0)) for k, v in p["facts"].items()})
                        origins.update(p["origins"])
            elif n["kind"] == "assumption":
                priors[key] = self._weight(n["strength"])
            elif n["kind"] == "claim":
                root_dates = {"support": {}, "oppose": {}}
                for basis, signal in sorted(n["signals"].items(), key=lambda item: (item[1].get("introduced_at", ""), item[0])):
                    if not signal["active"]:
                        continue
                    p = profile(basis, (*trail, key))
                    if nodes[basis]["kind"] == "claim" and p["balance"] <= 0:
                        if signal["effect"] == "support":
                            blocked.add(basis)
                        continue
                    dest, prior_dest = (positive, priors) if signal["effect"] == "support" else (negative, counterpriors)
                    cap = self._weight(signal["strength"])
                    for root, value in p["facts"].items():
                        # A new retelling is not a stronger observation. Reweight
                        # the original basis explicitly if its relevance changed.
                        dates = root_dates[signal["effect"]]
                        date = signal.get("introduced_at", "")
                        if root not in dest:
                            dest[root], dates[root] = min(value, cap), date
                        elif dates[root] == date:
                            dest[root] = max(dest[root], min(value, cap))
                    for root, value in p["priors"].items():
                        prior_dest[root] = max(prior_dest.get(root, 0), min(value, cap))
                    origins.update(p["origins"])
            else:
                raise ValueError("This node cannot ground a hypothesis")
            # Related defaults are a prior, not a pile of independent observations.
            # An observed counterfact cannot be outweighed by a stack of conventions.
            support = sorted([*positive.values(), *([max(priors.values())] if priors and not negative else [])], reverse=True)
            opposition = sorted([*negative.values(), *([max(counterpriors.values())] if counterpriors and not positive else [])], reverse=True)
            net = [support.count(tier)-opposition.count(tier) for tier in (3, 2, 1)]
            balance = next((v for v in net if v), 0)
            # A surviving measurement/other clue cannot silently replace a logical
            # premise that made the inference valid. The analyst must revisit it.
            if blocked and balance > 0:
                balance = 0
            band = ("premise_needs_revision" if blocked else "unassessed" if not support and not opposition else "undecided" if balance == 0 else
                    "less_likely" if balance < 0 else "favoured_with_counterevidence" if opposition else
                    "by_convention" if positive and any(nodes[k].get("assumption_kind") == "user_rule" for k in priors) else
                    "working_default" if not positive and priors else "reinforced" if len(positive) > 1 else "plausible")
            p = dict(facts=positive, counterfacts=negative, priors=priors, counterpriors=counterpriors,
                     origins=sorted(origins), blocked_premises=sorted(blocked), support=support,
                     opposition=opposition, balance=balance, net_relevance=net, observation_count=len(positive),
                     counter_observation_count=len(negative), band=band)
            memo[key] = p
            return p

        for n in nodes.values():
            if n["kind"] in {"claim", "assumption"} or n["kind"] == "evidence" and n["in_scope"]:
                profile(n["id"])
        return memo

    def merge(self, rid, keep_id, duplicate_id, reason, expected_keep_revision, expected_duplicate_revision):
        reason = text(reason, "reason")
        if keep_id == duplicate_id:
            raise ValueError("Merge needs two different claims")
        with self.store.db(write=True) as db:
            self._research(db, rid)
            nodes = self._nodes(db, rid)
            keep = self.store._node(db, rid, keep_id, "claim")
            duplicate = self.store._node(db, rid, duplicate_id, "claim")
            if keep.get("merged_into") or duplicate.get("merged_into"):
                raise ValueError("Use current canonical claims")
            if (keep["revision"], duplicate["revision"]) != (expected_keep_revision, expected_duplicate_revision):
                raise ValueError("Revision conflict: inspect both claims")
            before = dict(keep=deepcopy(keep), duplicate=deepcopy(duplicate))

            def combine(a, b):
                if a["active"] and b["active"] and a["effect"] != b["effect"]:
                    raise ValueError("Resolve conflicting interpretations of the same basis before merging")
                if not a["active"]:
                    return b
                if not b["active"]:
                    return a
                return a if self._weight(a["strength"]) >= self._weight(b["strength"]) else b

            for key, signal in duplicate["signals"].items():
                keep["signals"][key] = combine(keep["signals"][key], signal) if key in keep["signals"] else signal
            keep["aliases"] += [dict(subject=duplicate["subject"], predicate=duplicate["predicate"], object=duplicate["object"]), *duplicate["aliases"]]
            keep["based_on"] = sorted(set(keep["based_on"] + duplicate["based_on"]))
            keep["alternatives"] = sorted(set(keep["alternatives"] + duplicate["alternatives"]) - {keep_id, duplicate_id})
            keep["counterevidence"].update(duplicate["counterevidence"])
            nodes[keep_id] = keep
            duplicate.update(merged_into=keep_id, status="merged", merge_reason=reason, revision=duplicate["revision"]+1)
            nodes[duplicate_id] = duplicate
            for n in nodes.values():
                if n["kind"] != "claim" or n.get("merged_into"):
                    continue
                signals = {}
                for key, signal in n["signals"].items():
                    key = keep_id if key == duplicate_id else key
                    if key == n["id"]:
                        continue
                    signals[key] = combine(signals[key], signal) if key in signals else signal
                n["signals"] = signals
                n["based_on"] = sorted({keep_id if k == duplicate_id else k for k in n["based_on"]} - {n["id"]})
                n["alternatives"] = sorted({keep_id if k == duplicate_id else k for k in n["alternatives"]} - {n["id"]})
                n["revision"] += 1
                self.store._save(db, n)
            self.store._save(db, duplicate)
            self._refresh(db, rid)
            result = self.store._node(db, rid, keep_id)
            self.store._event(db, rid, keep_id, "working_merge", dict(reason=reason, before=before, result=result))
            return result

    def _refresh(self, db, rid):
        nodes = self._nodes(db, rid)
        profiles = self._profiles(nodes)
        db.execute("DELETE FROM edges WHERE research_id=? AND relation IN ('supports','contradicts','alternative')", (rid,))
        for n in nodes.values():
            if n["kind"] != "claim" or n.get("merged_into"):
                continue
            p = profiles[n["id"]]
            status = "supported" if p["balance"] > 0 else "rejected" if p["balance"] < 0 else "contested" if p["support"] else "proposed"
            supports = sorted(k for k, s in n["signals"].items() if s["active"] and s["effect"] == "support")
            counters = sorted(k for k, s in n["signals"].items() if s["active"] and s["effect"] == "oppose")
            fields = dict(plausibility=p, status=status, supports=supports, contradicts=counters, stale=False)
            if any(n.get(k) != v for k, v in fields.items()):
                n.update(fields, revision=n["revision"] + 1)
                self.store._save(db, n)
            for key in supports:
                self.store._edge(db, rid, key, n["id"], "supports")
            for key in counters:
                self.store._edge(db, rid, key, n["id"], "contradicts")
            for key in n["alternatives"]:
                self.store._edge(db, rid, n["id"], key, "alternative")
                self.store._edge(db, rid, key, n["id"], "alternative")

    def _model(self, db, rid):
        research = self._research(db, rid)
        nodes = self._nodes(db, rid)
        claims = [n for n in nodes.values() if n["kind"] == "claim" and not n.get("merged_into")]
        profiles = self._profiles(nodes)
        rivals = {n["id"]: set(n["alternatives"]) for n in claims}
        for key, ids in list(rivals.items()):
            for other in ids:
                rivals.setdefault(other, set()).add(key)

        def rank(key):
            p = profiles[key]
            return (*p["net_relevance"], -p["counter_observation_count"], p["observation_count"])

        def closure(keys):
            result, pending = set(), list(keys)
            while pending:
                key = pending.pop()
                if key in result:
                    continue
                n = nodes[key]
                if n.get("merged_into"):
                    pending.append(n["merged_into"])
                    continue
                if profiles[key]["balance"] <= 0:
                    raise ValueError("A selected premise has no current positive support")
                result.add(key)
                pending += [basis for basis, signal in n["signals"].items()
                            if signal["active"] and signal["effect"] == "support" and nodes[basis]["kind"] == "claim"]
            if any(rivals.get(key, set()) & result for key in result):
                raise ValueError("Mutually exclusive alternatives cannot enter one working model")
            return result

        tied = {n["id"] for n in claims for other in rivals[n["id"]]
                if profiles[n["id"]]["balance"] > 0 and profiles[other]["balance"] > 0 and rank(n["id"]) == rank(other)}
        weaker = {n["id"] for n in claims for other in rivals[n["id"]]
                  if profiles[other]["balance"] > 0 and rank(other) > rank(n["id"])}
        excluded = tied | weaker
        selected = set()
        for n in sorted(claims, key=lambda n: (*rank(n["id"]), n["id"]), reverse=True):
            if profiles[n["id"]]["balance"] <= 0 or n["id"] in excluded:
                continue
            try:
                proposed = closure(selected | {n["id"]})
            except ValueError:
                continue
            if not proposed & excluded:
                selected = proposed
        return dict(research=research, claims=claims, suggested_claim_ids=sorted(selected),
                    tied_alternatives=sorted(tied), assumptions=[n for n in nodes.values() if n["kind"] == "assumption"],
                    boundary="Ordinal relevance and distinct grounded observations, not calibrated probability or proof of reality."), closure

    def model(self, rid):
        with self.store.db() as db:
            return self._model(db, rid)[0]

    def finish(self, rid, summary, selected_claim_ids=None, open_questions=None):
        summary = text(summary, "summary", 30000)
        with self.store.db(write=True) as db:
            model, closure = self._model(db, rid)
            selected = set(model["suggested_claim_ids"] if selected_claim_ids is None else selected_claim_ids)
            if not selected:
                raise ValueError("Choose a nonempty working model; explain a choice if rivals tie")
            all_ids = {n["id"] for n in model["claims"]}
            if selected - all_ids:
                raise ValueError("Selected model references unknown or merged claims")
            chosen = closure(selected)
            nodes = self._nodes(db, rid)
            checks = [n for n in nodes.values() if n["kind"] == "check"]
            if any(n["status"] == "planned" for n in checks):
                raise ValueError("Complete or cancel pending checks before presenting the model")
            used_assumptions = set()
            for key in chosen:
                used_assumptions.update(nodes[key]["plausibility"]["priors"])
            conclusion = dict(summary=summary, selected_claim_ids=sorted(selected), premise_claim_ids=sorted(chosen-selected),
                model=[nodes[k] for k in sorted(chosen)],
                assumptions=[dict(id=k, statement=nodes[k]["statement"], kind=nodes[k]["assumption_kind"], reason=nodes[k]["reason"]) for k in sorted(used_assumptions)],
                unresolved_claim_ids=sorted(n["id"] for n in model["claims"] if n["id"] not in chosen and n["status"] != "rejected"),
                open_questions=open_questions or [], checks=checks, completion_state="working_model",
                stop_reason="most_plausible_working_model", boundary=model["boundary"])
            r = model["research"]
            if r["status"] == "concluded" and r["conclusion"] == conclusion:
                return {**r, "duplicate": True}
            r.update(status="concluded", conclusion=conclusion)
            self.store._save_research(db, r)
            self.store._event(db, rid, None, "finish", conclusion)
            return {**r, "duplicate": False}
