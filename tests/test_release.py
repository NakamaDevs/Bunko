import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("bootstrap", Path(__file__).resolve().parents[1] / "consumer/bunko.py")
bootstrap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootstrap)


class ReleaseTests(unittest.TestCase):
    def archive(self, names):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        archive = root / "bundle.tar.gz"
        with tarfile.open(archive, "w:gz") as tar:
            for name, data in names:
                entry = tarfile.TarInfo(name)
                entry.size = len(data)
                tar.addfile(entry, io.BytesIO(data))
        destination = root / "out"
        destination.mkdir()
        return archive, destination

    def test_rejects_path_traversal_before_writing(self):
        archive, destination = self.archive([("safe", b"ok"), ("../escape", b"bad")])
        with self.assertRaises(ValueError): bootstrap.unpack(archive, destination)
        self.assertEqual(list(destination.iterdir()), [])

    def test_rejects_duplicate_members(self):
        archive, destination = self.archive([("bunko", b"one"), ("bunko", b"two")])
        with self.assertRaises(ValueError): bootstrap.unpack(archive, destination)

    def test_checks_each_file_against_manifest(self):
        manifest = {"files": {"bunko": hashlib.sha256(b"expected").hexdigest()}}
        archive, destination = self.archive([("bunko", b"changed"), ("bundle.json", json.dumps(manifest).encode())])
        with self.assertRaises(ValueError): bootstrap.unpack(archive, destination)

    def test_extracts_verified_bundle(self):
        manifest = {"files": {"bunko": hashlib.sha256(b"expected").hexdigest()}}
        archive, destination = self.archive([("bunko", b"expected"), ("bundle.json", json.dumps(manifest).encode())])
        bootstrap.unpack(archive, destination)
        self.assertEqual((destination / "bunko").read_bytes(), b"expected")


if __name__ == "__main__": unittest.main()
