# NakamaDevs engineering governance v2

Policy version: **2.0.0**

This contract adopts every requirement in
[`engineering-v1.md`](engineering-v1.md), except where this file replaces it.
The version 2 owner-maintenance rules replace the version 1 administrator
enforcement and bypass rules.

## Owner maintenance

The lead administrator is the GitHub user `hectorddmx`, user ID `303818`.
An active repository ruleset can give this exact `User` actor an `always`
bypass. Do not grant this bypass to a role, team, bot, deploy key, or GitHub
App. Other users remain subject to repository protection.

Do not enable classic branch-protection `enforce_admins`. That mechanism cannot
express a user-specific exception. It can also override the explicit ruleset
bypass. Repositories without active protection need no bypass rule.

The lead administrator can merge, push, or perform owner maintenance without
self-approval. Use this access only for an intentional repository operation.
Keep the GitHub ruleset audit history.

## Migration

1. Identify the exact repository and default branch.
2. Add the exact `User` actor to each active protection ruleset.
3. Set its bypass mode to `always`.
4. Disable classic `enforce_admins` when classic protection exists.
5. Read the effective rules and confirm the current user can always bypass.
6. Confirm that no team or role received the bypass.

Rollback changes the user bypass to `pull_request` and enables classic
administrator enforcement. Rollback affects owner maintenance immediately.
Record the reason before rollback.
