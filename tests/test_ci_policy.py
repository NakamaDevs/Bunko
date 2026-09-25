"""Regression coverage for the NAK-1009 Bunko public CI exception."""

import argparse
from contextlib import redirect_stdout
import io
from pathlib import Path
import unittest
from unittest.mock import patch

from scripts import nakama_governance as governance


ROOT = Path(__file__).resolve().parents[1]
CI_PATH = '.github/workflows/ci.yml'


class PublicCITests(unittest.TestCase):
    def setUp(self):
        self.workflow = (ROOT / CI_PATH).read_text()

    def errors(self, workflow):
        return governance.bunko_public_ci_errors(CI_PATH, workflow)

    def test_current_workflow_passes_both_policy_layers(self):
        self.assertEqual(self.errors(self.workflow), [])
        self.assertEqual(governance.runner_policy_errors(CI_PATH, self.workflow), [])

    def test_regular_and_dependabot_use_the_same_literal_runner(self):
        jobs = governance.workflow_job_blocks(self.workflow)
        self.assertEqual([name for name, _ in jobs], ['verify'])
        self.assertEqual(governance.workflow_job_field(jobs[0][1], 'runs-on').strip(), 'ubuntu-24.04')
        self.assertNotIn('dependabot[bot]', self.workflow)

    def test_rejects_paid_custom_and_dynamic_runners(self):
        for runner in ('macos-15', 'ubuntu-24.04-arm', 'ubuntu-24.04-large', 'ubuntu-24.04-xlarge', 'ubuntu-latest',
                       'custom-paid', 'nakama-linux-x64', 'nakama-dependabot-linux-x64',
                       '[ubuntu-24.04, custom-paid]', '${{ matrix.runner }}',
                       "${{ vars.runner || 'ubuntu-24.04' }}",
                       '\n      group: paid\n      labels: ubuntu-24.04',
                       "${{ github.event.pull_request.user.login == 'dependabot[bot]' && 'ubuntu-24.04-xlarge' || 'ubuntu-24.04' }}"):
            with self.subTest(runner=runner):
                self.assertTrue(self.errors(self.workflow.replace('runs-on: ubuntu-24.04', f'runs-on: {runner}')))

    def test_rejects_missing_or_weakened_job_guards(self):
        guard = governance.BUNKO_PUBLIC_CI_GUARD
        for condition in ('', '${{ true }}',
                          guard.replace("visibility == 'public'", "visibility == 'private'"),
                          guard.replace(' && ', ' || ', 1),
                          guard.replace("github.event.repository.visibility == 'public' && ", ''),
                          "${{ github.event.repository.visibility == 'public' }}",
                          guard + ' || true',
                          '${{ true }} # ' + guard):
            with self.subTest(condition=condition):
                self.assertTrue(self.errors(self.workflow.replace(guard, condition)))
        self.assertTrue(self.errors(self.workflow.replace('    if:', '      if:')))

    def test_guard_requires_public_visibility_for_every_event(self):
        # Pin the complete expression so its parentheses and comparisons cannot drift.
        block = governance.workflow_job_blocks(self.workflow)[0][1]
        self.assertEqual(governance.workflow_job_field(block, 'if').strip(),
                         "${{ github.event.repository.visibility == 'public' && (github.event_name != 'pull_request' || github.event.pull_request.head.repo.full_name == github.repository) }}")

    def test_exception_cannot_expand_to_other_jobs_or_workflows(self):
        self.assertTrue(governance.bunko_public_ci_errors('.github/workflows/other.yml', self.workflow))
        self.assertTrue(self.errors(self.workflow.replace('  verify:', '  deploy:')))
        self.assertTrue(self.errors(self.workflow + '\n  extra:\n    uses: org/repo/.github/workflows/paid.yml@main\n'))
        self.assertTrue(self.errors(self.workflow.replace('    runs-on: ubuntu-24.04', '    uses: ./other.yml')))
        self.assertTrue(self.errors('jobs: {}'))
        self.assertTrue(self.errors(self.workflow + '\n  paid: {runs-on: ubuntu-24.04-xlarge, steps: []}\n'))

    def test_workload_declaration_is_required(self):
        self.assertTrue(self.errors(self.workflow.replace('server-only', 'native-macos')))
        self.assertTrue(self.errors(self.workflow.replace('    # nakama-workload: server-only\n', '')))

    def test_command_applies_exception_only_to_bunko(self):
        with patch.object(governance, 'repository_root', return_value=ROOT), \
             patch.object(governance, 'load_context') as context, \
             patch.object(governance, 'bunko_public_ci_errors', return_value=[]) as check, \
             redirect_stdout(io.StringIO()):
            context.return_value = {'repository': 'NakamaDevs/Other'}
            governance.command_runner_policy(argparse.Namespace())
            check.assert_not_called()
            context.return_value = {'repository': 'NakamaDevs/Bunko'}
            governance.command_runner_policy(argparse.Namespace())
            check.assert_called_once_with(CI_PATH, self.workflow)


if __name__ == '__main__':
    unittest.main()
