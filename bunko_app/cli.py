"""Bunko lifecycle commands; dependencies run in a private workspace runtime."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from .config import Workspace

PACKAGE = Path(__file__).resolve().parent.parent
PAYLOAD = ("apphost.mts", "aspire.config.json", "tsconfig.apphost.json", "package.json",
           "package-lock.json", "tools", "bunko_app", "VERSION")
IGNORE = shutil.ignore_patterns("node_modules", ".venv", "__pycache__", "*.pyc", ".aspire", "notes.db", "*.duckdb", "*.duckdb.wal")


def run(args, cwd, env=None):
    subprocess.run([str(arg) for arg in args], cwd=cwd, env=env, check=True)


def version():
    return (PACKAGE / "VERSION").read_text().strip()


def runtime_path(workspace):
    manifest = PACKAGE / "bundle.json"
    if manifest.exists():
        identity = hashlib.sha256(manifest.read_bytes()).hexdigest()[:16]
    else:
        raise ValueError("Build a release bundle first: python3 scripts/package.py. Run bunko from the extracted bundle.")
    return workspace.state / "runtimes" / f"{version()}-{identity}"


def environment(workspace, runtime, dev_tools=False):
    return {**os.environ, "BUNKO_CONFIG": str(workspace.config), "BUNKO_ROOT": str(workspace.root),
            "BUNKO_STATE": str(workspace.state), "BUNKO_DATABASE": str(workspace.database),
            "BUNKO_DOMAIN": workspace.domain, "BUNKO_PORT": str(workspace.port),
            "BUNKO_DEV_TOOLS": "1" if dev_tools else "0", "BUNKO_NOTES_UI_PORT": str(workspace.notes_ui_port),
            "PYTHONPATH": str(runtime)}


@contextmanager
def workspace_lock(workspace):
    import fcntl
    workspace.state.mkdir(parents=True, exist_ok=True)
    with (workspace.state / "lifecycle.lock").open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("Another Bunko lifecycle command is running for this workspace") from None
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def ensure_runtime(workspace, dev_tools=False):
    runtime = runtime_path(workspace)
    ready = runtime / ".ready"
    if not ready.exists():
        if runtime.exists():
            shutil.rmtree(runtime)
        runtime.mkdir(parents=True)
        for name in PAYLOAD:
            source = PACKAGE / name
            if source.is_dir():
                shutil.copytree(source, runtime / name, ignore=IGNORE)
            else:
                shutil.copy2(source, runtime / name)
        run(["npm", "ci", "--ignore-scripts"], runtime)
        # Aspire's npm wrapper requires its explicitly reviewed platform install step.
        run(["npm", "rebuild", "@microsoft/aspire-cli"], runtime)
        run(["uv", "sync", "--project", "tools", "--frozen"], runtime)
        run([runtime / "node_modules/.bin/aspire", "restore", "--non-interactive"], runtime)
        ready.write_text(version() + "\n")
    if dev_tools and not (runtime / ".dev-ready").exists():
        run(["npm", "ci"], runtime / "tools/review/web")
        (runtime / ".dev-ready").write_text(version() + "\n")
    return runtime


def active_runtime(workspace):
    marker = workspace.state / "active.json"
    if not marker.exists():
        return None
    runtime = Path(json.loads(marker.read_text())["runtime"]).resolve()
    if runtime.parent != (workspace.state / "runtimes").resolve() or not (runtime / ".ready").exists():
        raise ValueError("Invalid active runtime record")
    return runtime


def backup_notes(workspace):
    if workspace.database.exists():
        backup = workspace.state / "backups" / f"notes-before-{version()}.duckdb"
        if not backup.exists():
            # Connect read-only to reject a live writer before copying its database.
            # The actual schema is unchanged in 0.1.0; backups support explicit rollback.
            runtime = runtime_path(workspace)
            script = "import duckdb,sys; c=duckdb.connect(sys.argv[1],read_only=True); c.close()"
            run([runtime / "tools/.venv/bin/python", "-c", script, workspace.database], workspace.root)
            if Path(str(workspace.database) + ".wal").exists():
                raise ValueError("Stop the existing notes service cleanly before migration; a DuckDB WAL remains")
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(workspace.database, backup)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="bunko", description="Local documentation and repository review")
    parser.add_argument("--version", action="version", version=f"Bunko {version()}")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("setup", "start", "stop", "doctor", "build", "status"):
        command = commands.add_parser(name)
        command.add_argument("--config", default="workspace.json", help="Workspace configuration; paths are relative to this file")
        if name in {"start", "setup"}:
            command.add_argument("--dev-tools", action="store_true", help="Enable the optional Tidewave/Vite development integration")
    args = parser.parse_args(argv)
    try:
        workspace = Workspace.load(args.config)
        if args.command == "doctor":
            missing = [tool for tool in ("git", "node", "npm", "uv") if not shutil.which(tool)]
            print(json.dumps({"version": version(), "config": str(workspace.config), "state": str(workspace.state),
                              "database": str(workspace.database), "domain": workspace.domain, "port": workspace.port,
                              "docs_url": f"http://docs.{workspace.domain}:{workspace.port}/",
                              "review_url": f"http://review.{workspace.domain}:{workspace.port}/",
                              "missing_tools": missing, "platform": sys.platform}, indent=2))
            if sys.platform not in {"darwin", "linux"}:
                print("Bunko 0.1 supports macOS and Linux lifecycle commands; Windows is not supported.", file=sys.stderr)
                return 1
            return bool(missing)
        with workspace_lock(workspace):
            if args.command in {"stop", "status"}:
                runtime = active_runtime(workspace)
                if runtime is None:
                    print("No Bunko runtime is recorded for this workspace.")
                    return 0 if args.command == "stop" else 1
                command = "stop" if args.command == "stop" else "describe"
                run([runtime / "node_modules/.bin/aspire", command, "--apphost", runtime / "apphost.mts", "--non-interactive"], runtime)
                if args.command == "stop":
                    (workspace.state / "active.json").unlink()
                return 0
            if args.command == "start" and active_runtime(workspace):
                raise ValueError("A Bunko runtime is already recorded. Run bunko status, then bunko stop before starting or upgrading.")
            dev_tools = getattr(args, "dev_tools", False)
            runtime = ensure_runtime(workspace, dev_tools)
            env = environment(workspace, runtime, dev_tools)
            if args.command == "setup":
                print(f"Prepared Bunko {version()} for {workspace.name}")
            elif args.command == "build":
                run([runtime / "tools/.venv/bin/python", "tools/docs/serve.py", "--build"], runtime, env)
                print(f"Built documentation: {workspace.state / 'docs/site'}")
            else:
                backup_notes(workspace)
                # Record the owner before spawning so a failed readiness check is recoverable with stop.
                (workspace.state / "active.json").write_text(json.dumps({"runtime": str(runtime), "version": version()}))
                run([runtime / "node_modules/.bin/aspire", "start", "--isolated", "--non-interactive"], runtime, env)
                run([runtime / "node_modules/.bin/aspire", "wait", "gateway", "--timeout", "60", "--non-interactive"], runtime, env)
                print(f"Docs: http://docs.{workspace.domain}:{workspace.port}/")
                print(f"Review: http://review.{workspace.domain}:{workspace.port}/")
        return 0
    except (OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError) as error:
        print(f"bunko: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
