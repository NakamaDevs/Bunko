import json
from pathlib import Path
import tempfile
import unittest

from bunko_app.config import Workspace


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "guide").mkdir()
        self.path = self.root / "workspace.json"
        self.data = {"name": "Example", "repositories": {"example": "."},
                     "documentation": [{"id": "guide", "label": "Guide", "repository": "example", "path": "guide"}]}

    def load(self):
        self.path.write_text(json.dumps(self.data))
        return Workspace.load(self.path)

    def test_resolves_content_and_state_against_config_not_cwd(self):
        workspace = self.load()
        self.assertEqual(workspace.root, self.root.resolve())
        self.assertEqual(workspace.database, self.root.resolve() / "_build/state/notes.duckdb")
        self.assertEqual(workspace, self.load())

    def test_two_checkouts_have_distinct_default_routes(self):
        first = self.load()
        (self.root / "second/guide").mkdir(parents=True)
        second = self.root / "second/workspace.json"
        second.write_text(json.dumps(self.data))
        self.assertNotEqual(first.domain, Workspace.load(second).domain)

    def test_rejects_documentation_escape(self):
        self.data["documentation"][0]["path"] = ".."
        with self.assertRaises(ValueError): self.load()

    def test_rejects_destructive_state_root(self):
        self.data["runtime"] = {"state_dir": "."}
        with self.assertRaises(ValueError): self.load()

    def test_rejects_nonlocal_domain(self):
        self.data["runtime"] = {"domain": "example.com"}
        with self.assertRaises(ValueError): self.load()

    def test_rejects_boolean_port(self):
        self.data["runtime"] = {"port": True}
        with self.assertRaises(ValueError): self.load()

    def test_rejects_duplicate_mount(self):
        self.data["documentation"] *= 2
        with self.assertRaises(ValueError): self.load()

    def test_rejects_newer_schema(self):
        self.data["schema_version"] = 2
        with self.assertRaises(ValueError): self.load()


if __name__ == "__main__": unittest.main()
