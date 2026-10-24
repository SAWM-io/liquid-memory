# Memory controls, traceability and governance

**Know what your agent recalled, what changed, and what was actually erased.**

Liquid Memory connects applications to Basira Cloud controls. This guide explains
which controls are available, how to use them, and what an integrator still owns.
It is a technical integration guide, not a compliance certificate or a legal opinion.

## Capability map

| Control | Public capability | Application integration | Important boundary |
| --- | --- | --- | --- |
| Historical recall | `flashback()` / `flashback_tsst()` | Query what was valid or known at a chosen time; inspect returned evidence. | Bounded recall is not an exhaustive reconstruction of every source or every model thought. |
| Correction with history | `write_assertion()` with the same claim and a declared revision | `record_fact()` keeps the same fact key and a new operation ID. | The host verifies the new information; a revision receipt alone does not prove factual truth. |
| Provenance | TSST evidence IDs, candidate IDs, revisions and integrity flags | Keep input sources and Cloud receipts alongside confirmed results. | A valid ID does not establish that a model interpretation follows from its source. |
| Local trace export | `WorldMemory.trace(world)` | Export this writer's confirmed source/receipt trail for review. | This JSON is not a complete Cloud access log, all personal data, or a tamper-proof archive. |
| Scoped erasure | SDK `purge_entity()`; example `purge_world()` | Explicitly authorize a target, block local reuse, verify both erasure flags. | Address backups, external logs, other caches and downstream copies separately. |
| Scope isolation | Space, entity, principal, key scopes and grants | Separate workers and tenants; give only the required access. | World names alone are not authorization controls. |
| Human supervision | Application validation before action and before confirmation | Permit review, refusal and correction; keep the outcome evidence. | Your domain rules, permissions and risk process remain part of the complete system. |

The Cloud has its own operational audit records. This SDK does **not** expose a
complete account-wide audit-log export API. Do not present this example's local
trace as that export. The source/receipt trace covers only operations that this
checkpoint has recorded.

## 1. Look back without rewriting the present

After the setup in [README](../README.md), choose the exact world and cutoff:

```python
from datetime import datetime, timezone

cutoff_ms = int(datetime(2026, 10, 1, tzinfo=timezone.utc).timestamp() * 1000)
result = memory.recall("assistant-1/project-orion", "What was the delivery date?", at_ms=cutoff_ms)
assert result["flashback"] is True
for proof in result["evidence"]:
    print(proof["evidence_id"], proof["claim_key"], proof["revision"])
```

The example checks the space, entity, evidence structure and integrity flags.
If the historical projection is unavailable, it does not silently substitute a
current answer. A missing result means **not returned by this bounded query**,
not necessarily nonexistent.

For both a business-time and a knowledge-time cutoff, use the SDK directly:

```python
entity = memory.worlds()["assistant-1/project-orion"]
result = cloud.flashback_tsst(
    "What did the agent know about the delivery?",
    entity_id=entity,
    as_of_valid_time_ms=cutoff_ms,
    as_of_transaction_time_ms=cutoff_ms,
    limit=5,
)
# Validate scope, flashback and evidence just as for your ordinary retrieval path.
```

Business time describes when the fact applies. Transaction time describes when
the service recorded it. A correction learned later need not appear in an answer
about what was known earlier. Neither method reruns the old action.

## 2. Correct a fact and retain its source trail

```python
memory.record_fact(
    "assistant-1/project-orion", "delivery.status",
    "The delivery is now scheduled for Monday.",
    "The scheduling service confirmed Monday; receipt example-43.",
    operation_id="delivery-change-43", expected_revision=1,
    epistemic_status="observed",
)
```

The wrapper uses the existing claim, a new candidate ID and the API's explicit
revision fields. It stores the exact source and returned revision. `observed`
should mean an outcome your application actually checked; a user's assertion
is normally `reported`, and a model interpretation is `inferred`.

`expected_revision` checks the local receipt index, not a distributed server CAS.
Coordinate writers as described in the [multi-agent guide](agents-and-characters.md).

## 3. Export a reviewable trace

```python
import json
import os
from pathlib import Path

trace = memory.trace("assistant-1/project-orion")
Path(".state").mkdir(exist_ok=True)
# A new, private file; never serve this path directly to an unauthenticated user.
fd = os.open(".state/orion-trace.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, "w", encoding="utf-8") as stream:
    json.dump(trace, stream, ensure_ascii=False, indent=2)
```

The export labels its coverage `checkpoint_only`. Each confirmed record includes
its source, statement, requested temporal fields, operation identity and Cloud
receipt. Pending operations are identified separately. Restrict access because
source texts can contain personal or confidential information.

