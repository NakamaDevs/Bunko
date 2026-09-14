"""Local notes service for the documentation site.

Readers add a note against a block of a page while reading. Notes are stored in
DuckDB and listed on a generated index page, so a pass over the docs produces a
worklist instead of scattered edits.

Notes are held in DuckDB. The service binds to the loopback interface and is
not an authenticated service: do not expose it.

DuckDB takes an exclusive lock on its file for the life of a connection, so
this process is the only one that opens it. Anything else that needs the notes
reads them over HTTP, which is why the generated notes page asks this service
rather than the file.

A note is anchored to a block by a hash of the block's heading trail and its
normalized text, not by a line number, so edits elsewhere on the page do not
move it. When the anchored text itself changes the note becomes "orphaned": it
keeps its page and its recorded preview so it can still be found and re-placed.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import threading

import duckdb
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HOST = "127.0.0.1"
# Aspire assigns a port; standalone runs keep a predictable one.
PORT = int(os.environ.get("PORT") or 8900)

# DuckDB's own browser UI, served by this process because it is the process
# holding the database lock. Nothing else can open the file while it runs.
# Set NOTES_UI_PORT to 0 to run without it.
UI_PORT = int(os.environ.get("NOTES_UI_PORT", "0"))
DATABASE = Path(os.environ.get("BUNKO_DATABASE", Path(os.environ.get("BUNKO_ROOT", Path.cwd())) / "_build/state/notes.duckdb"))
# The store this replaced. Its rows are copied across once, then it is left
# alone rather than deleted, so nothing is lost if the move has to be undone.
LEGACY_DATABASE = Path(os.environ.get("BUNKO_ROOT", Path.cwd())) / "tools/docs/annotations/notes.db"
KINDS = ("TODO", "QUESTION", "FIXME", "NOTE")

SCHEMA = """
CREATE TABLE IF NOT EXISTS note (
  -- Allocated by the writer rather than a sequence: DuckDB 1.4 cannot restart a
  -- sequence, nor replace one a column default depends on, so importing rows
  -- with existing ids would leave the sequence behind them.
  id            BIGINT PRIMARY KEY,
  page_path     TEXT NOT NULL,
  page_title    TEXT NOT NULL DEFAULT '',
  block_anchor  TEXT NOT NULL,
  block_preview TEXT NOT NULL DEFAULT '',
  heading       TEXT NOT NULL DEFAULT '',
  kind          TEXT NOT NULL DEFAULT 'TODO',
  body          TEXT NOT NULL,
  -- Set when the note is against one line of a rendered code block.
  line_number   INTEGER,
  -- Set when the note is against source in a repository rather than a page.
  repo          TEXT,
  revision      TEXT,
  file_path     TEXT,
  created_at    TEXT NOT NULL,
  resolved_at   TEXT
);
"""

COLUMNS = (
    "id", "page_path", "page_title", "block_anchor", "block_preview", "heading",
    "kind", "body", "line_number", "repo", "revision", "file_path",
    "created_at", "resolved_at",
)

_connection = None
_lock = threading.Lock()


def connect():
    """The one connection to the store; DuckDB allows no second writer."""
    global _connection
    if _connection is None:
        DATABASE.parent.mkdir(parents=True, exist_ok=True)
        _connection = duckdb.connect(str(DATABASE))
        for statement in filter(None, (s.strip() for s in SCHEMA.split(";"))):
            _connection.execute(statement)
        _migrate(_connection)
        _import_legacy(_connection)
    return _connection


def _migrate(connection) -> None:
    """Add columns introduced after a database was first created."""
    existing = {row[1] for row in connection.execute("PRAGMA table_info('note')").fetchall()}
    for column, kind in (
        ("line_number", "INTEGER"), ("repo", "TEXT"),
        ("revision", "TEXT"), ("file_path", "TEXT"),
    ):
        if column not in existing:
            connection.execute(f"ALTER TABLE note ADD COLUMN {column} {kind}")


def _import_legacy(connection) -> None:
    """Copy notes from the SQLite store this replaced, once."""
    if not LEGACY_DATABASE.exists():
        return
    if connection.execute("SELECT count(*) FROM note").fetchone()[0]:
        return

    legacy = sqlite3.connect(LEGACY_DATABASE)
    legacy.row_factory = sqlite3.Row
    try:
        rows = [dict(row) for row in legacy.execute("SELECT * FROM note")]
    except sqlite3.DatabaseError:
        return
    finally:
        legacy.close()

    for row in rows:
        values = [row.get(name) for name in COLUMNS]
        connection.execute(
            f"INSERT INTO note ({', '.join(COLUMNS)}) VALUES ({', '.join('?' * len(COLUMNS))})",
            values,
        )
    if rows:
        print(f"imported {len(rows)} notes from {LEGACY_DATABASE.name}")


def start_ui(connection) -> str | None:
    """Serve DuckDB's UI from this process, the only one that may open the file."""
    if not UI_PORT:
        return None
    try:
        connection.execute("INSTALL ui")
        connection.execute("LOAD ui")
        connection.execute(f"SET ui_local_port = {UI_PORT}")
        connection.execute("CALL start_ui_server()")
        return connection.execute("SELECT * FROM get_ui_url()").fetchone()[0]
    except duckdb.Error as error:
        # The UI is a convenience; the service must still serve notes without it.
        print(f"DuckDB UI unavailable: {error}")
        return None


