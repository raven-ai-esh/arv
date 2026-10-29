"""The user-facing abduction loop, without the historical proof/holdout gate."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from arv.store import Store
from arv.working import WorkingModel


class WorkingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "graph.sqlite3"
        self.store = Store(self.path)
        self.w = WorkingModel(self.store)
        self.rid = self.w.begin("Understand this dataset", "dataset:a", "working")["id"]

    def tearDown(self):
        self.temp.cleanup()

    def fact(self, content, key, **extra):
        return self.store.observe(self.rid, content, "fixture://observations", "observations:a", key, "dataset:a", **extra)

    def hypothesis(self, basis, same_as="", **extra):
        return self.w.hypothesize(self.rid, "Dataset", "has", "Signal cluster", "The observed readings suggest a shared signal",
                                 [b["id"] for b in basis], same_as=same_as, **extra)

    def test_two_distinct_recordings_strengthen_the_same_hypothesis(self):
        a = self.fact("Channel A records a recurring pulse", "channels:A")
        b = self.fact("Channel B independently records a recurring pulse", "channels:B")
        first = self.hypothesis([a])
        second = self.hypothesis([b])
        self.assertEqual(first["id"], second["id"])
        self.assertGreater(second["plausibility"]["support"], first["plausibility"]["support"])
        self.assertEqual(second["plausibility"]["observation_count"], 2)
        self.assertEqual(second["status"], "supported")
        self.assertEqual(second["plausibility"]["band"], "reinforced")
        self.assertIn(second["id"], self.w.model(self.rid)["suggested_claim_ids"])

    def test_copy_and_derived_retelling_do_not_strengthen_a_fact(self):
        a = self.fact("Channel A records a recurring pulse", "channels:A")
        first = self.hypothesis([a])
        copy = self.store.observe(self.rid, a["content"], "fixture://copy", a["origin_id"], a["locator"], "dataset:a")
        self.assertEqual(copy["id"], a["id"])
        derived = self.store.observe(self.rid, "Signals probably exist", "agent://summary", "summary", "line:1", "dataset:a",
                                     source_kind="derived", derived_from=[a["id"]])
        again = self.hypothesis([copy, derived])
        self.assertEqual(again["plausibility"]["support"], first["plausibility"]["support"])
        self.assertEqual(again["plausibility"]["observation_count"], 1)

    def test_retelling_cannot_promote_a_weak_fact_without_explicit_reassessment(self):
        a = self.fact("A repeated instrument pulse", "channels:A")
        first = self.hypothesis([a], strength="weak")
        summary = self.store.observe(self.rid, "The readings suggest a shared signal", "agent://summary", "summary", "1", "dataset:a", source_kind="derived", derived_from=[a["id"]])
        again = self.hypothesis([summary], strength="strong")
        self.assertEqual(again["plausibility"]["support"], first["plausibility"]["support"])
        changed = self.w.assess(self.rid, again["id"], [a["id"]], "support", "moderate", "The pattern is explicit in the recording", again["revision"])
        self.assertGreater(changed["plausibility"]["support"], first["plausibility"]["support"])

    def test_semantic_reuse_keeps_one_claim_and_retains_wording(self):
        a = self.fact("Channel A records a recurring pulse", "channels:A")
        b = self.fact("Channel B independently records a recurring pulse", "channels:B")
        first = self.hypothesis([a])
        merged = self.w.hypothesize(self.rid, "Pulse group", "exists_in", "Dataset", "Equivalent measurement relation",
                                   [b["id"]], same_as=first["id"])
        self.assertEqual(first["id"], merged["id"])
        self.assertTrue(merged["aliases"])
        self.assertEqual(len(self.w.model(self.rid)["claims"]), 1)
        self.assertEqual(merged["plausibility"]["observation_count"], 2)

    def test_existing_semantic_duplicates_merge_with_dependent_references(self):
        a = self.fact("Channel A records a recurring pulse", "channels:A")
        b = self.fact("Channel B records the recurring pulse", "channels:B")
        first = self.hypothesis([a])
        second = self.w.hypothesize(self.rid, "Pulse group", "exists_in", "Dataset", "Same measurement interpretation", [b["id"]])
        child = self.w.hypothesize(self.rid, "Pulse group", "contributes_to", "Recorded event", "Related inference", [second["id"]])
        merged = self.w.merge(self.rid, first["id"], second["id"], "Equivalent shared-signal interpretation statements", first["revision"], second["revision"])
        model = self.w.model(self.rid)
        self.assertEqual(merged["plausibility"]["observation_count"], 2)
        self.assertNotIn(second["id"], [c["id"] for c in model["claims"]])
        saved_child = next(c for c in model["claims"] if c["id"] == child["id"])
        self.assertEqual(saved_child["supports"], [first["id"]])
        retry = self.w.hypothesize(self.rid, "Pulse group", "exists_in", "Dataset", "Reuse merged wording", [b["id"]])
        self.assertEqual(retry["id"], first["id"])
        self.assertEqual(retry["plausibility"]["observation_count"], 2)

    def test_adopted_unit_rule_without_extra_certificate(self):
        rule = self.w.assume(self.rid, "Interpret U as centimetres", "user_rule", "User-supplied unit convention", "strong")
        raw = self.fact("R-7 raw length is 7 U", "R-7:raw")
        length = self.w.hypothesize(self.rid, "R-7", "length_cm", "7", "Apply convention", [rule["id"], raw["id"]])
        self.assertEqual(length["status"], "supported")
        self.assertEqual(length["plausibility"]["band"], "by_convention")
        result = self.w.finish(self.rid, "Provisional length is 7 cm", [length["id"]])
        self.assertEqual(result["status"], "concluded")
        self.assertEqual(result["conclusion"]["completion_state"], "working_model")
        self.assertEqual(result["conclusion"]["assumptions"][0]["kind"], "user_rule")
        self.assertNotIn("review_id", result["conclusion"])

    def test_explicit_calibration_revises_length_and_dependent_model(self):
        rule = self.w.assume(self.rid, "Interpret U as centimetres", "user_rule", "User convention", "strong")
        raw = self.fact("R-7 raw length is 7 U", "R-7:raw")
        length = self.w.hypothesize(self.rid, "R-7", "length_cm", "7", "Apply convention", [rule["id"], raw["id"]])
        fit = self.w.hypothesize(self.rid, "R-7", "fits", "10 cm slot", "Depends on length", [length["id"]])
        self.w.finish(self.rid, "Rod fits", [length["id"], fit["id"]])
        counter = self.fact("Calibration gives U=2 cm; R-7 length is 14 cm", "R-7:calibration")
        changed = self.w.assess(self.rid, length["id"], [counter["id"]], "oppose", "strong", "Documented contrary scale", length["revision"])
        model = self.w.model(self.rid)
        self.assertLess(changed["plausibility"]["balance"], 0)
        self.assertNotIn(length["id"], model["suggested_claim_ids"])
        self.assertNotIn(fit["id"], model["suggested_claim_ids"])
        self.assertEqual(model["research"]["status"], "active")
        self.assertIsNone(model["research"]["conclusion"])
        self.assertIn(counter["id"], changed["contradicts"])

    def test_unsupported_premise_cannot_be_silently_dropped_when_another_basis_survives(self):
        rule = self.w.assume(self.rid, "Interpret U as centimetres", "user_rule", "User convention", "strong")
        raw = self.fact("R-7 raw length is 7 U", "R-7:raw")
        count = self.fact("There are 12 identical rods", "batch:count")
        length = self.w.hypothesize(self.rid, "R-7", "length_cm", "7", "Apply convention", [raw['id'], rule['id']])
        fit = self.w.hypothesize(self.rid, "All 12 rods", "fit", "10 cm slots", "Length and count premise", [length['id'], count['id']])
        counter = self.fact("Calibration gives length 14 cm", "R-7:calibration")
        self.w.assess(self.rid, length['id'], [counter['id']], "oppose", "strong", "Old scale contradicted", length['revision'])
        self.assertNotIn(fit['id'], self.w.model(self.rid)['suggested_claim_ids'])
        with self.assertRaisesRegex(ValueError, 'premise|support'):
            self.w.finish(self.rid, "All rods fit", [fit['id']])

    def test_defeated_opposing_claim_does_not_become_a_required_premise(self):
        a = self.fact("Instrument log identifies an internal timing drift","instrument-log")
        b = self.fact("An old note suggests an external disturbance","old-note")
        target = self.w.hypothesize(self.rid,"Signal","are","instrument drift","Instrument log",[a['id']],strength='strong')
        rival = self.w.hypothesize(self.rid,"Signal","are","external disturbance","Old clue",[b['id']],strength='weak')
        target = self.w.assess(self.rid,target['id'],[rival['id']],'oppose','weak','Competing account',target['revision'])
        correction = self.fact("Current calibration record explicitly rejects that external disturbance","correction")
        self.w.assess(self.rid,rival['id'],[correction['id']],'oppose','strong','Current direct correction',rival['revision'])
        self.assertIn(target['id'],self.w.model(self.rid)['suggested_claim_ids'])
        result = self.w.finish(self.rid,"Instrument drift remains the best working picture",[target['id']])
        self.assertEqual(result['status'],'concluded')

    def test_ordinary_domain_default_can_enter_a_working_model(self):
        prior = self.w.assume(self.rid, "Instrument stations often need calibration", "domain_prior", "Ordinary research model", "weak")
        c = self.w.hypothesize(self.rid, "Instrument station", "depends_on", "calibration", "Working default; exact metrics remain to be learned", [prior["id"]])
        self.assertEqual(c["status"], "supported")
        self.assertEqual(c["plausibility"]["band"], "working_default")
        self.assertIn(c["id"], self.w.model(self.rid)["suggested_claim_ids"])

    def test_multiple_prior_statements_are_not_multiple_observations(self):
        a = self.w.assume(self.rid, "Instrument stations often need calibration", "domain_prior", "Ordinary structure", "weak")
        b = self.w.assume(self.rid, "Readings often depend on calibration", "domain_prior", "Related prior", "weak")
        c = self.hypothesis([a])
        d = self.hypothesis([b])
        self.assertEqual(c["plausibility"]["support"], d["plausibility"]["support"])
        self.assertEqual(d["plausibility"]["observation_count"], 0)

    def test_consistent_model_excludes_rival_and_its_incompatible_premise(self):
        a = self.fact("A lab test identifies a detector artefact", "a")
        b = self.fact("A field note suggests an external flash", "b")
        internal = self.w.hypothesize(self.rid, "Observed pattern", "explained_by", "Detector artefact", "Laboratory observation", [a["id"]], strength="strong")
        outside = self.w.hypothesize(self.rid, "Observed pattern", "explained_by", "External flash", "Rival arrangement", [b["id"]], alternatives=[internal["id"]], strength="weak")
        model = self.w.model(self.rid)
        self.assertIn(internal["id"], model["suggested_claim_ids"])
        self.assertNotIn(outside["id"], model["suggested_claim_ids"])
        with self.assertRaisesRegex(ValueError, "exclusive"):
            self.w.finish(self.rid, "Both arrangements", [internal["id"], outside["id"]])

    def test_a_high_scoring_descendant_does_not_revive_the_weaker_rival(self):
        a = self.fact("A direct lab record identifies detector artefact", "a")
        b = self.fact("A weak field clue suggests an external flash", "b")
        c = self.fact("A different useful observation", "c")
        internal = self.w.hypothesize(self.rid, "Observed pattern", "explained_by", "Detector artefact", "Direct source", [a["id"]], strength="strong")
        outside = self.w.hypothesize(self.rid, "Observed pattern", "explained_by", "External flash", "Weak rival", [b["id"]], alternatives=[internal["id"]], strength="weak")
        child = self.w.hypothesize(self.rid, "External flash", "explains", "Illumination change", "Dependent inference plus another fact", [outside["id"], c["id"]], strength="strong")
        self.assertGreater(child["plausibility"]["support"], internal["plausibility"]["support"])
        selected = self.w.model(self.rid)["suggested_claim_ids"]
        self.assertIn(internal["id"], selected)
        self.assertNotIn(outside["id"], selected)
        self.assertNotIn(child["id"], selected)

    def test_many_weak_signals_do_not_outvote_a_strong_counterfact(self):
        first = self.fact("A pulse pattern suggests a shared signal", "weak:0")
        c = self.hypothesis([first], strength="weak")
        for i in range(1, 6):
            c = self.hypothesis([self.fact("Another indirect pattern clue "+str(i),"weak:"+str(i))],strength="weak")
        counter = self.fact("A current calibration record explicitly rejects the proposed offset", "direct-counter")
        c = self.w.assess(self.rid,c["id"],[counter["id"]],"oppose","strong","Direct counterfact is more diagnostic than repeated weak clues",c["revision"])
        self.assertLess(c["plausibility"]["balance"],0)
        self.assertNotIn(c["id"],self.w.model(self.rid)["suggested_claim_ids"])

    def test_circular_support_and_cross_scope_fail_without_mutation(self):
        e = self.fact("Channel A pulse", "a")
        a = self.hypothesis([e])
        b = self.w.hypothesize(self.rid, "Signal", "has", "Sensor", "Related observation", [a["id"]])
        with self.assertRaisesRegex(ValueError, "Circular"):
            self.w.assess(self.rid, a["id"], [b["id"]], "support", "strong", "Would be a circle", a["revision"])
        other = self.store.observe(self.rid, "Other subject", "fixture://other", "other", "1", "dataset:b")
        with self.assertRaisesRegex(ValueError, "scope"):
            self.hypothesis([other])
        self.assertEqual(self.w.model(self.rid)["claims"][0]["plausibility"]["observation_count"], 1)

    def test_revision_and_retirement_preserve_history(self):
        a = self.fact("Pulse from channel A", "a")
        c = self.hypothesis([a])
        n = self.fact("An explicit contradiction", "n")
        changed = self.w.assess(self.rid, c["id"], [n["id"]], "oppose", "weak", "Some contrary evidence", c["revision"])
        with self.assertRaisesRegex(ValueError, "Revision"):
            self.w.assess(self.rid, c["id"], [n["id"]], "withdraw", "weak", "Old note superseded", c["revision"])
        updated = self.w.assess(self.rid, c["id"], [n["id"]], "withdraw", "weak", "Old note superseded by a later agreement", changed["revision"])
        self.assertFalse(updated["signals"][n["id"]]["active"])
        trace = self.store.inspect(self.rid, "trace")
        self.assertTrue(any(e["operation"] == "working_assess" for e in trace["events"]))
        self.assertIn("Old note superseded", json.dumps(trace, ensure_ascii=False))

    def test_persistence_and_identical_retry_do_not_change_strength(self):
        e = self.fact("Pulse from channel A", "a")
        c = self.hypothesis([e])
        self.assertTrue(self.hypothesis([e])["duplicate"])
        self.assertEqual(self.hypothesis([e])["revision"], c["revision"])
        restarted = WorkingModel(Store(self.path))
        self.assertEqual(restarted.model(self.rid)["claims"][0]["plausibility"], c["plausibility"])
        self.assertEqual(restarted.begin("Understand this dataset", "dataset:a", "working")["id"], self.rid)
        with self.assertRaisesRegex(ValueError, "different"):
            restarted.begin("A different question", "dataset:a", "working")

    def test_optional_check_failure_is_not_source_absence_and_can_be_cancelled(self):
        c = self.hypothesis([self.fact("Pulse from channel A", "a")])
        q = self.store.check(self.rid, "plan", "check", [c["id"]], "Does the note explain this?", "Read note", "Could revise the relation")
        with self.assertRaisesRegex(ValueError, "pending"):
            self.w.finish(self.rid, "A working picture")
        self.store.check(self.rid, "complete", check_id=q["id"], outcome="error", result="Source request failed")
        result = self.w.finish(self.rid, "Working picture with an unresolved access attempt")
        self.assertEqual(result["conclusion"]["checks"][0]["outcome"], "error")


if __name__ == "__main__":
    unittest.main()
