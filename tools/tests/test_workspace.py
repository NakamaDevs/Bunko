"""Exercise storage isolation and repository edits against temporary data."""
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest

TOOLS = Path(__file__).resolve().parents[1]
def module(name, path):
    spec = importlib.util.spec_from_file_location(name, TOOLS / path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value

class NotesTests(unittest.TestCase):
    def test_shared_store_persists_and_filters_sources(self):
        notes = module('notes', 'docs/annotations/service.py')
        with tempfile.TemporaryDirectory() as folder:
            notes.DATABASE = Path(folder) / 'state/notes.duckdb'
            notes.LEGACY_DATABASE = Path(folder) / 'absent.db'
            prose = notes.add_note({'body':'Prose note','repo':'sdlc','file_path':'en/README.md','page_path':'/en/','block_anchor':'first'})
            notes.add_note({'body':'Code note','repo':'sdlc','file_path':'app.py','line_number':3})
            self.assertEqual(len(notes.list_notes(repo='sdlc')), 2)
            self.assertEqual(len(notes.list_notes(page_path='/en/')), 1)
            notes._connection.close()
            notes._connection = None
            self.assertEqual(len(notes.list_notes()), 2)
            notes.resolve_note(prose['id'], True)
            self.assertEqual(len(notes.list_notes()), 1)
            self.assertEqual(len(notes.list_notes(open_only=False)), 2)
            notes._connection.close()

class ReviewTests(unittest.TestCase):
    def test_worktree_lists_new_files_and_refuses_escape(self):
        api = module('review', 'review/api/service.py')
        with tempfile.TemporaryDirectory() as folder:
            repo = Path(folder).resolve()
            subprocess.run(['git','init','-q',folder],check=True)
            api.repository = lambda name: repo
            api.write_file('sdlc','draft.md','Draft')
            self.assertIn('draft.md',api.tree('sdlc','WORKTREE'))
            self.assertEqual(api.blob('sdlc','WORKTREE','draft.md'),'Draft')
            for path in ['../escape.md','.git/config','/tmp/escape.md']:
                with self.assertRaises(api.GitError):
                    api.write_file('sdlc',path,'bad')
            (repo/'escape').symlink_to(repo.parent)
            with self.assertRaises(api.GitError):
                api.write_file('sdlc','escape/outside.md','bad')

class DocumentationTests(unittest.TestCase):
    def test_repository_root_excludes_metadata_runtime_and_symlinks(self):
        import json
        import sys
        sys.path.insert(0, str(TOOLS / 'docs'))
        docs = module('root_docs', 'docs/serve.py')
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'README.md').write_text('# Guide')
            for name in ('.git', '_build', 'node_modules'):
                (root / name).mkdir()
                (root / name / 'private.md').write_text('excluded')
            (root / 'escape.md').symlink_to(root / '.git/private.md')
            docs.CONFIG = root / 'workspace.json'
            docs.BUILD = root / '_build/bunko/docs'
            docs.SOURCE = docs.BUILD / 'source'
            docs.CONFIG.write_text(json.dumps({'name':'Example','repositories':{'example':'.'},
                'documentation':[{'id':'guide','label':'Guide','repository':'example','path':'.'}]}))
            docs.prepare()
            self.assertTrue((docs.SOURCE / 'guide/README.md').exists())
            for name in ('.git', '_build', 'node_modules', 'escape.md'):
                self.assertFalse((docs.SOURCE / 'guide' / name).exists())
            before = docs.signature()
            (root / '_build/noise').write_text('not a source change')
            self.assertEqual(before, docs.signature())

    def test_multiple_roots_map_back_to_sources_and_removed_roots_disappear(self):
        import json
        import sys
        sys.path.insert(0, str(TOOLS / 'docs'))
        docs = module('docs_serve', 'docs/serve.py')
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for language in ('en', 'es'):
                (root / language).mkdir()
                (root / language / 'README.md').write_text('# Guide\n\n## Start\n')
            docs.CONFIG = root / 'workspace.json'
            docs.BUILD = root / 'generated'
            docs.SOURCE = docs.BUILD / 'source'
            config = {'name':'Test', 'repositories':{'example':'.'},'documentation':[{'id':lang,'label':lang,'repository':'example','path':lang} for lang in ('en','es')]}
            docs.CONFIG.write_text(json.dumps(config))
            docs.prepare()
            index = json.loads((docs.SOURCE / 'assets/palette-index.json').read_text())
            self.assertEqual(index['sources']['es/README.md'], {'repository':'example','path':'es/README.md'})
            self.assertTrue((docs.SOURCE / 'en/README.md').exists())
            config['documentation'].pop()
            docs.CONFIG.write_text(json.dumps(config))
            docs.prepare()
            self.assertFalse((docs.SOURCE / 'es').exists())
            (root / 'en' / 'README.md').rename(root / 'en' / 'guide.md')
            docs.prepare()
            self.assertIn('(en/guide.md)', (docs.SOURCE / 'index.md').read_text())
            self.assertFalse((docs.SOURCE / 'en' / 'README.md').exists())
            import os
            from unittest.mock import patch
            with patch.dict(os.environ, {"BUNKO_DEV_TOOLS": "1"}):
                docs.prepare(dev=True)
            self.assertIn('tidewave_root', (docs.BUILD / 'mkdocs.yml').read_text())
            self.assertIn('site_dir: site-dev', (docs.BUILD / 'mkdocs.yml').read_text())
            self.assertNotIn('tidewave', (docs.BUILD / 'mkdocs.build.yml').read_text())

class CommitTests(unittest.TestCase):
    def test_commit_preserves_unrelated_staged_work(self):
        api = module('review_commit', 'review/api/service.py')
        with tempfile.TemporaryDirectory() as folder:
            repo = Path(folder).resolve()
            def git(*args):
                return subprocess.check_output(['git','-C',str(repo),*args],text=True).strip()
            git('init','-q')
            git('config','user.name','Test User')
            git('config','user.email','test@example.test')
            (repo / 'one.md').write_text('one')
            (repo / 'two.md').write_text('two')
            git('add','.')
            git('commit','-qm','initial')
            (repo / 'one.md').write_text('changed one')
            (repo / 'two.md').write_text('changed two')
            git('add','two.md')
            api.repository = lambda name: repo
            api.commit('example','docs: update one',['one.md'])
            self.assertEqual(git('show','HEAD:two.md'),'two')
            self.assertEqual(git('diff','--cached','--name-only'),'two.md')
            with self.assertRaises(api.GitError):
                api._range(None,'--output=outside')

if __name__ == '__main__':
    unittest.main()
