from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from test_workspace import module


class WorktreeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name).resolve()
        self.root = base / 'repo'
        self.root.mkdir()
        self.api = module('worktrees_review', 'review/api/service.py')
        self.api.repositories = lambda: {'repo': self.root}
        self.git('init', '-q', '-b', 'main')
        self.git('config', 'user.name', 'Test')
        self.git('config', 'user.email', 'test@example.test')
        self.commit('README.md', 'first\n', 'initial')
        # Never fetched; it only maps branches to refs/remotes/origin/*.
        self.git('remote', 'add', 'origin', str(base / 'origin.git'))
        self.publish('main')
        self.git('symbolic-ref', 'refs/remotes/origin/HEAD', 'refs/remotes/origin/main')
        self.trees = base / 'trees'

    def git(self, *args, cwd=None):
        return subprocess.check_output(['git', '-C', str(cwd or self.root), *args], text=True).strip()

    def commit(self, name, text, message, cwd=None):
        (Path(cwd or self.root) / name).write_text(text)
        self.git('add', name, cwd=cwd)
        self.git('commit', '-qm', message, cwd=cwd)

    def publish(self, branch, ref=None):
        """Stand in for a fetch: point the remote-tracking branch at a commit."""
        self.git('update-ref', f'refs/remotes/origin/{branch}', ref or branch)

    def worktree(self, name, start='main'):
        path = self.trees / name
        self.git('worktree', 'add', '-q', '-b', name, str(path), start)
        return path

    def states(self):
        return {entry['slug']: entry for entry in self.api.worktrees()}

    def test_each_state_and_cleanup_advice(self):
        self.worktree('merged')
        active = self.worktree('active')
        self.commit('active.txt', 'work\n', 'active work', cwd=active)
        squashed = self.worktree('squashed')
        self.commit('squash.txt', 'one\n', 'part one', cwd=squashed)
        self.commit('squash.txt', 'one\ntwo\n', 'part two', cwd=squashed)
        self.commit('squash.txt', 'one\ntwo\n', 'squash merge')  # the same change, landed as one commit
        self.publish('main')
        dirty = self.worktree('dirty')
        (dirty / 'README.md').write_text('edited\n')
        gone = self.worktree('gone')
        self.commit('gone.txt', 'gone\n', 'unmerged', cwd=gone)
        self.git('config', 'branch.gone.remote', 'origin')
        self.git('config', 'branch.gone.merge', 'refs/heads/gone')  # no origin/gone: deleted upstream
        missing = self.worktree('missing')
        shutil.rmtree(missing)

        rows = self.states()
        expected = {'merged': 'merged', 'active': 'active', 'squashed': 'integrated',
                    'dirty': 'dirty', 'gone': 'gone', 'missing': 'missing'}
        self.assertEqual({slug: row['state'] for slug, row in rows.items()}, expected)
        self.assertEqual({slug for slug, row in rows.items() if row['can_prune']},
                         {'merged', 'squashed', 'missing'})
        self.assertEqual(rows['active']['ahead'], 1)
        self.assertEqual(rows['dirty']['changed_files'], 1)
        self.assertTrue(rows['gone']['upstream_gone'])
        self.assertEqual(rows['merged']['cleanup'][-1], f'git -C {self.root} branch -d merged')
        # A squash merge leaves commits Git cannot see as merged, so `-d` would refuse.
        self.assertEqual(rows['squashed']['cleanup'][-1], f'git -C {self.root} branch -D squashed')
        self.assertEqual(rows['missing']['cleanup'], [f'git -C {self.root} worktree prune'])
        for slug in ('active', 'dirty', 'gone'):
            self.assertEqual(rows[slug]['cleanup'], [])

    def test_work_merged_into_a_dev_branch_counts_as_merged(self):
        feature = self.worktree('feature')
        self.commit('feature.txt', 'feature\n', 'feature', cwd=feature)
        self.git('branch', 'dev', 'main')
        self.git('merge', '-q', '--no-ff', '-m', 'merge feature', 'feature', cwd=self.worktree('dev-merge', 'dev'))
        self.publish('dev', 'dev-merge')
        row = self.states()['feature']
        self.assertEqual((row['state'], row['merged_into']), ('merged', 'origin/dev'))
        self.assertEqual(row['default_ref'], 'origin/main')

    def test_locked_and_integration_branch_worktrees_are_never_pruned(self):
        self.worktree('locked')
        self.git('worktree', 'lock', str(self.trees / 'locked'))
        self.git('branch', '-q', 'dev', 'main')
        self.publish('dev')
        self.git('worktree', 'add', '-q', str(self.trees / 'on-dev'), 'dev')
        rows = self.states()
        self.assertEqual(rows['locked']['state'], 'merged')
        self.assertFalse(rows['locked']['can_prune'])
        self.assertEqual(rows['on-dev']['state'], 'active')
        self.assertFalse(rows['on-dev']['can_prune'])

    def test_worktree_ids_resolve_like_repositories(self):
        path = self.worktree('review-me')
        self.commit('new.txt', 'hello\n', 'add new', cwd=path)
        (path / 'new.txt').write_text('changed\n')
        self.assertEqual(self.api.repository('repo@review-me'), path)
        self.assertEqual(self.api.overview('repo@review-me')['head'], 'review-me')
        self.assertEqual([row['path'] for row in self.api.changed_files('repo@review-me', None, None)], ['new.txt'])
        shutil.rmtree(self.worktree('removed'))
        for name in ('repo@removed', 'repo@unknown', 'other@review-me'):
            with self.assertRaises(self.api.GitError):
                self.api.repository(name)
        with self.assertRaises(self.api.GitError):
            self.api.worktrees('other')

    def test_slugs_stay_unique_and_readable(self):
        # Some tools nest a checkout named like the repository inside a task directory.
        self.git('worktree', 'add', '-q', '-b', 'task', str(self.trees / 'task-one' / 'repo'), 'main')
        self.git('worktree', 'add', '-q', '-b', 'a', str(self.trees / 'a' / 'same'), 'main')
        self.git('worktree', 'add', '-q', '-b', 'b', str(self.trees / 'b' / 'same'), 'main')
        self.assertEqual(sorted(self.states()), ['same', 'same-2', 'task-one'])


if __name__ == '__main__':
    unittest.main()
