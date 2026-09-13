"""Read-only Git API for the local code review tool.

Serves the repositories already checked out under ``repos/`` so they can be
browsed, diffed, and commented on locally, without pushing a branch or opening
anything on GitHub. Comments are not stored here: the documentation notes
service owns them, so one database holds both prose notes and code comments.

Browsing is read-only. Editing is not: a file can be written and the result
committed, which is why every path is resolved inside its repository and
refused otherwise. Nothing is pushed, no branch is changed, and no history is
rewritten.

Every Git invocation is built from an argument list, never a shell string.
Repository names are resolved through the Aspire source catalogue rather than
taken from the request.

The service binds to the loopback interface and performs no authentication. It
exposes source code, so do not expose it beyond this machine.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HOST = "127.0.0.1"
# Aspire assigns a port; standalone runs keep a predictable one.
PORT = int(os.environ.get("PORT") or 8901)
WORKSPACE_ROOT = Path(os.environ.get("BUNKO_ROOT", Path.cwd())).resolve()
SOURCE_CATALOG = Path(os.environ.get("BUNKO_CONFIG", WORKSPACE_ROOT / "workspace.json")).resolve()

# A diff of a very large range can take a long time and produce a huge payload.
MAX_PATCH_BYTES = 8 * 1024 * 1024
GIT_TIMEOUT = 30


class GitError(RuntimeError):
    """A Git command failed, or the request named something that does not exist."""


def repositories() -> dict[str, Path]:
    """Repository name to checkout path, from the Aspire source catalogue."""
    if not SOURCE_CATALOG.exists():
        return {}
    catalog = json.loads(SOURCE_CATALOG.read_text(encoding="utf-8"))
    found = {}
    for name, relative in catalog["repositories"].items():
        path = (SOURCE_CATALOG.parent / relative).resolve()
        if (path / ".git").exists():
            found[name] = path
    return dict(sorted(found.items()))


def repository(name: str) -> Path:
    try:
        return repositories()[name]
    except KeyError:
        raise GitError(f"Unknown repository {name!r}.") from None


def git(path: Path, *args: str) -> str:
    """Run one Git command inside a known checkout."""
    try:
        result = subprocess.run(
            ["git", "--literal-pathspecs", "-C", str(path), *args],
            capture_output=True, text=True, timeout=GIT_TIMEOUT, check=True,
        )
    except subprocess.TimeoutExpired:
        raise GitError("Git did not finish in time.") from None
    except subprocess.CalledProcessError as error:
        raise GitError((error.stderr or "Git failed.").strip().split("\n")[0]) from None
    return result.stdout


def _records(raw: str, fields: tuple[str, ...], separator: str = "\x1f") -> list[dict]:
    rows = []
    for line in raw.split("\x1e"):
        line = line.strip("\n")
        if not line:
            continue
        values = line.split(separator)
        rows.append(dict(zip(fields, values)))
    return rows


def overview(name: str) -> dict:
    path = repository(name)
    head = git(path, "rev-parse", "--abbrev-ref", "HEAD").strip()
    status = git(path, "status", "--porcelain")
    return {
        "name": name,
        "path": str(path),
        "head": head,
        "dirty": bool(status.strip()),
        "changed_files": len([line for line in status.splitlines() if line.strip()]),
    }


def refs(name: str) -> dict:
    path = repository(name)
    branches = _records(
        git(path, "for-each-ref", "--sort=-committerdate", "--count=60",
            "--format=%(refname:short)\x1f%(committerdate:iso8601)\x1f%(subject)\x1e",
            "refs/heads", "refs/remotes"),
        ("name", "date", "subject"),
    )
    commits = _records(
        git(path, "log", "-40", "--format=%h\x1f%an\x1f%ad\x1f%s\x1e", "--date=iso8601"),
        ("hash", "author", "date", "subject"),
    )
    return {"branches": branches, "commits": commits, "head": overview(name)["head"]}


def _range(base: str | None, head: str | None) -> list[str]:
    """Everything uncommitted by default; otherwise the range the UI asked for.

    A bare ``git diff`` hides staged work, which is exactly the work being
    reviewed, so the default compares the working tree against ``HEAD``.
    """
    if any(value and value.startswith("-") for value in (base, head)):
        raise GitError("Invalid revision.")
    if base and head:
        return [f"{base}...{head}"]
    if head:
        return [head]
    return ["HEAD"]


def changed_files(name: str, base: str | None, head: str | None) -> list[dict]:
    path = repository(name)
    args = ["diff", "--numstat", "--find-renames", *_range(base, head)]
    rows = []
    for line in git(path, *args).splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        added, removed, file_path = parts
        rows.append({
            "path": file_path,
            "added": None if added == "-" else int(added),
            "removed": None if removed == "-" else int(removed),
            "binary": added == "-",
        })
    return rows


def patch(name: str, base: str | None, head: str | None, file_path: str | None) -> str:
    path = repository(name)
    args = ["diff", "--find-renames", "--no-color", *_range(base, head)]
    if file_path:
        args += ["--", file_path]
    text = git(path, *args)
    if len(text.encode("utf-8")) > MAX_PATCH_BYTES:
        raise GitError("This diff is too large to render; choose a single file.")
    return text


def tree(name: str, revision: str) -> list[str]:
    if revision.startswith("-"):
        raise GitError("Invalid revision.")
    path = repository(name)
    if revision == "WORKTREE":
        return sorted(set(git(path, "ls-files", "--cached", "--others", "--exclude-standard").splitlines()))
    return [line for line in git(path, "ls-tree", "-r", "--name-only", revision).splitlines() if line]


# The working tree is not a revision, so the UI asks for it by this name.
WORKTREE = "WORKTREE"


def blob(name: str, revision: str, file_path: str) -> str | None:
    """File contents at a revision, or None when the file does not exist there."""
    path = repository(name)
    if file_path.startswith("/") or ".." in Path(file_path).parts or ".git" in Path(file_path).parts:
        raise GitError("Invalid path.")

    if revision == WORKTREE:
        target = _inside(path, file_path)
        if not target.is_relative_to(path):
            raise GitError("Invalid path.")
        if not target.is_file():
            return None
        try:
            return target.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            raise GitError("This file is not text.") from None

    try:
        return git(path, "show", f"{revision}:{file_path}")
    except GitError:
        # A file added in this range has no contents on the old side.
        return None


# Porcelain codes, mapped to the statuses the file tree can decorate with.
_STATUS = {
    "?": "untracked", "!": "ignored", "A": "added", "D": "deleted",
    "M": "modified", "R": "renamed", "C": "added", "U": "modified", "T": "modified",
}


def status(name: str) -> list[dict]:
    """Working-tree status, so the file tree can mark what changed."""
    path = repository(name)
    rows = []
    for line in git(path, "status", "--porcelain").splitlines():
        if len(line) < 4:
            continue
        code = line[0] if line[0] != " " else line[1]
        file_path = line[3:]
        # A rename is reported as "old -> new"; decorate the destination.
        if " -> " in file_path:
            file_path = file_path.split(" -> ", 1)[1]
        rows.append({"path": file_path.strip('"'), "status": _STATUS.get(code, "modified")})
    return rows


def _inside(repository_path: Path, file_path: str) -> Path:
    """Resolve a request path inside its repository, or refuse it."""
    if not file_path or file_path.startswith("/") or ".." in Path(file_path).parts or ".git" in Path(file_path).parts:
        raise GitError("Invalid path.")
    resolved = (repository_path / file_path).resolve()
    if not resolved.is_relative_to(repository_path):
        raise GitError("Invalid path.")
    if ".git" in resolved.relative_to(repository_path).parts:
        raise GitError("Invalid path.")
    return resolved


def write_file(name: str, file_path: str, contents: str) -> dict:
    """Write one file in the working tree. The editor's save."""
    repository_path = repository(name)
    target = _inside(repository_path, file_path)
    if not target.parent.exists():
        raise GitError("That directory does not exist.")
    target.write_text(contents, encoding="utf-8")
    return {"path": file_path, "bytes": len(contents.encode("utf-8"))}


