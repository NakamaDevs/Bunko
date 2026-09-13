# Bunko agent guide

Bunko (文庫) is a private local documentation and repository review application.
Start with the pinned [Kaicho mirror](governance/engineering-v2.md).
Use team `NAK` and project `Bunko` in Linear. The user-required issue-only branch
format below replaces the mirror's namespaced branch format for this repository.

Create an issue before editing. Use one issue, owner, Herdr linked worktree,
`<type>/NAK-123-short-description` branch, and pull request for each change.
Keep the primary checkout on `main`. Record stack parents in the issue and PR.

Keep workspace content and writable state outside installed releases. Resolve
repository paths relative to the explicit workspace configuration. Bind services
to loopback. Keep notes in a single-writer database. Never push or change branches
from the reviewer. Preserve exact dependency locks and release checksums.

Run focused tests, then `mise run verify` before pushing. Use Conventional Commits
and the approved identity in private Git configuration. Keep incomplete PRs draft.
Review the complete diff, address review findings with evidence, and check current
CI and code-owner approval before merge. Do not replace a released artifact.
