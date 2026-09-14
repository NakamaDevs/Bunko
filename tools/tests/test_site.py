"""Render a consumer's own MkDocs configuration through Bunko's site mode."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS / 'docs'))
sys.path.insert(0, str(TOOLS / 'review'))

CONSUMER = """site_name: Consumer
docs_dir: docs
nav:
  - Home: README.md
  - Guides:
      - Setup: guide/setup.md
theme:
  name: material
  logo: assets/logo.png
  custom_dir: overrides
plugins:
  - search
  - macros:
      module_name: macros
      render_by_default: false
hooks:
  - hooks.py
markdown_extensions:
  - pymdownx.superfences:
      custom_fences:
        - name: mermaid
          class: mermaid
          format: !!python/name:pymdownx.superfences.fence_code_format
extra_css:
  - stylesheets/brand.css
extra:
  palette:
    linear_workspace: consumer
"""


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, TOOLS / path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


class SiteModeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = self.root = Path(self.temp.name).resolve()
        subprocess.run(['git', 'init', '-q', str(root)], check=True)
        (root / '.gitignore').write_text('/_build/\n.bunko-site*.yml\n')
        (root / 'docs/guide').mkdir(parents=True)
        (root / 'docs/stylesheets').mkdir()
        (root / 'docs/assets').mkdir()
        (root / 'docs/assets/logo.png').write_bytes(b'png')
        (root / 'docs/stylesheets/brand.css').write_text(':root { --bd-accent: #EF4503; }')
        (root / 'docs/README.md').write_text('# Home\n\n[Setup](guide/setup.md)\n')
        (root / 'docs/guide/setup.md').write_text('---\nrender_macros: true\n---\n# Setup\n\n## Install\n\nValue: {{ answer() }}\n\n[Source](../../app.py)\n')
        (root / 'app.py').write_text('print(1)\n')
        (root / 'overrides').mkdir()
        (root / 'overrides/consumer.txt').write_text('consumer')
        (root / 'macros.py').write_text('def define_env(env):\n    env.macro(lambda: "forty-two", "answer")\n')
        # Zensical 0.0.58 accepts hooks but does not run them; they must still resolve.
        (root / 'hooks.py').write_text('def on_page_markdown(markdown, page, config, files):\n    return markdown\n')
        (root / 'mkdocs.yml').write_text(CONSUMER)
        (root / 'apps.json').write_text(json.dumps({'applications': [['api', 'https://api.localhost/']]}))
        (root / 'workspace.json').write_text(json.dumps({
            'name': 'Consumer', 'repositories': {'consumer': '.'},
            'documentation': [{'id': 'docs', 'label': 'Docs', 'repository': 'consumer', 'path': 'docs'}],
            'site': {'config': 'mkdocs.yml'}, 'palette': {'applications_file': 'apps.json'}}))
        self.docs = module('site_serve', 'docs/serve.py')
        self.docs.CONFIG = root / 'workspace.json'
        self.docs.BUILD = root / '_build/bunko/docs'

    def test_renders_consumer_settings_with_bunko_overlay(self):
        rendered = self.docs.prepare()
        text = rendered.read_text()
        self.assertEqual(rendered, self.root / '.bunko-site.build.yml')
        self.assertIn('!!python/name:pymdownx.superfences.fence_code_format', text)
        settings = __import__('yaml').load(text, Loader=self.docs.Loader)
        self.assertEqual(settings['docs_dir'], 'docs')
        self.assertEqual(settings['theme']['logo'], 'assets/logo.png')
        self.assertEqual(settings['extra_css'][0], 'stylesheets/palette.css')
        self.assertEqual(settings['extra_css'][-1], 'stylesheets/brand.css')
        theme = self.docs.BUILD / 'theme'
        self.assertTrue((theme / 'partials/bunko-head.html').exists())
        self.assertTrue((theme / 'consumer.txt').exists())
        index = json.loads((theme / 'assets/palette-index.json').read_text())
        self.assertIn([0, 'Setup', 'guide/setup/', 'Guides', 'guide/setup.md'], index['entries'])
        self.assertEqual(index['sources']['guide/setup.md'], {'repository': 'consumer', 'path': 'docs/guide/setup.md'})
        self.assertEqual(index['applications'], [['api', 'https://api.localhost/']])
        self.assertEqual(index['linear'], 'consumer')
        self.assertFalse((self.root / 'docs/assets/palette-index.json').exists())

        with patch.dict(os.environ, {'BUNKO_DEV_TOOLS': '1'}):
            dev = self.docs.prepare(dev=True)
        self.assertIn('tidewave_root', dev.read_text())
        self.assertNotIn('tidewave_root', rendered.read_text())

        zensical = Path(sys.executable).parent / 'zensical'
        result = subprocess.run([zensical, 'build', '-f', rendered], cwd=self.root, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        page = (self.docs.BUILD / 'site/guide/setup/index.html').read_text()
        self.assertIn('forty-two', page)
        self.assertIn('javascripts/annotations.js', page)
        self.assertTrue((self.docs.BUILD / 'site/assets/palette-index.json').exists())

    def test_requires_ignored_rendered_config_and_unshadowed_assets(self):
        (self.root / '.gitignore').write_text('/_build/\n')
        with self.assertRaisesRegex(ValueError, 'gitignore'):
            self.docs.prepare()
        (self.root / '.gitignore').write_text('/_build/\n.bunko-site*.yml\n')
        (self.root / 'docs/javascripts').mkdir()
        (self.root / 'docs/javascripts/palette.js').write_text('old copy')
        with self.assertRaisesRegex(ValueError, 'javascripts/palette.js'):
            self.docs.prepare()

    def test_rejects_docs_dir_outside_documentation_root(self):
        (self.root / 'mkdocs.yml').write_text(CONSUMER.replace('docs_dir: docs', 'docs_dir: overrides'))
        with self.assertRaisesRegex(ValueError, 'docs_dir'):
            self.docs.prepare()


class ReviewAppearanceTests(unittest.TestCase):
    def test_title_and_stylesheets_come_from_workspace(self):
        appearance = module('appearance', 'review/appearance.py')
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            (root / 'theme.css').write_text(':root { --paper: #fff; }')
            (root / 'workspace.json').write_text(json.dumps({'review': {
                'title': 'Team <Review>', 'stylesheets': ['theme.css', '../outside.css']}}))
            title, sheets = appearance.load(root / 'workspace.json')
            self.assertEqual(sheets, [root / 'theme.css'])
            document = appearance.render('<head><title>Bunko Review</title></head>', title, len(sheets))
            self.assertEqual(document, '<head><title>Team &lt;Review&gt;</title>'
                                       '<link rel="stylesheet" href="/bunko-theme/0.css" /></head>')


if __name__ == '__main__':
    unittest.main()
