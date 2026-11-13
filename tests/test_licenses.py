import contextlib
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("licenses", ROOT / "scripts/licenses.py")
licenses = importlib.util.module_from_spec(spec)
spec.loader.exec_module(licenses)


class LicenseTests(unittest.TestCase):
    def test_committed_inventory_names_the_current_version(self):
        # A dependency update does not regenerate the file. A version change must.
        self.assertEqual(licenses.INVENTORY.read_text().splitlines()[:len(licenses.heading())], licenses.heading(),
                         "THIRD_PARTY_LICENSES.md is for a different version. Run mise run licenses.")

    def test_inventory_lists_each_locked_package(self):
        scopes, _ = licenses.collect()
        text = licenses.inventory(scopes)
        for packages in scopes.values():
            for (name, version), license_name in packages.items():
                self.assertIn(f"| `{name}` | {version} | {license_name} |", text)

    def test_check_reports_a_stale_inventory(self):
        original = licenses.INVENTORY
        with tempfile.TemporaryDirectory() as directory:
            licenses.INVENTORY = Path(directory) / "THIRD_PARTY_LICENSES.md"
            try:
                licenses.INVENTORY.write_text("old\n")
                with contextlib.redirect_stderr(io.StringIO()) as errors:
                    self.assertEqual(licenses.main(["--check"]), 1)
                self.assertIn("is stale", errors.getvalue())
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(licenses.main([]), 0)
                self.assertEqual(licenses.main(["--check"]), 0)
            finally:
                licenses.INVENTORY = original

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

    def test_keeps_each_term_of_an_explicit_python_expression(self):
        header = "Name: example\nLicense-Expression: MIT AND GPL-3.0-only\nClassifier: License :: OSI Approved :: MIT License"
        self.assertEqual(licenses.python_license(header), "MIT AND GPL-3.0-only")
        scopes = {"bundle": {}, "installed": {("example", "1.0.0"): licenses.python_license(header)}, "development": {}}
        self.assertEqual(len(licenses.problems(scopes)), 1)

    def test_uses_every_classifier_when_python_metadata_has_no_known_license(self):
        header = ("Name: example\nLicense: Dual License\nClassifier: License :: OSI Approved :: MIT License\n"
                  "Classifier: License :: OSI Approved :: GNU General Public License v3 (GPLv3)")
        self.assertEqual(licenses.python_license(header), "MIT AND GNU General Public License v3 (GPLv3)")

    def test_notices_cover_every_bundled_package(self):
        scopes, _ = licenses.collect()
        text = licenses.notices()
        for name, version in scopes["bundle"]:
            self.assertIn(f"\n{name} {version}\nLicense: ", text)


if __name__ == "__main__": unittest.main()
