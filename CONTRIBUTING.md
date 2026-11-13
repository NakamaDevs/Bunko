# Contribute to Bunko

Bunko is a NakamaDevs project with the [MIT License](LICENSE). This guide
tells you how to propose a change, how to verify it, and which license rules
apply.

Agents also follow [`AGENTS.md`](AGENTS.md). That file and the governance
mirror in [`.nakama/kaicho/`](.nakama/kaicho/) state the delivery policy. If
this guide and the policy disagree, the policy applies.

## Before you start

- **NakamaDevs members:** create or find a Linear issue in team `NAK`, project
  `Bunko`. Each change has one issue.
- **Other contributors:** open a GitHub issue first. Describe the problem and
  the change that you propose. Wait for a maintainer to agree before you write
  code. The maintainer gives you the Linear identifier for your branch name.
- **Security problems:** do not put the details in a public issue. Open an
  issue that asks for a private contact, with no details.

## Set up

You need Python 3.12, Git, Node.js 24, npm, uv, and
[mise](https://mise.jdx.dev/). macOS and Linux are supported. Windows is not
supported.

```sh
mise run setup
mise run hooks:install
```

`setup` installs the locked dependencies. `hooks:install` adds the Git hooks
that check each commit message and the branch name.

## Make a change

1. Create a branch from the current `main`. Use the form
   `<type>/NAK-123-short-description`. `<type>` is a Conventional Commit type,
   such as `feat`, `fix`, `docs`, `build`, or `chore`. Do not add a user name
   or a tool name.
2. Keep the change small. One branch does one thing.
3. Add or update tests for each change in behavior. Python tests are in
   `tests/` and `tools/tests/`. Reviewer tests are in `tools/review/web/tests/`.
4. Update `README.md` when a command, a setting, or a limit changes.

These design rules apply to all changes:

- Services bind to loopback only.
- Workspace content and writable state stay outside the installed release.
- Repository paths resolve from the workspace configuration.
- The notes database has one writer.
- The reviewer does not push, change branches, or rewrite history.
- A released archive does not change. A correction gets a new version.

## Verify

Run the full gate before you push:

```sh
mise run verify
```

`verify` runs the governance checks, the tests, the linter, the type checks,
the asset build, and the release packaging. Run `mise run test` for a faster
check while you work.

CI runs the same gate for a branch in this repository. CI does not run for a
pull request from a fork. A maintainer runs `mise run verify` on that change
before the merge.

## Commit

Use [Conventional Commits](https://www.conventionalcommits.org/). Write the
subject in the imperative. Put the Linear reference in the body, with no colon:

```text
fix: refuse a documentation root outside its repository

Resolve the path before the comparison, so a symbolic link cannot
point outside the checkout.

Fixes NAK-123
```

Use `Fixes NAK-123` when the commit completes the issue. Use `Refs NAK-123`
for partial work.

## Dependencies and licenses

Bunko redistributes third-party code. The build bundles the production npm
dependencies into the reviewer and into the documentation code viewer, and the
release archive contains that output. Thus each dependency change is also a
license change.

[`THIRD_PARTY_LICENSES.md`](THIRD_PARTY_LICENSES.md) lists each package and its
license in three groups:

| Group | Contents | Permitted licenses |
| --- | --- | --- |
| Release bundle | Production npm dependencies | MIT, ISC, Apache-2.0, BSD-2-Clause, BSD-3-Clause, 0BSD |
| Installed by `bunko setup` | Python packages from PyPI | The licenses above, plus MPL-2.0, PSF-2.0, BlueOak-1.0.0, AFL-2.1 |
| Build and development tools | npm development dependencies | Same as the Python packages |

When you add, remove, or update a dependency:

1. Keep the exact lock files. Commit the manifest and its lock file together.
2. Run `mise run test`. The tests read the license of each locked package.
3. Run `mise run licenses`, and read the diff of `THIRD_PARTY_LICENSES.md`.
   Make sure that each new license is correct. Commit the file.

Step 3 is optional for an automatic update, such as a Dependabot pull request.
The committed file is the list for one version, and its first lines name that
version. A change of `VERSION` must regenerate it.

The tests fail when a package has no license, when a license is not permitted
for its group, or when the file names a different version. Do not add a license
to the permitted list in `scripts/licenses.py` without a maintainer's decision.
A copyleft license, such as GPL or AGPL, is not permitted in the release bundle.

`mise run package` writes `THIRD_PARTY_NOTICES.txt` into the release archive.
That file contains the license and notice files of each bundled package. The
archive also contains `LICENSE` and a `THIRD_PARTY_LICENSES.md` that the
package step makes from the lock files. Thus the list in an archive is always
current.

Do not copy source code from a different project into this repository. If a
copy is necessary, ask a maintainer first, keep the copyright notice, and
record the source and its license in the pull request.

## License of your contribution

Your contribution uses the MIT License of this repository. Contribute only work
that you have the right to submit. Bunko has no contributor license agreement.

## Open a pull request

- Give the pull request a Conventional Commit title.
- Complete the sections of the pull request template: behavior, evidence, and
  release and rollback.
- Record the validation that you ran and its result. State what you did not
  test.
- Keep an incomplete pull request in draft.
- Answer and resolve each review thread before the merge.
