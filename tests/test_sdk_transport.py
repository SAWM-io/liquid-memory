"""Contract test against the downloaded public SDK, using zero network calls."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

from memory import WorldMemory

SDK_PATH = Path(__file__).resolve().parents[1] / 'vendor' / 'basira_client.py'


@unittest.skipUnless(SDK_PATH.exists(), 'Run python bootstrap_sdk.py to include the public SDK contract test')
class PublishedSDKTransportTests(unittest.TestCase):
    def test_revision_scope_tsst_flashback_and_odvl_wire_contract(self):
        import httpx
        spec = importlib.util.spec_from_file_location('published_basira_sdk', SDK_PATH)
        sdk = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = sdk
        spec.loader.exec_module(sdk)
        entity = 'ent_' + 'a' * 32
        requests, facts = [], []
        def handler(request):
            body = json.loads(request.content)
            requests.append((request.url.path, copy.deepcopy(body)))
            if request.url.path.endswith('/entities'):
                self.assertEqual(body['entity_type'], 'monde')
                return httpx.Response(200, json={'entity_id': entity})
            self.assertEqual(body['entity_id'], entity)
            if request.url.path.endswith('/assertions'):
                self.assertNotIn('revision_reason', body)
                self.assertNotIn('revision_evidence', body)
                self.assertNotIn('known_at_ms', body)
                self.assertIn('evidence', body)
                if facts:
                    self.assertTrue(body['declared_revision'])
                    self.assertTrue(body['reason'])
                    self.assertEqual(body['claim_key'], facts[0]['claim_key'])
                    self.assertNotEqual(body['candidate_id'], facts[0]['candidate_id'])
                facts.append(body)
                return httpx.Response(200, json={
                    'status': 'completed', 'candidate_id': body['candidate_id'],
                    'claim_key': body['claim_key'], 'revision': len(facts), 'odvl_applied': True,
                })
            if request.url.path.endswith('/recall:tsst'):
                self.assertEqual(body['limit'], 10)
                self.assertTrue(body['epistemic']['include_belief_history'])
                historical = 'as_of_valid_time_ms' in body.get('temporal', {})
                if historical:
                    self.assertEqual(body['temporal']['as_of_valid_time_ms'], 1500)
                fact = facts[0] if historical else facts[-1]
                return httpx.Response(200, json={
                    'schema': 'basira-tsst-evidence/v1', 'memory_space_id': 'test-space',
                    'entity_id': entity, 'flashback': historical,
                    'evidence': [{'evidence_id': 'proof-1', 'integrity_verified': True,
                                  'candidate_id': fact['candidate_id'], 'claim_key': fact['claim_key'],
                                  'revision': 1 if historical else 2, 'excerpt': fact['content']}],
                })
            if request.url.path.endswith('/odvl:observe'):
                self.assertEqual(body['candidate_ids'], [facts[-1]['candidate_id']])
                return httpx.Response(200, json={'available': False, 'observations': []})
            self.fail('Unexpected endpoint: ' + request.url.path)
        with tempfile.TemporaryDirectory() as folder:
            with httpx.Client(transport=httpx.MockTransport(handler)) as transport:
                client = sdk.BasiraClient('test-space', 'example-test-key', http_client=transport)
                memory = WorldMemory(client, Path(folder) / 'state.json', 'test-space')
                memory.create_world('house')
                first = dict(world='house', key='cup', content='Cup in kitchen.', source='Host observation 1',
                             operation_id='one', valid_time_ms=1000)
                memory.record_fact(**first)
                memory.record_fact(**first)  # Receipt replay stays local, no extra write.
                memory.record_fact('house', 'cup', 'Cup on shelf.', 'Host observation 2',
                                   operation_id='two', expected_revision=1, valid_time_ms=2000)
                memory.recall('house', 'cup')
                memory.recall('house', 'cup', at_ms=1500)
                self.assertFalse(memory.observe('house')['available'])
        self.assertEqual(len(requests), 6)
