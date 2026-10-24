"""Small public-SDK adapter; the checkpoint is a receipt index, not a memory engine.

One application writer per checkpoint. Keep its directory private: it contains exact
source text. Back it up deliberately; it cannot automatically restore Cloud data.
World selection and the decision to revise a claim belong to the calling application.
"""
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
import time
from contextlib import contextmanager


def _digest(*values):
    return hashlib.sha256(json.dumps(values, ensure_ascii=False).encode()).hexdigest()


def _text(value, name, maximum):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"{name} must contain 1..{maximum} characters")
    return value


class WorldMemory:
    # Completed API idempotency receipts are retained for 48 hours.
    # This limits uncertain retries, not the lifetime of stored memories.
    RETRY_WINDOW_MS = 48 * 60 * 60 * 1000

    def __init__(self, client, checkpoint, space_id):
        self.client, self.path = client, Path(checkpoint)
        self.space_id = _text(space_id, "space_id", 160)
        if getattr(client, "space_id", None) != self.space_id:
            raise ValueError("Client memory space mismatch")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._locked():
            pass

    @contextmanager
    def _locked(self):
        lock = self.path.with_suffix(self.path.suffix + ".lock")
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            raise RuntimeError(f"Checkpoint locked: {lock}; inspect the owner before manual recovery")
        try:
            with os.fdopen(fd, "w") as stream:
                stream.write(str(os.getpid()))
            if self.path.exists():
                self.data = json.loads(self.path.read_text())
                if (self.data.get("schema") != "world-memory-checkpoint/v1"
                        or self.data.get("space_id") != self.space_id):
                    raise ValueError("Checkpoint schema or memory space mismatch")
            else:
                self.data = {"schema": "world-memory-checkpoint/v1", "space_id": self.space_id,
                             "worlds": {}, "operations": {}}
            yield
        finally:
            lock.unlink()

    def _save(self):
        fd, name = tempfile.mkstemp(prefix=self.path.name + ".", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w") as stream:
                json.dump(self.data, stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self.path)
            if hasattr(os, "O_DIRECTORY"):
                directory = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def _world(self, world):
        item = self.data["worlds"].get(world)
        if not item or item.get("status") != "confirmed":
            raise ValueError(f"Unknown or unconfirmed world: {world}")
        return item["entity_id"]

    def _scope(self, response, entity, required=False):
        if not isinstance(response, dict):
            raise ValueError("Expected a structured Cloud response")
        for field, expected in (("memory_space_id", self.space_id), ("entity_id", entity)):
            if (required or field in response) and response.get(field) != expected:
                raise ValueError(f"Cloud response {field} mismatch")

    def _check_retry_window(self, item):
        started = item.get("started_at_ms")
        now = time.time_ns() // 1_000_000
        if (type(started) is not int or now - started >= self.RETRY_WINDOW_MS
                or started - now > 300_000):
            raise RuntimeError("Uncertain operation outside the replay window; reconcile its Cloud receipt before retrying")

    def create_world(self, name, description=""):
        _text(name, "world name", 160)
        if not isinstance(description, str) or len(description) > 2000:
            raise ValueError("description must contain at most 2000 characters")
        with self._locked():
            item = self.data["worlds"].get(name)
            request = {"name": name, "description": description}
            if item and item["request"] != request:
                raise ValueError("World already exists with different creation input")
            if not item:
                item = {"request": request, "status": "pending",
                        "started_at_ms": time.time_ns() // 1_000_000,
                        "idempotency_key": "world-" + _digest(self.space_id, name, description)}
                self.data["worlds"][name] = item
                self._save()
            if item["status"] != "confirmed":
                self._check_retry_window(item)
                receipt = self.client.create_entity("monde", **request,
                                                    idempotency_key=item["idempotency_key"])
                entity = receipt.get("entity_id") if isinstance(receipt, dict) else None
                if not isinstance(entity, str) or not re.fullmatch(r"ent_[0-9a-f]{32}", entity):
                    raise ValueError("Invalid entity creation receipt; request remains pending")
                self._scope(receipt, entity)
                item.update(status="confirmed", entity_id=entity, receipt=receipt)
                self._save()
            return copy.deepcopy(item)

    def worlds(self):
        with self._locked():
            return {name: item["entity_id"] for name, item in self.data["worlds"].items()
                    if item["status"] == "confirmed"}

    def _history(self, world, key=None):
        return [op for op in self.data["operations"].values()
                if op["world"] == world and op["status"] == "confirmed"
                and (key is None or op["key"] == key)]

    def record_fact(self, world, key, content, source, *, operation_id,
                    expected_revision=None, valid_time_ms=None, belief_time_ms=None,
                    decision_time_ms=None, epistemic_status="reported", confidence=1.0):
        """Record one caller-selected factual statement; expected_revision is LOCAL only.

        Retry an uncertain result with the same operation_id and identical input.
        The persisted body, timestamps and idempotency key are reused after restart.
        """
        for value, name, limit in ((key, "key", 160), (content, "content", 1200),
                                   (source, "source", 1000), (operation_id, "operation_id", 160)):
            _text(value, name, limit)
        if "\n" in content or "\r" in content:
            raise ValueError("Use one single-line statement per fact; split structured material explicitly")
        if expected_revision is not None and (type(expected_revision) is not int or expected_revision < 0):
            raise ValueError("expected_revision must be a nonnegative integer")
        if epistemic_status not in {"reported", "observed", "inferred"}:
            raise ValueError("epistemic_status must be reported, observed, or inferred")
        if (type(confidence) not in (int, float) or not math.isfinite(confidence)
                or not 0 <= confidence <= 1):
            raise ValueError("confidence must be a finite number in [0, 1]")
        inputs = dict(content=content, source=source, expected_revision=expected_revision,
                      valid_time_ms=valid_time_ms, belief_time_ms=belief_time_ms,
                      decision_time_ms=decision_time_ms, epistemic_status=epistemic_status,
                      confidence=confidence)
        for field in ("valid_time_ms", "belief_time_ms", "decision_time_ms"):
            if inputs[field] is not None and (type(inputs[field]) is not int or inputs[field] < 0):
                raise ValueError(f"{field} must be nonnegative milliseconds")
        with self._locked():
            entity = self._world(world)
            op_key = _digest(world, operation_id)
            op = self.data["operations"].get(op_key)
            if op and (op["input"] != inputs or op["key"] != key):
                raise ValueError("operation_id reused with changed input")
            if not op:
                if any(row["world"] == world and row["key"] == key and row["status"] == "pending"
                       for row in self.data["operations"].values()):
                    raise ValueError("Retry the pending operation for this fact before revising it")
                prior = self._history(world, key)
                revision = prior[-1]["receipt"]["revision"] if prior else 0
                if expected_revision is not None and expected_revision != revision:
                    raise ValueError(f"Local revision conflict: expected {expected_revision}, have {revision}")
                now = time.time_ns() // 1_000_000
                body = {"claim_key": "claim-" + _digest(self.space_id, entity, key),
                        "candidate_id": "candidate-" + _digest(self.space_id, entity, operation_id),
                        "content": content, "epistemic_status": epistemic_status, "confidence": confidence,
                        "provenance_key": "source-" + _digest(source), "evidence": source,
                        **{field: inputs[field] if inputs[field] is not None else now
                           for field in ("valid_time_ms", "belief_time_ms", "decision_time_ms")}}
                if prior:
                    body.update(declared_revision=True, reason="Application-confirmed revision of " + key,
                                evidence=source)
                op = {"world": world, "key": key, "operation_id": operation_id, "input": inputs,
                      "body": body, "idempotency_key": "write-" + _digest(self.space_id, op_key),
                      "status": "pending", "started_at_ms": now}
                self.data["operations"][op_key] = op
                self._save()
            if op["status"] != "confirmed":
                self._check_retry_window(op)
                receipt = self.client.write_assertion(copy.deepcopy(op["body"]), entity_id=entity,
                                                       idempotency_key=op["idempotency_key"])
                self._scope(receipt, entity)
                if (receipt.get("status") != "completed"
                        or receipt.get("claim_key") != op["body"]["claim_key"]
                        or receipt.get("candidate_id") != op["body"]["candidate_id"]
                        or type(receipt.get("revision")) is not int or receipt["revision"] < 1
                        or type(receipt.get("odvl_applied")) is not bool):
                    raise ValueError("Invalid assertion receipt; operation remains pending")
                op.update(status="confirmed", receipt=receipt)
                self._save()
            return copy.deepcopy(op)

    def history(self, world, key):
        """All confirmed receipts in THIS checkpoint, not complete Cloud history."""
        with self._locked():
            self._world(world)
            return copy.deepcopy(self._history(world, key))

    def resume(self, world):
        """Local known facts and pending requests; no semantic routing or Cloud rebuild."""
        with self._locked():
            entity = self._world(world)
            facts = {op["key"]: op for op in self._history(world)}
            pending = [op["operation_id"] for op in self.data["operations"].values()
                       if op["world"] == world and op["status"] == "pending"]
            return copy.deepcopy({"world": world, "entity_id": entity,
                                  "known_facts": facts, "pending_operations": pending})

    def recall(self, world, query, at_ms=None):
        """Return at most 10 verified TSST evidence entries, never an exhaustive history."""
        with self._locked():
            entity = self._world(world)
        if at_ms is None:
            result = self.client.recall_tsst(query, entity_id=entity, limit=10,
                                            epistemic={"include_belief_history": True})
        else:
            if type(at_ms) is not int or at_ms < 0:
                raise ValueError("at_ms must be nonnegative milliseconds")
            result = self.client.flashback_tsst(query, as_of_valid_time_ms=at_ms,
                                               entity_id=entity, limit=10)
        self._scope(result, entity, required=True)
        if (result.get("schema") != "basira-tsst-evidence/v1"
                or not isinstance(result.get("evidence"), list) or len(result["evidence"]) > 10
                or (at_ms is not None and result.get("flashback") is not True)):
            raise ValueError("Invalid TSST evidence envelope")
        for row in result["evidence"]:
            self._scope(row, entity)
            if (row.get("integrity_verified") is not True
                    or not all(isinstance(row.get(field), str) and row[field]
                               for field in ("evidence_id", "claim_key", "candidate_id"))
                    or type(row.get("revision")) is not int or row["revision"] < 1):
                raise ValueError("Unverified or malformed TSST evidence")
        return result

    def observe(self, world):
        """Read ODVL for locally known candidates; unavailable is never measured zero."""
        snapshot = self.resume(world)
        ids = list(dict.fromkeys(op["body"]["candidate_id"] for op in snapshot["known_facts"].values()))
        if not ids:
            return {"available": False, "observations": [], "reason": "No confirmed candidates"}
        if len(ids) > 128:
            raise ValueError("This small example supports at most 128 current candidates per observation")
        result = self.client.odvl_observe(ids, entity_id=snapshot["entity_id"])
        self._scope(result, snapshot["entity_id"])
        if type(result.get("available")) is not bool or not isinstance(result.get("observations"), list):
            raise ValueError("Invalid ODVL observation response")
        for row in result["observations"]:
            self._scope(row, snapshot["entity_id"])
            if "candidate_id" in row and row["candidate_id"] not in ids:
                raise ValueError("ODVL observation candidate mismatch")
        return result
