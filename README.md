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

Keep the notes database outside the runtime directory and published documentation.
The standard `_build/state/notes.duckdb` location is excluded from repository-root guides.

Repository paths resolve relative to this configuration. Documentation paths
resolve inside the selected repository. Omit `runtime` for isolated defaults
based on the configuration's absolute path. Keep `_build/` ignored by Git.
The reviewer lists only configured Git checkouts. Editing and committing are
explicit UI actions; it does not push, switch branches, or rewrite history.
It also lists the linked worktrees of those checkouts. Open one to review it
like a repository. The **Worktrees** view marks each as missing, merged,
squash-merged, remote deleted, uncommitted, or active. It compares against
`origin/HEAD`, `main`, `master`, `dev`, and `develop` as of the last fetch, and
offers cleanup commands to copy. The reviewer never runs them.
Set `runtime.notes_ui_port` to serve DuckDB's UI for the notes database from
the notes process; the default `0` leaves it off.

## Customize the site and reviewer

Bunko ships a neutral look. A consumer keeps its own navigation, plugins, and
brand through optional `workspace.json` settings:

```json
{
  "site": {"config": "mkdocs.yml", "environment": ["DOCS_SOURCE_MODE"]},
  "review": {"title": "Team Review", "stylesheets": ["theme/review.css"]},
  "palette": {
    "applications": [["storefront", "https://storefront.localhost/"]],
    "applications_file": "_build/state/applications.json",
    "linear_workspace": "my-team"
  }
}
```

`site.config` renders the consumer's own MkDocs configuration in place. It
requires exactly one documentation root, which must be its `docs_dir`.
Navigation, `theme` (logo, palette, fonts, features, `custom_dir`), plugins,
hooks, Markdown extensions, `extra_css`, `extra_javascript`, and `extra` apply
unchanged, so page URLs and note anchors match the consumer's normal build.
Zensical executes the `search` and `macros` plugins; it accepts but does not run
hooks. `site.environment` names variables, such as macro settings, that
`bunko start` forwards from its own environment to the renderer; static builds
inherit the environment directly. Zensical requires `docs_dir` inside the
configuration's directory, so Bunko writes `.bunko-site.yml` and
`.bunko-site.build.yml` beside it. Ignore both in Git.

Bunko adds its palette, notes, code viewer, and diagram viewer through a
generated theme overlay. It loads its component stylesheets before the
consumer's `extra_css`, so consumer tokens and rules win. The components use the
`--bd-*` design tokens; list `stylesheets/sdlc.css` for Bunko's default skin or
define those tokens in a brand stylesheet. A consumer `custom_dir` is copied over
the overlay. A replacement `main.html` should include `partials/bunko-head.html`
in its `extrahead` block. Startup refuses documentation files that would hide a
Bunko asset, such as an old `javascripts/palette.js` copy.

Place `<div data-bunko-notes></div>` on any page to list every open note live,
grouped by page or repository file.

`review.stylesheets` link after the reviewer's built CSS in both the static and
`--dev-tools` modes. Override its tokens (`--paper`, `--surface`, `--ink`,
`--accent-ink`, and the rest in `tools/review/web/src/style.css`) under `:root`
and `.dark`. `review.title` names the page and header.

The palette lists `palette.applications` and the `[name, url]` pairs from
`palette.applications_file`, a JSON list or `{"applications": [...]}` object that
may be absent. `linear_workspace` enables issue jumps; site mode also reads
`extra.palette.linear_workspace`.

## Requirements

Requirements: Python 3.12, Git, Node.js 24, npm, and uv. The dependency-free
launcher also runs with newer Python 3 versions; uv installs the locked Python
3.12 service environment. Lifecycle commands currently target macOS and Linux;
Windows is not supported. macOS is the initial verified environment.
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
the NakamaDevs governance source. Follow the delivery routes in `AGENTS.md`.
Release publication and consumer adoption are tracked in NAK-951.

NAK-1009 authorizes Bunko CI to use the standard GitHub-hosted `ubuntu-24.04`
x64 runner for regular changes and Dependabot. This repository-scoped exception
supersedes self-hosted routing for `.github/workflows/ci.yml`, job `verify`.
The job requires public repository visibility and keeps the existing fork guard.
Private visibility skips the job before runner allocation.
The runner policy rejects larger runners, custom labels, runner groups, and
dynamic selection. Other jobs require a separate policy change.
Action pins, permissions, and other governance checks still apply.

[GitHub documents standard runners as free for public repositories](https://docs.github.com/en/actions/reference/runners/github-hosted-runners).
The [Ubuntu 24.04 image](https://github.com/actions/runner-images/blob/main/images/ubuntu/Ubuntu2404-Readme.md)
includes Python 3.12 and .NET SDKs for Aspire restore. The existing setup installs locked Node,
uv, validation tools, and application dependencies. CI does not start containers.
Bunko supports Linux lifecycle commands. Its Python packaging and web assets
require no native macOS tools. The existing tool locks include Linux x64.
The CI workload is `server-only`.

CI pins [mise 2026.9.9](https://github.com/jdx/mise/releases/tag/v2026.9.9),
released September 15, 2026, beyond the seven-day cooldown at adoption.
Its Aqua backend resolves binary paths from the selected archive's libc variant.
This supports the locked GNU archives for uv and prek. Mise 2026.7.17 searched
for musl paths after extracting those GNU archives. CI checks both commands
before dependency setup. Keep the existing lock URLs, checksums, and provenance.

### Dependency compatibility

NAK-1011 keeps these dependency limits until their compatibility checks pass:

| Dependency | Supported version | Requirement before a major update |
| --- | --- | --- |
| `vscode-jsonrpc` | 8.2.1 | Aspire must generate an import supported by JSON-RPC 9. |
| TypeScript | 6.0.3 | ESLint and Vue tooling must support the TypeScript 7 compiler API. |
| `@types/node` | 24.13.5 | Update the pinned Node 24 runtime before changing the types' major version. |

The [Aspire transport generator](https://github.com/dotnet/aspire/blob/v13.5.4/src/Aspire.Hosting.CodeGeneration.TypeScript/Resources/transport.mts)
still imports `vscode-jsonrpc/node.js`, which JSON-RPC 9 does not export.
[Microsoft documents TypeScript 7 API compatibility limits](https://devblogs.microsoft.com/typescript/announcing-typescript-7-0/).
[Vue tooling also requires compiler API compatibility](https://github.com/vuejs/language-tools/pull/6123).
Do not patch generated Aspire files to hide this mismatch.

Dependabot excludes only these incompatible version ranges. Compatible updates retain the seven-day cooldown.
Remove the matching exclusion after toolchain regeneration, lint, typechecking, and full Ubuntu CI pass.
CI consumes the committed locks; keep their versions and integrity hashes together.

## License

Bunko is available under the [MIT License](LICENSE).
