"""Offline by default. --cloud explicitly writes synthetic sample facts to Basira."""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

from memory import WorldMemory


class SyntheticCloud:
    """Deterministic in-process test fixture; NOT Basira or an alternative engine.

    It performs no semantic retrieval, integrity verification, or ODVL computation.
    Its integrity flags are fabricated fixtures for exercising response validation.
    """
    def __init__(self, space_id="synthetic-space"):
        self.space_id, self.receipts, self.rows, self.requests = space_id, {}, [], []

    def create_entity(self, entity_type, name, *, description="", idempotency_key):
        assert entity_type == "monde"
        return {"entity_id": "ent_" + hashlib.md5(name.encode(), usedforsecurity=False).hexdigest()}

    def write_assertion(self, assertion, *, entity_id, idempotency_key):
        self.requests.append(copy.deepcopy((assertion, entity_id, idempotency_key)))
        if idempotency_key not in self.receipts:
            revision = 1 + sum(row["claim_key"] == assertion["claim_key"] for row in self.rows)
            receipt = dict(status="completed", claim_key=assertion["claim_key"],
                           candidate_id=assertion["candidate_id"], revision=revision, odvl_applied=True)
            self.receipts[idempotency_key] = receipt
            self.rows.append(dict(assertion, entity_id=entity_id, revision=revision,
                                  evidence_id="fixture-" + str(len(self.rows)), integrity_verified=True))
        return copy.deepcopy(self.receipts[idempotency_key])

    def recall_tsst(self, query, *, entity_id, limit, epistemic=None):
        rows = [row for row in self.rows if row["entity_id"] == entity_id]
        return dict(schema="basira-tsst-evidence/v1", memory_space_id=self.space_id,
                    entity_id=entity_id, evidence=copy.deepcopy(rows[-limit:]), flashback=False)

    def flashback_tsst(self, query, *, as_of_valid_time_ms, entity_id, limit):
        result = self.recall_tsst(query, entity_id=entity_id, limit=limit)
        result["evidence"] = [row for row in result["evidence"]
                              if row["valid_time_ms"] <= as_of_valid_time_ms]
        result["flashback"] = True
        return result

    def odvl_observe(self, candidate_ids, *, entity_id):
        return dict(available=False, observations=[], reason="Synthetic fixture has no ODVL measurement")


def run(client, state, space):
    memory = WorldMemory(client, state, space)
    for world in ("house", "mission"):
        memory.create_world(world, "Synthetic long-term memory example")
    def record(world, key, content, op, revision, timestamp):
        return memory.record_fact(world, key, content, "synthetic:demo-script-v1", operation_id=op,
                                  expected_revision=revision, valid_time_ms=timestamp,
                                  belief_time_ms=timestamp, decision_time_ms=timestamp)
    record("house", "cup.location", "The cup is in the kitchen.", "house-cup-1", 0, 1_700_000_000_000)
    record("mission", "task.status", "The synthetic mission is waiting for review.", "mission-status-1", 0, 1_700_000_001_000)
    record("house", "cup.location", "The cup is on the shelf.", "house-cup-2", 1, 1_700_000_002_000)
    memory = WorldMemory(client, state, space)  # Simulate restarting the application wrapper.
    result = {"worlds": memory.worlds(), "return_to_house_local_checkpoint": memory.resume("house"),
              "local_confirmed_cup_receipt_history": memory.history("house", "cup.location"),
              "house_bounded_tsst_evidence": memory.recall("house", "Where is the cup?"),
              "house_tsst_flashback": memory.recall("house", "Where is the cup?", at_ms=1_700_000_001_000),
              "house_odvl_observation": memory.observe("house")}
    print(json.dumps(result, indent=2, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cloud", action="store_true", help="Write synthetic facts using the public Basira SDK")
    parser.add_argument("--state", type=Path, default=Path(".state/memory.json"), help="Cloud checkpoint path")
    args = parser.parse_args()
    if args.cloud:
        space, key = os.environ.get("BASIRA_SPACE"), os.environ.get("BASIRA_KEY")
        if not space or not key:
            parser.error("--cloud requires BASIRA_SPACE and BASIRA_KEY")
        sys.path.insert(0, str(Path(__file__).parent / "vendor"))
        from basira_client import BasiraClient
        print("CLOUD: writing synthetic example facts; no LLM or business actions are executed.")
        with BasiraClient(space, key) as cloud:
            run(cloud, args.state, space)
    else:
        print("OFFLINE SYNTHETIC FIXTURE: no Cloud calls, semantic engine, or ODVL measurement.")
        with tempfile.TemporaryDirectory(prefix="basira-memory-demo-") as directory:
            run(SyntheticCloud(), Path(directory) / "memory.json", "synthetic-space")


if __name__ == "__main__":
    main()
