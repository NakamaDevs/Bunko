"""Bundle @pierre/diffs into the documentation site, same-origin.

The library resolves Shiki grammars through dynamic imports, so a plain bundle
emits a chunk for every language Shiki ships: 318 files and about 11 MB. The
documentation uses a handful of languages, so this keeps an allowlist and drops
the rest. Shared chunks are always kept, because grammars embed one another.

The output is generated and ignored by Git. Run it through
``mise run docs:codeview`` after changing the allowlist or the pinned version.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ENTRY = Path(__file__).resolve().parent / "entry.mjs"
OUTPUT = ROOT / "tools" / "docs" / "assets" / "assets" / "diffs"
ESBUILD = ROOT / "node_modules" / ".bin" / "esbuild"

# Languages the documentation can render. Shiki's own ids, not Markdown
# aliases: `sh` and `bash` are both `shellscript`, `text` has no grammar.
LANGUAGES = {
    "shellscript", "python", "typescript", "javascript", "json", "yaml",
    "toml", "markdown", "sql", "ini", "diff", "vue", "html", "css", "xml",
    "docker", "tsx", "jsx", "csharp", "go", "rust", "java", "ruby", "php",
}

# The viewer's own themes are emitted as chunks too, and are always needed.
THEMES = {"pierre-light", "pierre-dark"}

_CHUNK = re.compile(r"^(?P<name>.+)-[A-Z0-9]{8}\.js$")


def bundle() -> None:
    if not ESBUILD.exists():
        raise SystemExit(f"esbuild not found at {ESBUILD}. Run npm install.")
    if OUTPUT.exists():
        shutil.rmtree(OUTPUT)
    OUTPUT.mkdir(parents=True)
    subprocess.run(
        [
            str(ESBUILD), str(ENTRY), "--bundle", "--format=esm", "--splitting",
            f"--outdir={OUTPUT}", "--platform=browser", "--target=es2022", "--minify",
        ],
        check=True, cwd=ROOT, capture_output=True, text=True,
    )


def prune() -> tuple[int, int]:
    removed = kept = 0
    for path in OUTPUT.glob("*.js"):
        if path.name == "entry.js" or path.name.startswith("chunk-"):
            kept += 1
            continue
        match = _CHUNK.match(path.name)
        if match and match.group("name") in LANGUAGES | THEMES:
            kept += 1
            continue
        path.unlink()
        # Source maps are not emitted by default, but stay tidy if they are.
        path.with_suffix(".js.map").unlink(missing_ok=True)
        removed += 1
    return kept, removed


def main() -> int:
    bundle()
    kept, removed = prune()
    size = sum(path.stat().st_size for path in OUTPUT.rglob("*")) / 1024 / 1024
    print(f"codeview bundle: {kept} files kept, {removed} unused grammars removed, {size:.1f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