def commit(name: str, message: str, paths: list[str]) -> dict:
    """Commit the named paths. Nothing is pushed and no branch is changed."""
    message = (message or "").strip()
    if not message:
        raise GitError("A commit needs a message.")
    if not paths:
        raise GitError("A commit needs at least one file.")

    repository_path = repository(name)
    for file_path in paths:
        _inside(repository_path, file_path)

    git(repository_path, "add", "--", *paths)
    staged = git(repository_path, "diff", "--cached", "--name-only", "--", *paths).strip()
    if not staged:
        raise GitError("Those files have no changes to commit.")

    git(repository_path, "commit", "-m", message, "--", *paths)
    head = git(repository_path, "rev-parse", "--short", "HEAD").strip()
    return {"commit": head, "files": staged.splitlines(), "branch": overview(name)["head"]}


class Handler(BaseHTTPRequestHandler):
    server_version = "BunkoReview/1.0"

    def log_message(self, *_args) -> None:  # noqa: D102 - quiet by default
        pass

    def _send(self, status: int, payload: object) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._send(204, {})

    def _payload(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(length) or b"{}") if length else {}

    def do_POST(self) -> None:  # noqa: N802
        if self.headers.get("Origin"):
            self._send(403, {"error": "Use the workspace gateway."})
            return
        parts = [part for part in urlparse(self.path).path.strip("/").split("/") if part]
        try:
            payload = self._payload()
            if len(parts) == 4 and parts[:2] == ["api", "repos"]:
                name, action = parts[2], parts[3]
                if action == "file":
                    return self._send(200, write_file(name, payload.get("path"), payload.get("contents") or ""))
                if action == "commit":
                    return self._send(200, commit(name, payload.get("message"), payload.get("paths") or []))
            self._send(404, {"error": "Unknown endpoint."})
        except GitError as error:
            self._send(400, {"error": str(error)})
        except (json.JSONDecodeError, TypeError) as error:
            self._send(400, {"error": f"Bad request: {error}"})
        except Exception as error:  # noqa: BLE001 - a local tool reports its own faults
            self._send(500, {"error": f"{type(error).__name__}: {error}"})

    def do_GET(self) -> None:  # noqa: N802
        url = urlparse(self.path)
        query = {key: values[0] for key, values in parse_qs(url.query).items()}
        parts = [part for part in url.path.strip("/").split("/") if part]

        try:
            self._send(200, self._route(parts, query))
        except GitError as error:
            self._send(400, {"error": str(error)})
        except Exception as error:  # noqa: BLE001 - a local tool reports its own faults
            self._send(500, {"error": f"{type(error).__name__}: {error}"})

    def _route(self, parts: list[str], query: dict) -> object:
        if parts == ["api", "health"]:
            return {"ok": True}
        if parts == ["api", "repos"]:
            return {"repositories": [overview(name) for name in repositories()]}
        if len(parts) == 4 and parts[:2] == ["api", "repos"]:
            name, action = parts[2], parts[3]
            if action == "refs":
                return refs(name)
            if action == "changes":
                return {
                    "files": changed_files(name, query.get("base"), query.get("head")),
                    "base": query.get("base"),
                    "head": query.get("head"),
                }
            if action == "patch":
                return {"patch": patch(name, query.get("base"), query.get("head"), query.get("path"))}
            if action == "tree":
                return {"paths": tree(name, query.get("rev") or "HEAD")}
            if action == "status":
                return {"status": status(name)}
            if action == "blob":
                path = query.get("path")
                if not path:
                    raise GitError("A path is required.")
                return {"path": path, "contents": blob(name, query.get("rev") or "HEAD", path)}
            if action == "sides":
                path = query.get("path")
                if not path:
                    raise GitError("A path is required.")
                base = query.get("base") or "HEAD"
                head = query.get("head") or WORKTREE
                return {
                    "path": path,
                    "old": blob(name, base, path),
                    "new": blob(name, head, path),
                }
        raise GitError("Unknown endpoint.")


def main() -> int:
    found = repositories()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"code review API on http://{HOST}:{PORT}/api  ({len(found)} repositories)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
