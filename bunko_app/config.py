"""Resolve all consumer paths from an explicit workspace configuration."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Workspace:
    config: Path
    root: Path
    state: Path
    database: Path
    domain: str
    port: int
    name: str
    data: dict
    notes_ui_port: int = 0

    @classmethod
    def load(cls, path: str | Path) -> "Workspace":
        config = Path(path).expanduser().resolve(strict=True)
        data = json.loads(config.read_text(encoding="utf-8"))
        if data.get("schema_version", 1) != 1:
            raise ValueError("Unsupported workspace schema_version")
        if not isinstance(data.get("name"), str) or not data["name"].strip():
            raise ValueError("Workspace name must be a nonempty string")
        root = config.parent
        repos = data.get("repositories")
        if not isinstance(repos, dict) or not repos:
            raise ValueError("At least one repository is required")
        for name, relative in repos.items():
            if not re.fullmatch(r"[A-Za-z0-9_-]+", name):
                raise ValueError("Repository IDs must contain letters, numbers, underscores, or hyphens")
            if not isinstance(relative, str) or not (root / relative).resolve().is_dir():
                raise ValueError(f"Repository directory does not exist: {name}")
        seen = {"assets", "stylesheets", "javascripts"}
        if not isinstance(data.get("documentation"), list) or not data["documentation"]:
            raise ValueError("At least one documentation root is required")
        for item in data["documentation"]:
            ident = item["id"]
            if not isinstance(ident, str) or not ident.isidentifier() or ident in seen:
                raise ValueError("Documentation IDs must be unique identifiers, excluding asset names")
            seen.add(ident)
            repo = (root / repos[item["repository"]]).resolve()
            folder = (repo / item["path"]).resolve(strict=True)
            folder.relative_to(repo)
            if not folder.is_dir():
                raise ValueError("Documentation roots must be directories")
        settings = data.get("runtime", {})
        identity = hashlib.sha256(str(config).encode()).hexdigest()[:10]
        state = (root / settings.get("state_dir", "_build/bunko")).resolve()
        database = (root / settings.get("notes_database", "_build/state/notes.duckdb")).resolve()
        # These must be distinct dedicated paths; never target a content root.
        if state == root or root.is_relative_to(state):
            raise ValueError("state_dir must not contain the workspace root")
        if database == state or database.is_relative_to(state) or state.is_relative_to(database):
            raise ValueError("notes_database must be separate from state_dir")
        for item in data["documentation"]:
            source = (root / repos[item["repository"]] / item["path"]).resolve()
            if source == state or source.is_relative_to(state):
                raise ValueError("state_dir must not contain a documentation root")
            if source == database or source.is_relative_to(database):
                raise ValueError("notes_database must not contain a documentation root")
            # Repository-root guides support the standard excluded _build directory.
            # Other database locations inside maintained documentation are refused.
            if database.is_relative_to(source) and "_build" not in database.relative_to(source).parts[:-1]:
                raise ValueError("notes_database must be outside published documentation")
        domain = settings.get("domain", f"bunko-{identity}.localhost")
        if not isinstance(domain, str) or not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)*\.localhost", domain):
            raise ValueError("runtime.domain must be a DNS name ending in .localhost")
        port = settings.get("port", 20000 + int(identity, 16) % 30000)
        if type(port) is not int or not 1024 <= port <= 65535:
            raise ValueError("runtime.port must be an integer from 1024 through 65535")
        ui_port = settings.get("notes_ui_port", 0)
        if type(ui_port) is not int or not (ui_port == 0 or 1024 <= ui_port <= 65535):
            raise ValueError("runtime.notes_ui_port must be 0 or an integer from 1024 through 65535")
        site = data.get("site")
        if site is not None:
            if not isinstance(site, dict) or not isinstance(site.get("config"), str):
                raise ValueError("site.config must name a MkDocs configuration file")
            if len(data["documentation"]) != 1:
                raise ValueError("site.config renders exactly one documentation root")
            inside(root, site["config"], "site.config")
        review = data.get("review", {})
        if not isinstance(review, dict) or not isinstance(review.get("title", ""), str):
            raise ValueError("review.title must be a string")
        stylesheets = review.get("stylesheets", [])
        if not isinstance(stylesheets, list):
            raise ValueError("review.stylesheets must be a list")
        for item in stylesheets:
            if not isinstance(item, str) or not item.endswith(".css"):
                raise ValueError("review.stylesheets must list CSS files")
            inside(root, item, "review.stylesheets")
        palette = data.get("palette", {})
        if not isinstance(palette, dict):
            raise ValueError("palette must be an object")
        applications = palette.get("applications", [])
        if not isinstance(applications, list) or not all(
                isinstance(entry, list) and len(entry) == 2 and all(isinstance(part, str) for part in entry)
                for entry in applications):
            raise ValueError("palette.applications must list [name, url] pairs")
        for key in ("applications_file", "linear_workspace"):
            if not isinstance(palette.get(key, ""), str):
                raise ValueError(f"palette.{key} must be a string")
        return cls(config, root, state, database, domain, port, data["name"], data, ui_port)


def inside(root: Path, relative: str, label: str) -> Path:
    """Resolve an existing consumer file that must stay inside the workspace."""
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError(f"{label} must name an existing file inside the workspace")
    return path
