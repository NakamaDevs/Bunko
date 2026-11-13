import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("licenses", ROOT / "scripts/licenses.py")
licenses = importlib.util.module_from_spec(spec)
spec.loader.exec_module(licenses)


class LicenseTests(unittest.TestCase):
    def test_committed_inventory_matches_the_lock_files(self):
        scopes, _ = licenses.collect()
        self.assertEqual(licenses.INVENTORY.read_text(), licenses.inventory(scopes),
                         "THIRD_PARTY_LICENSES.md is stale. Run mise run licenses.")

    def test_every_license_is_allowed_in_its_scope(self):
        scopes, _ = licenses.collect()
        self.assertEqual(licenses.problems(scopes), [])

    def test_rejects_copyleft_in_the_release_bundle(self):
        scopes = {"bundle": {("example", "1.0.0"): "GPL-3.0-only"}, "installed": {}, "development": {}}
        self.assertEqual(len(licenses.problems(scopes)), 1)

    def test_rejects_a_missing_license(self):
        scopes = {"bundle": {}, "installed": {("example", "1.0.0"): ""}, "development": {}}
        self.assertEqual(len(licenses.problems(scopes)), 1)

    def test_checks_each_term_of_an_expression(self):
        scopes = {"bundle": {("example", "1.0.0"): "MIT OR GPL-3.0-only"}, "installed": {}, "development": {}}
        self.assertEqual(len(licenses.problems(scopes)), 1)

    def test_notices_cover_every_bundled_package(self):
        scopes, _ = licenses.collect()
        text = licenses.notices()
        for name, version in scopes["bundle"]:
            self.assertIn(f"\n{name} {version}\nLicense: ", text)


if __name__ == "__main__": unittest.main()
