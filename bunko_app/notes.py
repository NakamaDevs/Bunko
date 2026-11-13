"""Read, resolve, and clear the comments of a running workspace from the command line.

The commands talk to the notes service through the loopback gateway, because
the service is the only process that may open the notes database. Each comment
gets the absolute path of its file on disk, so an agent can open the source.
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import urllib.error
import urllib.parse
import urllib.request

FORMATS = ("markdown", "json", "text")
KINDS = ("TODO", "QUESTION", "FIXME", "NOTE")


def add_arguments(commands, add_config):
    """Add ``bunko notes list|resolve|clear`` to the command parser."""
    notes = commands.add_parser("notes", help="Read, resolve, or clear comments of the running workspace")
    actions = notes.add_subparsers(dest="notes_command", required=True)
    for name, text in (("list", "Print comments with the path of each file on disk"),
                       ("clear", "Delete comments; all of them when no filter is given")):
        action = actions.add_parser(name, help=text)
        add_config(action)
        action.add_argument("--repo", help="Repository ID. Includes its worktrees. Use ID@worktree for one worktree")
        action.add_argument("--no-worktrees", action="store_true", help="Leave out comments on linked worktrees")
        action.add_argument("--page", help="Documentation page path, or the start of one, such as /guide/")
        action.add_argument("--source", choices=("docs", "review"), help="Only documentation comments, or only review comments")
        action.add_argument("--kind", choices=KINDS, type=str.upper, help="Only comments of this kind")
        if name == "list":
            action.add_argument("--all", action="store_true", help="Include resolved comments")
            action.add_argument("--format", choices=FORMATS, default="markdown", help="Output format; markdown is for an agent prompt")
        else:
            action.add_argument("--open-only", action="store_true", help="Keep resolved comments")
            action.add_argument("--yes", action="store_true", help="Delete without this flag is refused")
    resolve = actions.add_parser("resolve", help="Mark comments as resolved")
    add_config(resolve)
    resolve.add_argument("ids", nargs="+", type=int, metavar="ID")
    resolve.add_argument("--reopen", action="store_true", help="Mark the comments as open again")


class Client:
    """The notes API of one workspace, through its loopback gateway."""

    def __init__(self, workspace):
        self.base = f"http://127.0.0.1:{workspace.port}"

    def request(self, method, path, payload=None):
        data = None if payload is None else json.dumps(payload).encode()
        request = urllib.request.Request(self.base + path, data=data, method=method,
                                         headers={"Content-Type": "application/json"} if data else {})
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.loads(response.read() or b"{}")
        except urllib.error.HTTPError as error:
            raise ValueError(f"The notes service refused the request: HTTP {error.code}") from None
        except (urllib.error.URLError, OSError):
            raise ValueError("Bunko is not running for this workspace. Run bunko start first.") from None

    def notes(self):
        return self.request("GET", "/notes?all=1")["notes"]


class Locator:
    """Find the checkout and the file on disk that a comment refers to."""

    def __init__(self, workspace):
        self.workspace = workspace
        self.repositories = {name: (workspace.root / relative).resolve()
                             for name, relative in workspace.data["repositories"].items()}
        self.worktrees = {}
        self.pages = None

    def checkout(self, repo):
        """The directory of ``repo`` or of ``repo@worktree``; None when it is unknown."""
        if not repo:
            return None
        parent, _, slug = repo.partition("@")
        path = self.repositories.get(parent)
        if path is None or not slug:
            return path
        if parent not in self.worktrees:
            self.worktrees[parent] = linked_worktrees(path)
        return self.worktrees[parent].get(slug)

    def page_source(self, page_path):
        """The (repository, file) that a documentation page was made from."""
        if self.pages is None:
            self.pages = {}
            for folder in ("source", "theme"):
                index = self.workspace.state / "docs" / folder / "assets/palette-index.json"
                if index.is_file():
                    data = json.loads(index.read_text())
                    for entry in data.get("entries", []):
                        source = data.get("sources", {}).get(entry[4]) if entry[0] == 0 and len(entry) > 4 else None
                        if source:
                            self.pages["/" + entry[2].lstrip("/")] = (source["repository"], source["path"])
                    break
        return self.pages.get("/" + (page_path or "").lstrip("/"), (None, None))

    def describe(self, note):
        """The note with its origin, checkout, absolute file path, and page address."""
        review = is_review(note)
        repo, file_path = note.get("repo"), note.get("file_path")
        if not review and not (repo and file_path):
            repo, file_path = self.page_source(note.get("page_path"))
        checkout = self.checkout(repo)
        absolute = str(checkout / file_path) if checkout and file_path else None
        described = {**note, "source": "review" if review else "docs", "repo": repo, "file_path": file_path,
                     "checkout": str(checkout) if checkout else None, "absolute_path": absolute}
        if not review:
            described["page_url"] = (f"http://docs.{self.workspace.domain}:{self.workspace.port}"
                                     f"/{(note.get('page_path') or '').lstrip('/')}")
        return described


def linked_worktrees(path):
    """Map each worktree slug of a repository to its directory.

    The slug rule is the same as ``_linked_worktrees`` in the review API, which
    writes ``repo@slug`` into a review comment.
    """
    try:
        output = subprocess.run(["git", "-C", str(path), "worktree", "list", "--porcelain"],
                                capture_output=True, text=True, check=True, timeout=30).stdout
    except (subprocess.SubprocessError, OSError):
        return {}
    entries, current = [], {}
    for line in output.splitlines() + [""]:
        if not line:
            if current:
                entries.append(current)
            current = {}
            continue
        key, _, value = line.partition(" ")
        current[key] = value or True
    found = {}
    for entry in entries[1:]:
        if entry.get("bare"):
            continue
        worktree = Path(entry["worktree"])
        base = worktree.name if worktree.name != path.name else worktree.parent.name
        slug, suffix = base, 2
        while slug in found:
            slug, suffix = f"{base}-{suffix}", suffix + 1
        found[slug] = worktree
    return found


def is_review(note):
    return bool(note.get("repo")) and (note.get("page_path") or "").startswith("review:")


def select(notes, args):
    """Apply the filters of ``list`` and ``clear`` to described notes."""
    chosen = []
    for note in notes:
        repo = note.get("repo") or ""
        if args.repo and repo != args.repo and not ("@" not in args.repo and repo.startswith(args.repo + "@")):
            continue
        if args.no_worktrees and "@" in repo:
            continue
        if args.source and note["source"] != args.source:
            continue
        if args.kind and note.get("kind") != args.kind:
            continue
        if args.page:
            if note["source"] != "docs":
                continue
            if not ("/" + (note.get("page_path") or "").lstrip("/")).startswith("/" + args.page.lstrip("/")):
                continue
        chosen.append(note)
    return sorted(chosen, key=lambda note: (note.get("repo") or "", note["source"], note.get("file_path") or note.get("page_path") or "",
                                            note.get("line_number") or 0, note["id"]))


def location(note):
    """The shortest useful place name: ``file:line`` in a checkout, or a page."""
    place = note.get("absolute_path") or note.get("file_path") or note.get("page_path") or ""
    return f"{place}:{note['line_number']}" if note.get("line_number") and note.get("file_path") else place


def markdown(workspace, notes):
    """A prompt-ready document: one section for each repository or worktree."""
    open_count = sum(1 for note in notes if not note.get("resolved_at"))
    lines = [f"# Comments from Bunko: {workspace.name}", "",
             f"{len(notes)} comments, {open_count} open. Each comment gives the file on disk that it refers to.", ""]
    group = object()
    for note in notes:
        key = note.get("repo") or "(no repository)"
        if key != group:
            group = key
            lines += [f"## {key}", ""]
            if note.get("checkout"):
                lines += [f"Checkout: `{note['checkout']}`", ""]
        state = " (resolved)" if note.get("resolved_at") else ""
        lines += [f"### #{note['id']} {note.get('kind', 'NOTE')}{state}: `{location(note)}`", ""]
        if note["source"] == "review":
            lines.append(f"- Origin: code review, revision `{note.get('revision') or 'unknown'}`")
        else:
            lines.append(f"- Origin: documentation page [{note.get('page_title') or note.get('page_path')}]({note['page_url']})")
            if note.get("heading"):
                lines.append(f"- Section: {note['heading']}")
        if note.get("absolute_path"):
            lines.append(f"- File: `{location(note)}`")
        elif note.get("file_path"):
            lines.append(f"- File: `{note['file_path']}` (checkout not found on disk)")
        if note.get("block_preview"):
            lines.append(f"- Refers to: {json.dumps(note['block_preview'], ensure_ascii=False)}")
        lines += ["", note.get("body", "").strip(), ""]
    return "\n".join(lines).rstrip() + "\n"


def text(notes):
    return "".join(f"#{note['id']}\t{note.get('kind', '')}\t{'resolved' if note.get('resolved_at') else 'open'}\t"
                   f"{note.get('repo') or '-'}\t{location(note)}\t{' '.join(note.get('body', '').split())}\n" for note in notes)


def main(workspace, args, output=print):
    client = Client(workspace)
    if args.notes_command == "resolve":
        known = {note["id"] for note in client.notes()}
        missing = [note_id for note_id in args.ids if note_id not in known]
        if missing:
            raise ValueError("Unknown comment ID: " + ", ".join(map(str, missing)))
        for note_id in args.ids:
            client.request("PATCH", f"/notes/{note_id}", {"resolved": not args.reopen})
        output(f"{'Reopened' if args.reopen else 'Resolved'} {len(args.ids)} comments.")
        return 0
    locator = Locator(workspace)
    notes = [locator.describe(note) for note in client.notes()]
    if args.notes_command == "list":
        notes = select([note for note in notes if args.all or not note.get("resolved_at")], args)
        if args.format == "json":
            output(json.dumps({"workspace": workspace.name, "notes": notes}, indent=2, ensure_ascii=False))
        else:
            output((markdown(workspace, notes) if args.format == "markdown" else text(notes)).rstrip("\n"))
        return 0
    notes = select([note for note in notes if not (args.open_only and note.get("resolved_at"))], args)
    if not args.yes:
        raise ValueError(f"{len(notes)} comments match. Add --yes to delete them. A deleted comment cannot be restored.")
    for note in notes:
        client.request("DELETE", f"/notes/{note['id']}")
    output(f"Deleted {len(notes)} comments.")
    return 0