def _rows(result) -> list[dict]:
    names = [column[0] for column in result.description]
    return [dict(zip(names, record)) for record in result.fetchall()]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def list_notes(
    page_path: str | None = None,
    open_only: bool = True,
    repo: str | None = None,
) -> list[dict]:
    query = "SELECT * FROM note"
    clauses, values = [], []
    if page_path is not None:
        clauses.append("page_path = ?")
        values.append(page_path)
    if repo is not None:
        clauses.append("repo = ?")
        values.append(repo)
    if open_only:
        clauses.append("resolved_at IS NULL")
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY created_at DESC"
    with _lock:
        return _rows(connect().execute(query, values))


def add_note(payload: dict) -> dict:
    body = (payload.get("body") or "").strip()
    if not body:
        raise ValueError("A note needs a body.")
    kind = payload.get("kind") or "TODO"
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {', '.join(KINDS)}.")

    fields = [name for name in COLUMNS if name != "resolved_at"]
    record = {
        "page_path": payload.get("page_path") or "",
        "page_title": payload.get("page_title") or "",
        "block_anchor": payload.get("block_anchor") or "",
        "block_preview": (payload.get("block_preview") or "")[:280],
        "heading": payload.get("heading") or "",
        "kind": kind,
        "body": body,
        "line_number": payload.get("line_number"),
        "repo": payload.get("repo"),
        "revision": payload.get("revision"),
        "file_path": payload.get("file_path"),
        "created_at": _now(),
    }
    with _lock:
        connection = connect()
        record["id"] = connection.execute(
            "SELECT coalesce(max(id), 0) + 1 FROM note"
        ).fetchone()[0]
        result = connection.execute(
            f"INSERT INTO note ({', '.join(fields)})"
            f" VALUES ({', '.join('?' * len(fields))}) RETURNING *",
            [record[name] for name in fields],
        )
        return _rows(result)[0]


def resolve_note(note_id: int, resolved: bool) -> None:
    with _lock:
        connect().execute(
            "UPDATE note SET resolved_at = ? WHERE id = ?",
            [_now() if resolved else None, note_id],
        )


def delete_note(note_id: int) -> None:
    with _lock:
        connect().execute("DELETE FROM note WHERE id = ?", [note_id])


class Handler(BaseHTTPRequestHandler):
    server_version = "BunkoNotes/1.0"

    def log_message(self, *_args) -> None:  # noqa: D102 - quiet by default
        pass

    def _send(self, status: int, payload: object) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        # The docs site is served from a different local port than this service.
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, DELETE, OPTIONS")
        self.end_headers()
        self.wfile.write(body)

    def _payload(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        return json.loads(self.rfile.read(length) or b"{}")

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._send(204, {})

    def do_GET(self) -> None:  # noqa: N802
        url = urlparse(self.path)
        if url.path != "/notes":
            self._send(404, {"error": "not found"})
            return
        query = parse_qs(url.query)
        page = query.get("page", [None])[0]
        repo = query.get("repo", [None])[0]
        open_only = query.get("all", ["0"])[0] != "1"
        self._send(200, {"notes": list_notes(page, open_only, repo)})

    def do_POST(self) -> None:  # noqa: N802
        if self.headers.get("Origin"):
            self._send(403, {"error": "Use the workspace gateway."})
            return
        if urlparse(self.path).path != "/notes":
            self._send(404, {"error": "not found"})
            return
        try:
            self._send(201, {"note": add_note(self._payload())})
        except (ValueError, json.JSONDecodeError) as error:
            self._send(400, {"error": str(error)})

    def do_PATCH(self) -> None:  # noqa: N802
        if self.headers.get("Origin"):
            self._send(403, {"error": "Use the workspace gateway."})
            return
        parts = urlparse(self.path).path.strip("/").split("/")
        if len(parts) != 2 or parts[0] != "notes":
            self._send(404, {"error": "not found"})
            return
        resolve_note(int(parts[1]), bool(self._payload().get("resolved", True)))
        self._send(200, {"ok": True})

    def do_DELETE(self) -> None:  # noqa: N802
        if self.headers.get("Origin"):
            self._send(403, {"error": "Use the workspace gateway."})
            return
        parts = urlparse(self.path).path.strip("/").split("/")
        if len(parts) != 2 or parts[0] != "notes":
            self._send(404, {"error": "not found"})
            return
        delete_note(int(parts[1]))
        self._send(200, {"ok": True})


def main() -> int:
    ui_url = start_ui(connect())
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"documentation notes on http://{HOST}:{PORT}/notes  (database: {DATABASE})")
    if ui_url:
        print(f"DuckDB UI on {ui_url}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
