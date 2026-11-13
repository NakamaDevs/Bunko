import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
from urllib.parse import urlparse, parse_qs

from bunko_app import cli, notes
from bunko_app.config import Workspace


def git(path, *args):
    subprocess.run(["git", "-C", str(path), "-c", "user.name=test", "-c", "user.email=test@example.invalid",
                    "-c", "commit.gpgsign=false", *args], check=True, capture_output=True)


class NotesTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        (self.root / "app/guide").mkdir(parents=True)
        (self.root / "app/guide/index.md").write_text("# Guide\n")
        (self.root / "app/src").mkdir()
        (self.root / "app/src/main.py").write_text("print('x')\n")
        git(self.root / "app", "init", "-q", "-b", "main")
        git(self.root / "app", "add", "-A")
        git(self.root / "app", "commit", "-q", "-m", "fixture")
        git(self.root / "app", "worktree", "add", "-q", "-b", "feat/x", str(self.root / "app-feature"))

        self.store = [
            {"id": 1, "page_path": "review:app", "repo": "app", "revision": "abc123", "file_path": "src/main.py",
             "line_number": 1, "kind": "FIXME", "body": "Rename this.", "block_preview": "", "resolved_at": None},
            {"id": 2, "page_path": "review:app@app-feature", "repo": "app@app-feature", "revision": "WORKTREE",
             "file_path": "src/main.py", "line_number": 1, "kind": "TODO", "body": "Add a test.", "resolved_at": None},
            {"id": 3, "page_path": "/guide/", "page_title": "Guide", "repo": None, "file_path": None, "heading": "Intro",
             "block_preview": "Some selected text", "kind": "QUESTION", "body": "Is this current?", "resolved_at": None},
            {"id": 4, "page_path": "/guide/", "page_title": "Guide", "repo": "app", "file_path": "guide/index.md",
             "kind": "NOTE", "body": "Old remark.", "resolved_at": "2026-11-01T00:00:00+00:00"},
        ]
        store, requests = self.store, []
        self.requests = requests

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_): pass
            def reply(self, payload):
                body = json.dumps(payload).encode()
                self.send_response(200); self.send_header("Content-Length", str(len(body))); self.end_headers()
                self.wfile.write(body)
            def do_GET(self):
                requests.append(("GET", self.path, self.headers.get("Origin")))
                everything = parse_qs(urlparse(self.path).query).get("all") == ["1"]
                self.reply({"notes": [n for n in store if everything or not n["resolved_at"]]})
            def do_PATCH(self):
                payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                note = next(n for n in store if n["id"] == int(self.path.rsplit("/", 1)[1]))
                note["resolved_at"] = "now" if payload["resolved"] else None
                self.reply({"ok": True})
            def do_DELETE(self):
                store[:] = [n for n in store if n["id"] != int(self.path.rsplit("/", 1)[1])]
                self.reply({"ok": True})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

        self.config = self.root / "workspace.json"
        self.config.write_text(json.dumps({
            "name": "Test", "repositories": {"app": "app"},
            "documentation": [{"id": "guide", "label": "Guide", "repository": "app", "path": "guide"}],
            "runtime": {"domain": "test.localhost", "port": self.server.server_address[1]}}))
        workspace = Workspace.load(self.config)
        index = workspace.state / "docs/source/assets/palette-index.json"
        index.parent.mkdir(parents=True)
        index.write_text(json.dumps({"entries": [[0, "Guide", "guide/", "Guide", "guide/index.md"], [1, "Intro", "guide/#intro", "Guide"]],
                                     "sources": {"guide/index.md": {"repository": "app", "path": "guide/index.md"}}}))

    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.main(["notes", *args, "--config", str(self.config)])
        return code, out.getvalue(), err.getvalue()

    def listed(self, *args):
        code, out, _ = self.run_cli("list", "--format", "json", *args)
        self.assertEqual(code, 0)
        return json.loads(out)["notes"]

    def test_lists_open_comments_with_the_file_on_disk(self):
        found = {note["id"]: note for note in self.listed()}
        self.assertEqual(sorted(found), [1, 2, 3])
        self.assertEqual(found[1]["absolute_path"], str(self.root / "app/src/main.py"))
        self.assertEqual(found[1]["source"], "review")
        self.assertEqual(found[2]["absolute_path"], str(self.root / "app-feature/src/main.py"))
        self.assertEqual(found[2]["checkout"], str(self.root / "app-feature"))

    def test_finds_the_source_file_of_a_documentation_page(self):
        note = next(note for note in self.listed() if note["id"] == 3)
        self.assertEqual(note["source"], "docs")
        self.assertEqual(note["absolute_path"], str(self.root / "app/guide/index.md"))
        self.assertEqual(note["page_url"], f"http://docs.test.localhost:{self.server.server_address[1]}/guide/")

    def test_filters(self):
        ids = lambda *args: sorted(note["id"] for note in self.listed(*args))
        self.assertEqual(ids("--all"), [1, 2, 3, 4])
        self.assertEqual(ids("--repo", "app"), [1, 2, 3])
        self.assertEqual(ids("--repo", "app", "--no-worktrees"), [1, 3])
        self.assertEqual(ids("--repo", "app@app-feature"), [2])
        self.assertEqual(ids("--repo", "other"), [])
        self.assertEqual(ids("--source", "review"), [1, 2])
        self.assertEqual(ids("--source", "docs", "--all"), [3, 4])
        self.assertEqual(ids("--page", "/guide/"), [3])
        self.assertEqual(ids("--page", "guide"), [3])
        self.assertEqual(ids("--page", "/other/"), [])
        self.assertEqual(ids("--kind", "fixme"), [1])

    def test_markdown_groups_by_repository_and_worktree(self):
        code, out, _ = self.run_cli("list")
        self.assertEqual(code, 0)
        self.assertIn("# Comments from Bunko: Test", out)
        self.assertIn("## app\n", out)
        self.assertIn("## app@app-feature\n", out)
        self.assertIn(f"### #1 FIXME: `{self.root / 'app/src/main.py'}:1`", out)
        self.assertIn('- Refers to: "Some selected text"', out)
        self.assertIn("Is this current?", out)
        self.assertNotIn("Old remark.", out)

    def test_text_format_has_one_line_for_each_comment(self):
        code, out, _ = self.run_cli("list", "--format", "text")
        self.assertEqual(len(out.strip().splitlines()), 3)

    def test_resolve_and_reopen(self):
        self.assertEqual(self.run_cli("resolve", "1", "2")[0], 0)
        self.assertEqual(sorted(note["id"] for note in self.listed()), [3])
        self.assertEqual(self.run_cli("resolve", "--reopen", "1")[0], 0)
        self.assertEqual(sorted(note["id"] for note in self.listed()), [1, 3])

    def test_resolve_refuses_an_unknown_id_and_changes_nothing(self):
        code, _, err = self.run_cli("resolve", "1", "99")
        self.assertEqual(code, 1)
        self.assertIn("99", err)
        self.assertIsNone(self.store[0]["resolved_at"])

    def test_clear_needs_yes(self):
        code, _, err = self.run_cli("clear")
        self.assertEqual(code, 1)
        self.assertIn("4 comments match", err)
        self.assertEqual(len(self.store), 4)

    def test_clear_deletes_only_the_selection(self):
        code, out, _ = self.run_cli("clear", "--repo", "app@app-feature", "--yes")
        self.assertEqual((code, out.strip()), (0, "Deleted 1 comments."))
        self.assertEqual([note["id"] for note in self.store], [1, 3, 4])
        self.assertEqual(self.run_cli("clear", "--open-only", "--yes")[0], 0)
        self.assertEqual([note["id"] for note in self.store], [4])
        self.assertEqual(self.run_cli("clear", "--yes")[0], 0)
        self.assertEqual(self.store, [])

    def test_sends_no_origin_header(self):
        self.listed()
        self.assertTrue(all(origin is None for _, _, origin in self.requests))

    def test_reports_a_workspace_that_is_not_running(self):
        self.server.shutdown(); self.server.server_close()
        code, _, err = self.run_cli("list")
        self.assertEqual(code, 1)
        self.assertIn("not running", err)


if __name__ == "__main__": unittest.main()
