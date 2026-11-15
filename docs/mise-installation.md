# Manage a local Bunko installation with mise

Use mise to manage the Bunko release separately from your workspace content and
notes. This is an alternative to the checksum-pinned consumer bootstrap in
[Releases](releases.md), not a replacement for that bootstrap's integrity checks.
Choose one installation source for each workspace so its launcher and update
commands agree about the active release.

## Install a release in your home configuration

This lifecycle guide targets macOS and Linux; Bunko 0.4.0 does not support
Windows lifecycle commands.

Prerequisites: mise with its GitHub backend, authenticated GitHub access to this
private repository, Git, Python, Node.js, npm, and uv. Use the Node version required
by the selected release; Bunko 0.4.0 requires Node `^24.20.0`. A parent repository's
mise pins can override home defaults. `doctor` checks executable presence, not Node engine compatibility,
so check `node --version` in the directory
where you will run Bunko. Do not put access tokens in the configuration.

Add these entries to your existing `~/.config/mise/config.toml`. Merge them into
existing tables rather than replacing the file or duplicating table headers:

```toml
[tool_alias]
bunko = "github:NakamaDevs/Bunko"

[tools]
bunko = { version = "0.4.0", asset_pattern = "bunko-*.tar.gz", bin_path = "." }
```

Then, from your home directory:

```sh
mise install bunko
mise exec -- bunko --version
mise exec -- bunko doctor --config /absolute/path/to/workspace.json
```

mise owns the installed application. The workspace owns `workspace.json`, its
repository references, generated runtime directories, and the notes database.
Keep writable state outside the mise installation. Bunko's `setup` creates an
isolated runtime and installs the release's frozen npm/uv/Aspire dependencies.
Do not replace these locks with broad dependency updates.

For integrity-sensitive or reproducible adoption, continue to use the consumer
bootstrap and its exact `bunko.lock.json` archive digest. Downloading a release
with the mise GitHub backend does not mean the consumer bootstrap's per-file
manifest verification ran. Consult mise's lockfile/checksum configuration if
using mise as your installation policy.

## Updating a release is not activating a workspace

Preview a Bunko-only upgrade, then install it:

```sh
cd ~
mise upgrade bunko --bump --no-prune --dry-run
mise upgrade bunko --bump --no-prune
```

`--bump` updates the configured version pin. `--no-prune` retains old installed
releases for recovery. Bare `mise upgrade` can update other configured tools;
`mise self-update` updates mise itself, not Bunko.

The lower-level upgrade command does **not** restart a running Bunko workspace.
An existing launcher that points directly to an old extracted release will also
keep using that release until updated. Check both the selected CLI and active
workspace; neither a new pin nor `bunko --version` proves activation.

## Safe activation sequence

1. Record the old installed release and active runtime. Keep that application
   available until the new release is verified.
2. Check the new release's prerequisites and run `doctor`, then `setup`, with
   the explicit workspace configuration. Prepare dependencies while the old
   workspace is still running. If preparation fails, leave it running.
3. Stop the old workspace through its lifecycle command. Wait until its notes
   database is released. Never run two versions against the same notes database.
4. Back up the stopped notes/state directory, workspace configuration, and
   launcher/version settings outside the runtime directory. Preserve the old
   runtime and any custom document refresh or sanitization scripts.
5. Start the new release with the same workspace configuration.
6. Check the active version, `status`, docs, review, and existing notes. Confirm
   the actual services are healthy; installer helper resources may be stopped.
   HTTP success is useful but does not replace checking important UI behavior.
7. Update every normal launcher to use the selected installation. Keep temporary
   rollback material until acceptance; do not automatically delete user state.

For an already installed release, the lifecycle commands are:

```sh
mise exec -- bunko setup --config /absolute/path/to/workspace.json
mise exec -- bunko stop --config /absolute/path/to/workspace.json
# Back up stopped state and configuration here before continuing.
mise exec -- bunko start --config /absolute/path/to/workspace.json
mise exec -- bunko status --config /absolute/path/to/workspace.json
```

The notes path is configurable: inspect `doctor` instead of assuming a particular
home folder or `_build` layout. On startup failure, retain the backup, inspect
which services still run, and stop them before restoring or starting the old
release. Do not copy a database backup over a live database. A future release may
change the schema; retaining old application code alone is not a rollback plan.

## Optional one-command local workflow

A machine-local helper can expose the sequence as `mise run bunko:upgrade`.
**Bunko 0.4.0 does not ship that task or the helper.** The name only works where
someone has installed the helper and its mise task. Do not describe it as a
built-in command or copy a task that refers to another person's home directory.

A local implementation should:

- Serialize upgrades and scope installation to Bunko only.
- Detect an already-current active release and verify it without restarting.
- Fail before stopping if new prerequisite requirements are unsupported.
- Prepare dependencies first, then stop and back up state before activation.
- Verify the active version and endpoint health after starting.
- Keep old releases and backups on failure and print recovery instructions.
- Provide a read-only check mode and tests for sequencing and backup behavior.

When sharing a helper, distribute its source, tests, configuration contract, and
installation instructions together. Parameterize the workspace and prerequisite
versions; do not present one machine's hard-coded script as portable tooling.

## References

- [mise GitHub backend](https://mise.jdx.dev/dev-tools/backends/github.html)
- [mise upgrade](https://mise.jdx.dev/cli/upgrade.html)
- [mise lockfiles](https://mise.jdx.dev/dev-tools/mise-lock.html)
- [Bunko release packaging and consumer bootstrap](releases.md)
