"""Build a deterministic Bunko release bundle from verified local build outputs."""
from __future__ import annotations

import gzip
import hashlib
import io
import json
from pathlib import Path
import sys
import tarfile
import subprocess

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from bunko_app.cli import IGNORE, PAYLOAD


def files():
    for name in (*PAYLOAD, "bunko", "README.md"):
        source = ROOT / name
        if source.is_file():
            yield source
            continue
        for path in sorted(source.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(source)
            if any(IGNORE(path.parent, [part]) for part in relative.parts):
                continue
            if path.is_symlink():
                raise ValueError(f"Release payload must not contain symlinks: {path}")
            yield path


def main():
    for asset in ("tools/review/web/dist/index.html", "tools/docs/assets/assets/diffs/entry.js"):
        if not (ROOT / asset).is_file():
            raise SystemExit(f"Missing release asset: {asset}. Run mise run assets:build first.")
    version = (ROOT / "VERSION").read_text().strip()
    contents = {p.relative_to(ROOT).as_posix(): p.read_bytes() for p in files()}
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    dirty = bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, text=True).strip())
    manifest = {"schema_version": 1, "version": version,
                "provenance": {"repository": "NakamaDevs/Bunko", "commit": revision, "dirty": dirty,
                               "python": sys.version.split()[0],
                               "node": subprocess.check_output(['node','--version'], text=True).strip(),
                               "uv": subprocess.check_output(['uv','--version'], text=True).strip()},
                "files": {name: hashlib.sha256(data).hexdigest() for name, data in sorted(contents.items())}}
    contents["bundle.json"] = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
    output = ROOT / "dist"
    output.mkdir(exist_ok=True)
    archive = output / f"bunko-{version}.tar.gz"
    with archive.open("wb") as stream, gzip.GzipFile(fileobj=stream, mode="wb", filename="", mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode="w") as tar:
            for name, data in sorted(contents.items()):
                info = tarfile.TarInfo(name)
                info.size, info.mtime, info.uid, info.gid = len(data), 0, 0, 0
                info.mode = 0o755 if name == "bunko" else 0o644
                tar.addfile(info, io.BytesIO(data))
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (output / "SHA256SUMS").write_text(f"{digest}  {archive.name}\n")
    pin = {"schema_version": 1, "repository": "NakamaDevs/Bunko", "version": version,
           "asset": archive.name, "sha256": digest}
    (output / "bunko.lock.json").write_text(json.dumps(pin, indent=2) + "\n")
    print(f"{archive}\nSHA256: {digest}")


if __name__ == "__main__": main()
