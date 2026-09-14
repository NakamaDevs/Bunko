#!/usr/bin/env python3
"""Download the consumer's exact private Bunko release and invoke its CLI."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile


def unpack(archive, destination):
    with tarfile.open(archive, "r:gz") as bundle:
        members = bundle.getmembers()
        names = set()
        total = 0
        for member in members:
            name = PurePosixPath(member.name)
            if (name.is_absolute() or ".." in name.parts or "\\" in member.name
                    or not member.isfile() or member.name in names):
                raise ValueError("Unsafe or duplicate release archive entry")
            names.add(member.name)
            total += member.size
            if total > 512 * 1024 * 1024:
                raise ValueError("Release exceeds the unpacked size limit")
        for member in members:
            path = destination.joinpath(*PurePosixPath(member.name).parts)
            path.parent.mkdir(parents=True, exist_ok=True)
            with bundle.extractfile(member) as source, path.open("wb") as target:
                shutil.copyfileobj(source, target)
            path.chmod(0o755 if member.name == "bunko" else 0o644)
    manifest = json.loads((destination / "bundle.json").read_text())
    if set(manifest["files"]) != names - {"bundle.json"}:
        raise ValueError("Release manifest file list does not match archive")
    for name, digest in manifest["files"].items():
        if hashlib.sha256((destination / name).read_bytes()).hexdigest() != digest:
            raise ValueError("Release manifest checksum mismatch")


def main():
    root = Path(__file__).resolve().parent.parent
    pin = json.loads((root / "bunko.lock.json").read_text())
    if pin.get("schema_version") != 1 or pin.get("repository") != "NakamaDevs/Bunko":
        raise ValueError("Unsupported Bunko release pin")
    version = pin["version"]
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:-[a-zA-Z0-9.-]+)?", version):
        raise ValueError("An exact Bunko version is required")
    if pin["asset"] != f"bunko-{version}.tar.gz" or not re.fullmatch(r"[a-f0-9]{64}", pin["sha256"]):
        raise ValueError("Invalid Bunko release asset or SHA256")
    cache_root = Path(os.environ.get("BUNKO_CACHE", Path.home() / ".cache/bunko")).expanduser()
    cache_root.mkdir(parents=True, exist_ok=True)
    installed = cache_root / pin["sha256"]
    if not installed.is_dir():
        with tempfile.TemporaryDirectory(prefix="download-", dir=cache_root) as directory:
            temporary = Path(directory)
            subprocess.run(["gh", "release", "download", f"v{version}", "--repo", pin["repository"],
                            "--pattern", pin["asset"], "--dir", str(temporary)], check=True)
            archive = temporary / pin["asset"]
            if hashlib.sha256(archive.read_bytes()).hexdigest() != pin["sha256"]:
                raise ValueError("Bunko release checksum does not match bunko.lock.json")
            stage = temporary / "unpacked"
            stage.mkdir()
            unpack(archive, stage)
            try:
                stage.rename(installed)
            except OSError:
                if not installed.is_dir():
                    raise
    return subprocess.call([sys.executable, str(installed / "bunko"), *sys.argv[1:]], cwd=root)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        print(f"bunko: {error}", file=sys.stderr)
        raise SystemExit(1)
