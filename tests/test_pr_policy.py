"""PR author and branch policy regressions for NAK-1009."""

import argparse
from contextlib import redirect_stderr, redirect_stdout
import io
import os
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from scripts import nakama_governance as governance

ROOT = Path(__file__).resolve().parents[1]


class PullRequestPolicyTests(unittest.TestCase):
    def check_branch(self, branch, author, accepted, base_present=True):
        env = {'PR_HEAD_BRANCH': branch, 'PR_AUTHOR_LOGIN': author,
               'PR_BASE_REVISION': 'base-sha'}
        result = subprocess.CompletedProcess([], 0 if base_present else 1, '.branch-policy\n', '')
        with patch.dict(os.environ, env, clear=True), \
             patch.object(governance, 'repository_root', return_value=ROOT), \
             patch.object(governance, 'run_git', return_value=result), \
             redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            if accepted:
                governance.command_pr_branch(argparse.Namespace())
            else:
                with self.assertRaises(SystemExit) as error:
                    governance.command_pr_branch(argparse.Namespace())
                self.assertEqual(error.exception.code, 1)

    def test_authentic_dependabot_branches(self):
        for branch in ('dependabot/npm_and_yarn/vscode-jsonrpc-9.0.2',
                       'dependabot/npm_and_yarn/tools/review/web/typescript-5.9.3',
                       'dependabot/uv/tools/aiohttp-3.14.3',
                       'dependabot/github_actions/actions/checkout-7.0.1'):
            with self.subTest(branch=branch):
                self.check_branch(branch, 'dependabot[bot]', True)

    def test_human_or_missing_author_cannot_use_dependabot_prefix(self):
        for author in ('hectorddmx', '', 'dependabot', 'renovate[bot]'):
            with self.subTest(author=author):
                self.check_branch('dependabot/npm_and_yarn/vscode-jsonrpc-9.0.2', author, False)

    def test_bot_must_use_standard_dependabot_branch(self):
        for branch in ('dependabot/', 'dependabot/npm_and_yarn/', 'random-branch',
                       'feat/NAK-1009-human-branch', 'dependabot/npm_and_yarn/package bad'):
            with self.subTest(branch=branch):
                self.check_branch(branch, 'dependabot[bot]', False)

    def test_regular_human_policy_is_unchanged(self):
        self.check_branch('ci/NAK-1009-free-public-ci', 'hectorddmx', True)
        self.check_branch('ci/no-issue', 'hectorddmx', False)
        self.check_branch('ci/NAK-1009-free-public-ci', '', True)

    def test_dependabot_still_requires_available_base(self):
        self.check_branch('dependabot/npm_and_yarn/vscode-jsonrpc-9.0.2',
                          'dependabot[bot]', False, base_present=False)

    def test_standard_dependabot_title_passes_existing_gate(self):
        with patch.dict(os.environ, {'PR_TITLE': 'chore(deps): bump vscode-jsonrpc from 8.2.1 to 9.0.2'}, clear=True), \
             redirect_stdout(io.StringIO()):
            governance.command_pr_title(argparse.Namespace())

    def test_ci_passes_github_pr_author_not_actor(self):
        workflow = (ROOT / '.github/workflows/ci.yml').read_text()
        self.assertIn('PR_AUTHOR_LOGIN: ${{ github.event.pull_request.user.login }}', workflow)


if __name__ == '__main__':
    unittest.main()
