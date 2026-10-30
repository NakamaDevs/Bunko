"""Regression tests for ticket syntax and the existing online existence gate."""
import importlib.util
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

path = Path(__file__).with_name('nakama_governance.py')
if __name__ == '__main__' and len(sys.argv) > 1:
    path = Path(sys.argv.pop(1)).resolve()
spec = importlib.util.spec_from_file_location('ticket_policy', path)
policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policy)
PROFILE = {'default_branch': 'main', 'existing_branches': ['old/OPS-1']}
LEGACY = {'LINEAR_TEAM_KEY': 'NAK', 'LINEAR_PROJECT_NAME': 'Synthetic Project', 'PROTECTED_BRANCHES': 'main', 'LEGACY_BRANCH_ALLOWLIST': '', 'BRANCH_FORMAT': 'issue'}

class TicketPolicy(unittest.TestCase):
    def branch(self, branch):
        return policy.branch_error(branch, PROFILE) if hasattr(policy, 'branch_error') else policy.validate_branch_format(branch, LEGACY)

    def message(self, text):
        return policy.message_error(text) if hasattr(policy, 'message_error') else policy.validate_commit_message(text, True)

    def test_accepts_branch_keys_without_allowlist(self):
        for key in ('ABC', 'DOC', 'QA2', 'Z', 'LONGTEAM'):
            with self.subTest(key=key):
                self.assertIsNone(self.branch(f'fix/{key}-123-description'))

    def test_rejects_missing_or_malformed_branch_tickets(self):
        for ticket in ('', 'ABC', 'ABC-', 'ABC-0', 'ABC-01', 'ABC-one', '123-45', 'İ-123', 'ı-123', 'ſ-123', 'KEY-123'):
            with self.subTest(ticket=ticket):
                self.assertIsNotNone(self.branch(f'fix/{ticket}-description'))

    @unittest.skipUnless(hasattr(policy, 'message_error') or hasattr(policy, 'validate_commit_message'), 'legacy checker delegates body references to the delivery hook')
    def test_accepts_commit_keys_without_allowlist(self):
        for key in ('ABC', 'DOC', 'QA2', 'Z', 'LONGTEAM'):
            with self.subTest(key=key):
                self.assertIsNone(self.message(f'fix: preserve ticket\n\nRefs {key}-123'))

    @unittest.skipUnless(hasattr(policy, 'message_error') or hasattr(policy, 'validate_commit_message'), 'legacy checker delegates body references to the delivery hook')
    def test_rejects_missing_or_malformed_commit_tickets(self):
        for ticket in ('', 'ABC', 'ABC-', 'ABC-0', 'ABC-01', 'ABC-one', '123-45', 'İ-123', 'ı-123', 'ſ-123', 'KEY-123'):
            with self.subTest(ticket=ticket):
                self.assertIsNotNone(self.message(f'fix: preserve ticket\n\nRefs {ticket}'))
        for suffix in ('garbage', '.5', '/other', '_tail', '-extra'):
            self.assertIsNotNone(self.message(f'fix: preserve ticket\n\nRefs ABC-123{suffix}'))
        self.assertIsNotNone(self.message('not a semantic header\n\nRefs ABC-123'))
        self.assertIsNotNone(self.message('fix: no reference'))

    def test_preserves_other_branch_gates(self):
        self.assertIsNone(self.branch('main'))
        self.assertIsNotNone(self.branch('other/ABC-123-description'))
        self.assertIsNotNone(self.branch('fix/ABC-0-description'))

    @unittest.skipUnless(hasattr(policy, 'linear_issue'), 'existing checker is intentionally offline')
    def test_existing_online_existence_and_project_gate(self):
        def response(issue):
            return io.BytesIO(json.dumps({'data': {'issue': issue}}).encode())
        valid = {'identifier':'ABC-123', 'team':{'key':'ABC'}, 'project':{'name':'Synthetic Project'}}
        with patch.object(policy.urllib.request, 'urlopen', return_value=response(valid)) as call:
            policy.linear_issue('fix/ABC-123-description', LEGACY, 'synthetic-fixture', 'https://example.invalid/graphql')
            self.assertEqual(json.loads(call.call_args.args[0].data)['variables']['id'], 'ABC-123')
        for issue in (None, {}, valid | {'identifier':'ABC-124'}, valid | {'project':{'name':'Other Project'}}):
            with patch.object(policy.urllib.request, 'urlopen', return_value=response(issue)):
                with self.assertRaises(SystemExit):
                    policy.linear_issue('fix/ABC-123-description', LEGACY, 'synthetic-fixture', 'https://example.invalid/graphql')
        with patch.object(policy.urllib.request, 'urlopen', side_effect=OSError('synthetic unavailable')):
            with self.assertRaises(SystemExit):
                policy.linear_issue('fix/ABC-123-description', LEGACY, 'synthetic-fixture', 'https://example.invalid/graphql')

if __name__ == '__main__':
    unittest.main()
