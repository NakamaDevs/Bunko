"""List third-party packages and their licenses, and collect the notices a release must carry.

The inventory comes from the committed lock files, so it is the same on every
platform. Python license names come from the installed environment, because
``uv.lock`` does not record them.

    python scripts/licenses.py          # rewrite THIRD_PARTY_LICENSES.md
    python scripts/licenses.py --check  # fail when the file is stale or a license is not allowed
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "THIRD_PARTY_LICENSES.md"
NPM_LOCKS = ("package-lock.json", "tools/review/web/package-lock.json")
SITE_PACKAGES = "tools/.venv/lib/python*/site-packages"

# Licenses that permit redistribution in the release bundle with a notice only.
BUNDLE_ALLOWED = {"MIT", "ISC", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "0BSD"}
# Packages that a package manager installs on the user's machine are not
# redistributed by Bunko, so file-level copyleft and similar terms are acceptable.
INSTALLED_ALLOWED = BUNDLE_ALLOWED | {"MPL-2.0", "PSF-2.0", "BlueOak-1.0.0", "AFL-2.1"}

# Spellings that package metadata uses for an SPDX identifier.
SPELLINGS = {
    "apache 2.0": "Apache-2.0", "apache license 2.0": "Apache-2.0", "apache software license": "Apache-2.0",
    "mit license": "MIT", "mit licence": "MIT",
    "mozilla public license 2.0 (mpl 2.0)": "MPL-2.0",
    "python software foundation license": "PSF-2.0",
}
# Python packages whose metadata does not give one usable identifier. Each value
# was read from the license file of the package.
PYTHON_OVERRIDES = {
    "duckdb": "MIT",
    "hjson": "MIT OR AFL-2.1",
    "jinja2": "BSD-3-Clause",
    "mergedeep": "MIT",
    "python-dateutil": "Apache-2.0 AND BSD-3-Clause",
}
NOTICE_FILE = re.compile(r"^(licen[sc]e|notice|copying)([.-].*)?$", re.IGNORECASE)


def spdx(text):
    text = (text or "").strip()
    known = {name.lower(): name for name in INSTALLED_ALLOWED}
    return known.get(text.lower()) or SPELLINGS.get(text.lower()) or text


def npm_packages():
    """Yield (scope, name, version, license, directory) for each locked npm package."""
    for lock in NPM_LOCKS:
        base = (ROOT / lock).parent
        for path, entry in json.loads((ROOT / lock).read_text())["packages"].items():
            if not path or entry.get("link"):
                continue
            name = path.rsplit("node_modules/", 1)[1]
            development = entry.get("dev") or entry.get("devOptional")
            yield ("development" if development else "bundle", name, entry["version"],
                   spdx(entry.get("license")), base / path)


def python_packages():
    """Yield (name, version, license) for each locked Python package that is installed."""
    metadata = {}
    for path in ROOT.glob(f"{SITE_PACKAGES}/*.dist-info/METADATA"):
        header = path.read_text(errors="replace").split("\n\n", 1)[0]
        fields = dict(re.findall(r"^(Name|License-Expression|License): (.+)$", header, re.MULTILINE))
        classifiers = re.findall(r"^Classifier: License :: (?:OSI Approved :: )?(.+)$", header, re.MULTILINE)
        name = re.sub(r"[-_.]+", "-", fields["Name"]).lower()
        declared = fields.get("License-Expression") or fields.get("License") or ""
        if spdx(declared) not in INSTALLED_ALLOWED and " " in declared.strip() and classifiers:
            declared = classifiers[0]
        metadata[name] = PYTHON_OVERRIDES.get(name) or spdx(declared or (classifiers[0] if classifiers else ""))
    if not metadata:
        raise SystemExit("No Python environment found. Run mise run setup first.")
    for package in tomllib.loads((ROOT / "tools/uv.lock").read_text())["package"]:
        name = re.sub(r"[-_.]+", "-", package["name"]).lower()
        if name in metadata:
            yield name, package["version"], metadata[name]


def collect():
    """Return {scope: {(name, version): license}} for the three scopes."""
    scopes = {"bundle": {}, "installed": {}, "development": {}}
    locations = {}
    for scope, name, version, license_name, directory in npm_packages():
        scopes[scope][(name, version)] = license_name
        if scope == "bundle":
            locations.setdefault((name, version), directory)
    for key in scopes["bundle"]:
        scopes["development"].pop(key, None)
    for name, version, license_name in python_packages():
        scopes["installed"][(name, version)] = license_name
    return scopes, locations


def terms(expression):
    return [term for term in re.split(r"\s+(?:AND|OR)\s+|[()]", expression) if term]


def problems(scopes):
    found = []
    for scope, allowed in (("bundle", BUNDLE_ALLOWED), ("installed", INSTALLED_ALLOWED), ("development", INSTALLED_ALLOWED)):
        for (name, version), license_name in sorted(scopes[scope].items()):
            if not license_name or any(term not in allowed for term in terms(license_name)):
                found.append(f"{name} {version}: license {license_name or 'missing'!r} is not allowed in scope {scope}")
    return found


SECTIONS = (
    ("bundle", "Release bundle",
     "Production dependencies of the two npm packages. The build bundles their code into\n"
     "`tools/review/web/dist` and `tools/docs/assets/assets/diffs`, and the release archive\n"
     "contains that output. The archive carries their license texts in `THIRD_PARTY_NOTICES.txt`."),
    ("installed", "Installed by `bunko setup`",
     "Python packages that `uv` installs from PyPI on the user's machine. The release archive\n"
     "does not contain them."),
    ("development", "Build and development tools",
     "npm development dependencies. `bunko setup` installs those of the root package, which\n"
     "include the Aspire command-line tool. `--dev-tools` installs those of the reviewer. The\n"
     "release archive does not contain them."),
)


def inventory(scopes):
    lines = ["# Third-party licenses", "",
             "`scripts/licenses.py` generates this file from the lock files. Do not edit it.",
             "Run `mise run licenses` after a dependency change.", ""]
    for scope, title, text in SECTIONS:
        counts = {}
        for license_name in scopes[scope].values():
            counts[license_name] = counts.get(license_name, 0) + 1
        summary = ", ".join(f"{name} ({count})" for name, count in sorted(counts.items(), key=lambda item: (-item[1], item[0])))
        lines += [f"## {title}", "", text, "", f"{len(scopes[scope])} packages: {summary}.", "",
                  "| Package | Version | License |", "| --- | --- | --- |"]
        lines += [f"| `{name}` | {version} | {license_name} |"
                  for (name, version), license_name in sorted(scopes[scope].items(), key=lambda item: (item[0][0].lower(), item[0][1]))]
        lines.append("")
    return "\n".join(lines)


def notices():
    """License and notice texts of every package whose code the release bundle can contain."""
    scopes, locations = collect()
    parts = ["Bunko third-party notices", "",
             "The Bunko release bundle contains code from these packages.",
             "Each section gives the license and notice files of one package.", ""]
    for (name, version), license_name in sorted(scopes["bundle"].items(), key=lambda item: (item[0][0].lower(), item[0][1])):
        directory = locations[(name, version)]
        if not directory.is_dir():
            raise SystemExit(f"Missing {directory}. Run mise run setup first.")
        files = sorted(path for path in directory.iterdir() if path.is_file() and NOTICE_FILE.match(path.name))
        parts += ["=" * 78, f"{name} {version}", f"License: {license_name}", "=" * 78, ""]
        if not files:
            parts += ["The package contains no license file. Its package.json declares the license above.", ""]
        for path in files:
            parts += [path.read_text(errors="replace").strip(), ""]
    return "\n".join(parts)


def main(argv):
    scopes, _ = collect()
    found = problems(scopes)
    text = inventory(scopes)
    if "--check" in argv:
        if not INVENTORY.exists() or INVENTORY.read_text() != text:
            found.append(f"{INVENTORY.name} is stale. Run mise run licenses.")
    else:
        INVENTORY.write_text(text)
        print(f"Wrote {INVENTORY.name}: " + ", ".join(f"{len(scopes[scope])} {scope}" for scope in scopes))
    for problem in found:
        print(f"licenses: {problem}", file=sys.stderr)
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
