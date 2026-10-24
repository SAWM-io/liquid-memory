import copy
import json
from pathlib import Path
import tempfile
import unittest

from demo import SyntheticCloud
from memory import WorldMemory


class GovernanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'memory.json'
        self.cloud = SyntheticCloud()
        self.memory = WorldMemory(self.cloud, self.path, self.cloud.space_id)
        for world in ('house', 'mission'):
            self.memory.create_world(world)
            self.memory.record_fact(world, 'fact', 'A fixture fact for ' + world,
                                    'private-source-' + world, operation_id='first')
        self.entity = self.memory.worlds()['house']
        self.calls = []
        def purge(entity_id, *, idempotency_key):
            self.calls.append((entity_id, idempotency_key))
            return {'status': 'purged', 'purge_receipt': 'pgr_test', 'entity_id': entity_id,
                    'memory_space_id': self.cloud.space_id, 'memory_cleared': True, 'odvl_cleared': True}
        self.cloud.purge_entity = purge

    def purge(self):
        return self.memory.purge_world('house', operation_id='authorized-erasure-1',
                                      confirm_entity_id=self.entity)

    def test_trace_is_scoped_and_explicitly_local(self):
        trace = self.memory.trace('house')
        self.assertEqual(trace['coverage'], 'checkpoint_only')
        self.assertEqual(len(trace['records']), 1)
        self.assertEqual(trace['records'][0]['input']['source'], 'private-source-house')
        self.assertNotIn('private-source-mission', json.dumps(trace))
        trace['records'][0]['input']['source'] = 'mutated copy'
        self.assertEqual(self.memory.history('house', 'fact')[0]['input']['source'], 'private-source-house')

    def test_explicit_entity_confirmation_required(self):
        with self.assertRaises(ValueError):
            self.memory.purge_world('house', operation_id='x', confirm_entity_id='wrong-entity')
        self.assertEqual(self.calls, [])
        self.assertEqual(len(self.memory.history('house', 'fact')), 1)

    def test_purge_removes_local_fact_copies_preserves_other_world_and_blocks_reuse(self):
        other = self.memory.resume('mission')
        result = self.purge()
        self.assertTrue(result['odvl_cleared'])
        self.assertEqual(self.memory.resume('mission'), other)
        self.assertNotIn('private-source-house', self.path.read_text())
        self.assertNotIn('A fixture fact for house', self.path.read_text())
        for attempt in (lambda: self.memory.resume('house'), lambda: self.memory.trace('house'),
                        lambda: self.memory.create_world('house'),
                        lambda: self.memory.record_fact('house', 'fact', 'again', 'source', operation_id='new')):
            with self.assertRaises(ValueError):
                attempt()
        self.assertEqual(self.purge(), result)
        self.assertEqual(len(self.calls), 1)

    def test_partial_purge_never_counts_as_complete(self):
        original = self.cloud.purge_entity
        self.cloud.purge_entity = lambda *a, **kw: dict(original(*a, **kw), odvl_cleared=False)
        with self.assertRaisesRegex(ValueError, 'not fully confirmed'):
            self.purge()
        self.assertEqual(json.loads(self.path.read_text())['worlds']['house']['status'], 'purge_pending')
        with self.assertRaises(ValueError):
            self.memory.resume('house')

    def test_lost_ack_retries_exact_purge_after_restart(self):
        original = self.cloud.purge_entity
        def lose(*a, **kw):
            original(*a, **kw)
            raise TimeoutError('lost acknowledgement')
        self.cloud.purge_entity = lose
        with self.assertRaises(TimeoutError):
            self.purge()
        with self.assertRaises(ValueError):
            self.memory.create_world('house')
        self.memory = WorldMemory(self.cloud, self.path, self.cloud.space_id)
        self.cloud.purge_entity = original
        self.purge()
        self.assertEqual(self.calls[0], self.calls[1])

    def test_receipt_without_explicit_scope_is_not_enough(self):
        original = self.cloud.purge_entity
        def missing_scope(*args, **kwargs):
            receipt = original(*args, **kwargs)
            receipt.pop('memory_space_id')
            receipt.pop('entity_id')
            return receipt
        self.cloud.purge_entity = missing_scope
        with self.assertRaisesRegex(ValueError, 'mismatch'):
            self.purge()
        self.assertIn('private-source-house', self.path.read_text())
        with self.assertRaises(ValueError):
            self.memory.resume('house')

    def test_wrong_scope_receipt_blocks_local_reuse(self):
        original = self.cloud.purge_entity
        self.cloud.purge_entity = lambda *a, **kw: dict(original(*a, **kw), entity_id='another-world')
        with self.assertRaisesRegex(ValueError, 'mismatch'):
            self.purge()
        with self.assertRaises(ValueError):
            self.memory.resume('house')
