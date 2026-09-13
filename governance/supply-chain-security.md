# Supply-chain security

Policy version: **1.0.0**

This policy applies to development tools, application dependencies, GitHub Actions, generated artifacts, installers, and source fetched from external repositories. It complements the canonical engineering governance contract.

## Default quarantine

Routine dependency and tool resolution must ignore releases published less than **7 days** ago. The delay creates time for malicious, hijacked, broken, or withdrawn releases to be detected before Nakamadevs consumes them. It is a floor, not evidence that an older release is safe.

Security updates are not delayed automatically by Dependabot. A maintainer may deliberately bypass the seven-day floor for a security fix only when the PR links the advisory or incident, pins the exact version or digest, records why waiting is riskier, receives code-owner approval, and passes the full affected validation. Keep exceptions narrow and remove temporary exclusions in the same PR or a tracked follow-up.

## Required controls

1. Commit application lockfiles and install from them without re-resolution in CI and release jobs. Lockfiles must include registry integrity hashes when the ecosystem supports them.
2. Pin mise tools to exact versions in `mise.toml`, commit `mise.lock`, and pin the mise runtime used by CI. Select an update with `mise latest TOOL --minimum-release-age 7d`, write that exact version with `mise use --pin TOOL@VERSION`, then regenerate the lock. A repository that deliberately retains a fuzzy selector uses `MISE_SAFE=1 mise lock --bump --minimum-release-age 7d` in update automation.
3. Pin third-party GitHub Actions to a full 40-character commit SHA and retain the release tag in a same-line comment for Dependabot. Local actions may use relative paths.
4. Configure Dependabot version updates with `cooldown.default-days: 7` for every detected ecosystem, including `github-actions` and `gitsubmodule` where present. Dependency-update PRs receive the same CI and code-owner review as application code. Dependabot internal update jobs and Dependabot-authored PR CI run only on clean, one-job disposable `nakama-dependabot-*` runners selected from `github.event.pull_request.user.login`; unavailable disposable capacity must never fall back to a persistent runner.
5. Pin Git and submodule dependencies to immutable commits. Do not resolve branches, moving tags, `latest`, release channels, or partial tool versions in CI or release paths.
6. Verify downloaded binaries with an upstream checksum, signature, provenance statement, or attestation before execution. A versioned URL without integrity verification is insufficient.
7. Treat install-time scripts as code execution. Disable them by default where supported, maintain the smallest reviewed allowlist, and never use an unrestricted bypass in CI.
8. Use least-privilege workflow permissions, keep secrets out of dependency-update jobs, and review changes to workflows, lockfiles, registries, checksums, and allowlists as security-sensitive changes.
9. Treat security scanners as supply-chain dependencies too. Pin and integrity-lock the CLI, execute it without repository secrets or unnecessary network access, verify release provenance, and exercise a positive detection canary before trusting a clean result. Follow the companion [secret-management policy](secret-management.md).

## Ecosystem implementation

| Ecosystem | Seven-day resolution gate | Reproducible install |
| --- | --- | --- |
| npm | project `.npmrc`: `min-release-age=7`; allow only reviewed lifecycle scripts | `npm ci`, committed `package-lock.json`, exact direct dependencies where practical |
| pnpm | `minimumReleaseAge: 10080` minutes | `pnpm install --frozen-lockfile` |
| Yarn | `.yarnrc.yml`: `npmMinimalAgeGate: "1w"` | `yarn install --immutable`; use hardened mode for one CI verification job |
| Bun | `bunfig.toml`: `minimumReleaseAge = 604800` seconds | `bun install --frozen-lockfile` |
| Hex/Mix | `hex: [cooldown: "7d"]` in `mix.exs` | committed `mix.lock`; `mix deps.get --check-locked`; pin Hex and checksum Rebar bootstrap |
| Dart/Pub | Dependabot `cooldown.default-days: 7` because Pub has no native release-age resolver gate | committed `pubspec.lock`; `dart pub get --enforce-lockfile`; subsequent Flutter commands use `--no-pub` in CI |
| SwiftPM | Dependabot `cooldown.default-days: 7` because SwiftPM has no native release-age resolver gate | committed `Package.resolved` for leaf products; `swift package resolve --force-resolved-versions` or `--disable-automatic-resolution` |
| mise | `mise latest TOOL --minimum-release-age 7d` before writing an exact pin; fuzzy automation uses the same flag on `mise lock --bump` | exact config versions plus committed `mise.lock`; CI installs in locked mode |

## Review checklist

- Explain every new registry, package, action, submodule, installer, lifecycle script, and binary download.
- Review maintainer and ownership changes, release history, advisories, transitive graph change, requested permissions, and install/build scripts.
- Confirm the lockfile change matches the manifest change and contains no unexpected source, checksum, or transitive replacement.
- Prefer a small dependency with a narrow permission surface over a broad convenience package. Remove unused dependencies promptly.
- Run vulnerability, retirement, and dependency-review checks available to the ecosystem, but do not treat a clean scanner result as proof of trust.

## Primary references

- [npm install configuration](https://docs.npmjs.com/cli/install/) (`min-release-age`, `before`, script allowlists, and lockfile behavior)
- [pnpm settings](https://pnpm.io/settings#minimumreleaseage)
- [Yarn security](https://yarnpkg.com/features/security) and [`npmMinimalAgeGate`](https://yarnpkg.com/configuration/yarnrc/#npmMinimalAgeGate)
- [Bun minimum release age](https://bun.sh/docs/pm/cli/install#minimum-release-age)
- [mise lockfiles](https://mise.jdx.dev/dev-tools/mise-lock.html), [`mise lock`](https://mise.jdx.dev/cli/lock.html), and [`mise upgrade`](https://mise.jdx.dev/cli/upgrade.html)
- [Hex dependency cooldown](https://hex.pm/docs/dependency-policies) and [`mix deps.get --check-locked`](https://hexdocs.pm/mix/Mix.Tasks.Deps.Get.html)
- [`dart pub get --enforce-lockfile`](https://dart.dev/tools/pub/cmd/pub-get#enforce-lockfile)
- [SwiftPM resolved versions](https://docs.swift.org/swiftpm/documentation/packagemanagerdocs/resolvingpackageversions/)
- [Dependabot cooldown](https://docs.github.com/en/code-security/reference/supply-chain-security/dependabot-options-reference#cooldown)
- [GitHub Actions secure use](https://docs.github.com/en/actions/reference/security/secure-use)