For an operational audit, also record your application's user authorization,
selected model/version, tools invoked, verified external results and published
answer. Do not invent or describe this as access to a model's private reasoning.
If you need tamper evidence and retention guarantees, send approved trace records
to your own access-controlled archival/audit system.

## 4. Erase an authorized world deliberately

**This operation is destructive and is never run by `demo.py`.** Use a dedicated
operator path, check the requester's authority, and confirm the exact entity.
The key needs `memory:purge` and the applicable admin grant on the target.

```python
world = "assistant-1/project-orion"
entity = memory.worlds()[world]
# Only after application authorization and explicit confirmation of this entity:
receipt = memory.purge_world(
    world,
    operation_id="authorized-erasure-request-2026-001",
    confirm_entity_id=entity,
)
assert receipt["memory_cleared"] is True
assert receipt["odvl_cleared"] is True
print(receipt["purge_receipt"])
```

Use a client authorized for that erasure when opening `WorldMemory`. The wrapper:

1. Saves a pending erasure marker before the network call, blocking local reads,
   new writes and recreation of that world through this checkpoint.
2. Sends the scoped SDK purge with a persisted idempotency key.
3. Checks the returned space, entity, `pgr_` receipt, `status="purged"` and **both**
   `memory_cleared` and `odvl_cleared` flags.
4. Removes that world's recorded statement/source copies from this checkpoint
   only after full confirmation; keeps the target and minimal erasure receipt.
   Other worlds remain intact.

A partial result (`memory_cleared=true`, `odvl_cleared=false`) is **not** a complete
purge. Local access stays blocked. Retrying the same key may replay the same
partial receipt; reconcile it with the operator instead of declaring success.
A lost acknowledgement can be retried with the same operation identity within
the documented replay window; older uncertain requests require reconciliation.

After a purge the entity's memory namespace is terminal. Start again with a new
entity/world identity; never restore an older checkpoint to reactivate it.
`delete_entity()` also tombstones the entity registry entry and revokes its grants;
it is a different operation. Root `purge_space()` closes the space but is **not**
a verified recursive physical erasure of every child entity namespace. Enumerate
and handle the intended entity scopes through an authorized operational process.

The example cannot erase copies you exported earlier, other agents' checkpoints,
model-provider logs, operating-system snapshots or backups. The remaining world
label and receipt can also be identifying: use non-personal world names and set
appropriate access and retention policies for the erasure trail. Reconcile
backup restoration with your deletion register before serving restored data.

## 5. What these controls contribute to compliance

These controls can support an organization's evidence and governance obligations
**within their verified technical scope**. They do not make every agent or
chatbot legally compliant automatically.

| Regulatory topic | Relevant contribution | Still owned by the complete deployment |
| --- | --- | --- |
| GDPR accuracy and rectification (Articles 5 and 16) | Sourced corrections and version history. | Validate accuracy, purposes, applicability and handling of a person's request. |
| GDPR erasure (Article 17) | Scoped purge receipts and application anti-reuse handling. | Check conditions/exceptions and handle processors, exports, backups and other copies. |
| GDPR accountability, privacy by design and security (Articles 5(2), 25, 32) | Access scopes, trace records and tested failure handling. | Lawful basis, minimization, retention, notices, security operations and contracts. |
| AI Act traceability, information and supervision (Articles 12–14 and 26, where applicable) | Reviewable memory sources, changes and host checks. | System classification, required logging, documentation, oversight and applicable timetable. |
| NIS2 continuity and incident handling (Articles 21 and 23, where applicable) | Evidence for reconstruction and recovery procedures. | Organizational scope, national implementation, backups, incident response and notifications. |

A technical trace does not replace the GDPR Article 30 record of processing
activities. The checkpoint export is not a complete Article 15 access response
or Article 20 portability solution. Applicability and deadlines differ by
system and organization; this repository does not claim a universal retention
period or a legal certification. Its automated tests verify the documented code
paths, not all regulatory requirements.

**Data boundary:** this Cloud integration sends the statements, sources and
queries you choose to Basira. Your model receives the evidence your application
forwards. Do not generalize a low-level search component's security property
into a promise that no plaintext reaches any Cloud service or model.

Official references: [GDPR](https://eur-lex.europa.eu/eli/reg/2016/679/oj),
[AI Act](https://eur-lex.europa.eu/eli/reg/2024/1689/oj),
[NIS2](https://eur-lex.europa.eu/eli/dir/2022/2555/oj).
Implementation checks: [validation record](validation.md).
