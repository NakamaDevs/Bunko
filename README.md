# Bunko 文庫

Bunko is a private, versioned local application for reading documentation,
reviewing repository changes, and keeping annotations beside your checkout.
Its command is `bunko`.

Each repository supplies a `workspace.json` and an exact release pin. Bunko
owns the docs renderer, reviewer, notes service, gateway, and Aspire AppHost.
Source files and notes remain in the consumer workspace.

## Use a release

Copy the release's `bunko.lock.json` and the reviewed bootstrap
[`consumer/bunko.py`](consumer/bunko.py) into the consumer repository, placing
that bootstrap at `scripts/bunko.py`. Use an authenticated GitHub CLI with read
access to this private repository.

```sh
python3 scripts/bunko.py doctor
python3 scripts/bunko.py setup
python3 scripts/bunko.py start
python3 scripts/bunko.py status
python3 scripts/bunko.py build
python3 scripts/bunko.py stop
```

The release also contains a directly executable `bunko` command. Pass
`--config /path/to/workspace.json` after the subcommand when working outside the
consumer directory. See [`examples/workspace.json`](examples/workspace.json).

Use `bunko start --dev-tools` to enable the extracted Tidewave integration.
The normal reviewer serves built assets. Development mode runs Vite with the
Tidewave plugin; both docs and review hosts expose `/tidewave/mcp`. The toolbar
loads from `tidewave.ai`, and authenticated Tidewave features require the user's
own account. Static documentation builds omit the toolbar.

## Configure a workspace

```json
{
  "schema_version": 1,
  "name": "My documentation",
  "repositories": {"docs": "."},
  "documentation": [
    {"id": "guide", "label": "Guide", "repository": "docs", "path": "guide"}
  ],
  "runtime": {
    "domain": "my-docs.localhost",
    "port": 8871,
    "state_dir": "_build/bunko",
    "notes_database": "_build/state/notes.duckdb"
  }
}
```

Repository paths resolve relative to this configuration. Documentation paths
resolve inside the selected repository. Omit `runtime` for isolated defaults
based on the configuration's absolute path. Keep `_build/` ignored by Git.
The reviewer lists only configured Git checkouts. Editing and committing are
explicit UI actions; it does not push, switch branches, or rewrite history.

Requirements: Python 3.12, Git, Node.js 24, npm, and uv. The dependency-free
launcher also runs with newer Python 3 versions; uv installs the locked Python
3.12 service environment. Lifecycle commands currently target macOS and Linux;
Windows is not supported in 0.1.0. macOS is the initial verified environment.
All services bind to loopback. Trust the local Aspire certificate interactively
when first requested; `aspire certs trust --non-interactive` can leave browser
trust incomplete.

## Develop and verify

```sh
mise run setup
mise run verify
```

`verify` tests configuration and archive safety, notes, Git changes, docs, and
gateway routing; type-checks the TypeScript applications; builds frontend
assets; and produces the release bundle. Run a fixture from the extracted
bundle to test the installed layout.

- [`bunko_app/`](bunko_app/): configuration and lifecycle commands.
- [`tools/`](tools/): documentation, notes, review, and gateway services.
- [`apphost.mts`](apphost.mts): isolated Aspire orchestration.
- [`consumer/`](consumer/): small pinned-release bootstrap.
- [`docs/releases.md`](docs/releases.md): packaging, publication, and rollback.
- [`docs/extraction.md`](docs/extraction.md): source provenance and migration.
- [`AGENTS.md`](AGENTS.md): repository work and review contract.

Work is tracked in the Bunko project in Linear, starting with NAK-913. Kaicho is
the NakamaDevs governance source. Implement changes in issue-linked Herdr
worktrees and review through pull requests. This initial extraction is under
review; no stable release has been published yet.
