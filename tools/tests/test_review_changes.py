from pathlib import Path
import subprocess
import tempfile
import unittest
from test_workspace import module


class ChangesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.api = module('changes_review', 'review/api/service.py')
        self.api.repository = lambda name: self.root
        self.git('init', '-q')
        self.git('config', 'user.name', 'Test')
        self.git('config', 'user.email', 'test@example.test')
        (self.root / 'old name.txt').write_text('original\nsecond\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'initial')

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.root), *args], text=True).strip()

    def test_untracked_text_binary_and_ignored_files(self):
        name = 'new\tfile\nname.md'
        (self.root / name).write_text('one\ntwo\n')
        (self.root / 'binary').write_bytes(b'\x00\xff')
        (self.root / '.gitignore').write_text('ignored\n')
        (self.root / 'ignored').write_text('secret')
        rows = {r['path']: r for r in self.api.changed_files('repo', None, None)}
        self.assertEqual(rows[name]['added'], 2)
        self.assertTrue(rows['binary']['binary'])
        self.assertNotIn('ignored', rows)
        self.assertEqual(self.api.sides('repo', None, None, name)['new'], 'one\ntwo\n')
        self.assertIsNone(self.api.sides('repo', None, None, name)['old'])
        self.assertEqual(self.api.changed_files('repo', 'HEAD', 'HEAD'), [])

    def test_staged_rename_preserves_both_sides_and_literal_names(self):
        name = 'new\tname\n.txt'
        self.git('mv', 'old name.txt', name)
        row, = self.api.changed_files('repo', None, None)
        self.assertEqual(row['path'], name)
        self.assertEqual(row['old_path'], 'old name.txt')
        self.assertIn('rename from old name.txt', self.api.patch('repo', None, None, name))
        sides = self.api.sides('repo', None, None, name)
        self.assertEqual(sides['old'], 'original\nsecond\n')
        self.assertEqual(sides['new'], sides['old'])
        self.git('commit', '-qm', 'rename')
        self.assertEqual(self.api.sides('repo', 'HEAD~1', 'HEAD', name), sides)

    def test_tree_and_status_preserve_literal_paths(self):
        names = ['café.md', 'quote".md', 'tab\tline\n.md', 'literal -> name.md']
        for name in names:
            (self.root / name).write_text('contents\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'unusual paths')
        for revision in ['WORKTREE', 'HEAD']:
            paths = self.api.tree('repo', revision)
            for name in names:
                self.assertIn(name, paths)
                self.assertEqual(self.api.blob('repo', revision, name), 'contents\n')
        for name in names:
            (self.root / name).write_text('changed\n')
        renamed = 'renamed\tfile\n.md'
        self.git('mv', 'old name.txt', renamed)
        statuses = {r['path']: r['status'] for r in self.api.status('repo')}
        for name in names:
            self.assertEqual(statuses[name], 'modified')
        self.assertEqual(statuses[renamed], 'renamed')

    def test_binary_sides_do_not_decode_blobs(self):
        (self.root / 'binary').write_bytes(b'\x00\xff')
        self.git('add', '.')
        self.git('commit', '-qm', 'binary')
        (self.root / 'binary').write_bytes(b'\x00\xfe')
        sides = self.api.sides('repo', None, None, 'binary')
        self.assertEqual(sides['old'], 'Binary file')
        self.assertEqual(sides['new'], 'Binary file')
        self.git('add', '.')
        self.git('commit', '-qm', 'change binary')
        self.assertEqual(self.api.sides('repo', 'HEAD~1', 'HEAD', 'binary'), sides)
        with self.assertRaisesRegex(self.api.GitError, 'not text'):
            self.api.blob('repo', 'HEAD', 'binary')
