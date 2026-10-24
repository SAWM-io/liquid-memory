import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from demo import SyntheticCloud
from memory import WorldMemory


class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "memory.json"
        self.cloud = SyntheticCloud()
        self.memory = WorldMemory(self.cloud, self.path, self.cloud.space_id)
        self.memory.create_world("house")
        self.memory.create_world("mission")

    def write(self, **changes):
        args = dict(world="house", key="cup.location", content="The cup is in the kitchen.",
                    source="synthetic:user-statement", operation_id="op-1")
        args.update(changes)
        return self.memory.record_fact(**args)

    def test_uncertain_write_replays_exact_request_after_restart(self):
        original = self.cloud.write_assertion
        def lose_receipt(*args, **kwargs):
            original(*args, **kwargs)
            raise TimeoutError("response lost after server commit")
        self.cloud.write_assertion = lose_receipt
        with self.assertRaises(TimeoutError):
            self.write()
        self.assertEqual(self.memory.history("house", "cup.location"), [])
        self.assertEqual(self.memory.resume("house")["pending_operations"], ["op-1"])
        frozen = json.loads(self.path.read_text())["operations"]
        self.memory = WorldMemory(self.cloud, self.path, self.cloud.space_id)
        with self.assertRaisesRegex(ValueError, "changed input"):
            self.write(content="A different statement.")
        with self.assertRaisesRegex(ValueError, "pending operation"):
            self.write(operation_id="op-2")
        self.cloud.write_assertion = original
        result = self.write()
        self.assertEqual(self.cloud.requests[0], self.cloud.requests[1])
        self.assertEqual(result["body"], next(iter(frozen.values()))["body"])
        self.assertEqual(len(self.cloud.rows), 1)
        self.assertEqual(self.write(), result)
        self.assertEqual(len(self.cloud.requests), 2)

    def test_receipt_required_before_confirmation(self):
        self.cloud.write_assertion = lambda *a, **kw: {"status": "pending"}
        with self.assertRaisesRegex(ValueError, "Invalid assertion receipt"):
            self.write()
        self.assertFalse(self.memory.history("house", "cup.location"))
        self.assertEqual(self.memory.resume("house")["pending_operations"], ["op-1"])

    def test_wrong_receipt_scope_remains_pending(self):
        original = self.cloud.write_assertion
        self.cloud.write_assertion = lambda *a, **kw: dict(original(*a, **kw), entity_id="another-world")
        with self.assertRaisesRegex(ValueError, "mismatch"):
            self.write()
        self.assertFalse(self.memory.history("house", "cup.location"))

    def test_revision_history_provenance_and_world_separation(self):
        initial = self.write(expected_revision=0)
        revised = self.write(content="The cup is on the shelf.", operation_id="op-2", expected_revision=1)
        mission = self.write(world="mission", content="The mission cup is packed.")
        self.assertEqual(initial["body"]["claim_key"], revised["body"]["claim_key"])
        self.assertNotEqual(initial["body"]["candidate_id"], revised["body"]["candidate_id"])
        self.assertNotEqual(initial["body"]["claim_key"], mission["body"]["claim_key"])
        self.assertEqual([op["receipt"]["revision"] for op in self.memory.history("house", "cup.location")], [1, 2])
        self.assertTrue(revised["body"]["declared_revision"])
        self.assertEqual(revised["body"]["reason"], "Application-confirmed revision of cup.location")
        self.assertEqual(initial["body"]["evidence"], initial["input"]["source"])
        self.assertEqual(initial["body"]["provenance_key"], revised["body"]["provenance_key"])
        self.assertNotIn("known_at_ms", revised["body"])
        self.assertNotIn("expected_revision", revised["body"])
        self.assertEqual(self.memory.resume("house")["known_facts"]["cup.location"], revised)
        self.assertEqual(len(self.memory.recall("mission", "cup")["evidence"]), 1)
        with self.assertRaisesRegex(ValueError, "Local revision conflict"):
            self.write(operation_id="op-3", expected_revision=1)
        with self.assertRaisesRegex(ValueError, "Unknown"):
            self.memory.recall("unregistered", "anything")

    def test_unverified_or_wrong_scope_evidence_is_rejected(self):
        self.write()
        original = self.cloud.recall_tsst
        for field, value in (("entity_id", "wrong"), ("memory_space_id", "wrong")):
            def wrong(*args, **kwargs):
                result = original(*args, **kwargs)
                result[field] = value
                return result
            self.cloud.recall_tsst = wrong
            with self.assertRaisesRegex(ValueError, "mismatch"):
                self.memory.recall("house", "cup")
        self.cloud.recall_tsst = original
        self.cloud.rows[0]["entity_id"] = "another-world"
        self.cloud.recall_tsst = lambda *a, **kw: dict(original(*a, **kw), evidence=self.cloud.rows)
        with self.assertRaisesRegex(ValueError, "mismatch"):
            self.memory.recall("house", "cup")
        self.cloud.rows[0]["entity_id"] = self.memory.worlds()["house"]
        self.cloud.recall_tsst = original
        self.cloud.rows[0]["integrity_verified"] = False
        with self.assertRaisesRegex(ValueError, "Unverified"):
            self.memory.recall("house", "cup")

    def test_flashback_must_be_explicit_and_never_falls_back(self):
        self.write(valid_time_ms=100)
        self.assertTrue(self.memory.recall("house", "cup", at_ms=100)["flashback"])
        self.cloud.flashback_tsst = lambda *a, **kw: self.cloud.recall_tsst("cup", entity_id=kw["entity_id"], limit=10)
        with self.assertRaisesRegex(ValueError, "envelope"):
            self.memory.recall("house", "cup", at_ms=100)

    def test_size_and_confidence_validation_without_truncation(self):
        for changes in ({"content": "x" * 1201}, {"source": "x" * 1001},
                        {"content": "First.\nSecond."}, {"confidence": float("nan")},
                        {"confidence": True}, {"confidence": 2}, {"epistemic_status": "certain"}):
            with self.assertRaises(ValueError):
                self.write(**changes)
        self.assertEqual(self.cloud.requests, [])

    def test_unavailable_odvl_is_not_zero_and_false_write_flag_is_valid(self):
        original = self.cloud.write_assertion
        def reaffirm(*args, **kwargs):
            return dict(original(*args, **kwargs), odvl_applied=False)
        self.cloud.write_assertion = reaffirm
        self.assertFalse(self.write()["receipt"]["odvl_applied"])
        result = self.memory.observe("house")
        self.assertFalse(result["available"])
        self.assertEqual(result["observations"], [])
        self.assertNotIn("resonance", result)

    def test_old_uncertain_write_requires_reconciliation_not_replay(self):
        self.cloud.write_assertion = lambda *a, **kw: {"status": "pending"}
        with self.assertRaises(ValueError):
            self.write()
        data = json.loads(self.path.read_text())
        next(iter(data["operations"].values()))["started_at_ms"] -= WorldMemory.RETRY_WINDOW_MS
        self.path.write_text(json.dumps(data))
        with self.assertRaisesRegex(RuntimeError, "reconcile"):
            self.write()
        self.assertFalse(self.memory.history("house", "cup.location"))

    def test_old_uncertain_creation_does_not_create_a_second_world(self):
        self.cloud.create_entity = lambda *a, **kw: {}
        with self.assertRaises(ValueError):
            self.memory.create_world("new-world")
        data = json.loads(self.path.read_text())
        data["worlds"]["new-world"]["started_at_ms"] -= WorldMemory.RETRY_WINDOW_MS
        self.path.write_text(json.dumps(data))
        with self.assertRaisesRegex(RuntimeError, "reconcile"):
            self.memory.create_world("new-world")
        self.assertNotIn("new-world", self.memory.worlds())

    def test_old_confirmed_memories_remain_available(self):
        self.write()
        data = json.loads(self.path.read_text())
        for item in list(data["worlds"].values()) + list(data["operations"].values()):
            item["started_at_ms"] = 1
        self.path.write_text(json.dumps(data))
        self.memory = WorldMemory(self.cloud, self.path, self.cloud.space_id)
        self.assertEqual(self.memory.resume("house")["known_facts"]["cup.location"]["status"], "confirmed")
        self.write()
        self.assertEqual(len(self.cloud.requests), 1)

    def test_exclusive_lock_and_space_mismatch(self):
        lock = self.path.with_suffix(".json.lock")
        lock.write_text("a writer or a stale lock")
        with self.assertRaisesRegex(RuntimeError, "locked"):
            self.memory.worlds()
        self.assertTrue(lock.exists())
        lock.unlink()
        with self.assertRaisesRegex(ValueError, "space mismatch"):
            WorldMemory(self.cloud, self.path, "another-space")


if __name__ == "__main__":
    unittest.main()
