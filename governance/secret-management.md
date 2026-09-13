# Secret management and leak prevention

Policy version: **1.0.0**

This policy covers credentials, tokens, private keys, signing material, connection strings, recovery codes, sensitive configuration, and any value that grants access. It complements the engineering and supply-chain contracts. A scanner reduces accidental exposure; it does not make a repository or credential safe.

## Required control layers

1. **Do not store secrets in Git.** Use an approved secret manager, operating-system credential store, or GitHub environment/repository secret. Commit only variable names and obviously non-secret placeholders.
2. **Reduce credential value.** Prefer short-lived, narrowly scoped credentials, workload identity/OIDC, separate CI and deployment identities, rotation, and auditable access over shared long-lived tokens.
3. **Prevent at push.** Enable GitHub secret scanning and push protection wherever the repository and plan support them. Configure delegated bypass review rather than unrestricted self-bypass when available.
4. **Prevent before commit.** The installed local hook runs `mise run security:secrets:staged`. Hooks are feedback, not a security boundary, and may not be the only enforcement.
5. **Detect in CI.** Every PR and protected-branch run scans complete reachable Git history with `mise run security:secrets`. The checkout includes full history, uses read-only permissions, and avoids persisted Git credentials.
6. **Prove the scanner works.** `python scripts/nakama_governance.py secrets` first feeds a synthetic repository-owned canary rule to the scanner. A scanner that exits successfully without detecting the canary fails the check.
7. **Protect output.** Scanner output must redact findings completely. Do not upload unredacted SARIF, JSON, logs, patches, or artifacts. Do not paste a suspected value into a PR, issue, chat, or ticket.
8. **Scan beyond Git deliberately.** Build output, caches, dependency trees, runner workspaces, cloud stores, chat, and ticket systems need separate controls. Do not scan credential-bearing systems with a tool that performs outbound validation unless the incident owner explicitly approves that behavior.

## Standard scanner and security assessment

NakamaDevs uses the **Gitleaks CLI 8.30.0**, installed as an exact mise tool and integrity-locked per platform. Repositories invoke the CLI directly rather than a third-party Action, container tag, Homebrew formula, `go install ...@latest`, or moving release reference.

The selection is deliberate:

- Gitleaks is an established, cross-platform, MIT-licensed Go CLI that scans locally without requiring repository, organization, or cloud credentials. Its default rules can be extended with repository-specific patterns.
- The scanner is deterministic enough for hooks and CI, supports complete-history and staged scans, and can fully redact findings.
- Gitleaks is pattern/entropy based. It can miss unknown formats and cannot prove whether a credential is live. Passing it is not evidence that no secret exists.
- Upstream describes Gitleaks as feature-complete with future releases focused on security patches. That is acceptable for a narrow control, but ownership and release practice must be reassessed before every upgrade.
- Release 8.30.1 was produced from a commit outside normal branch history after an acknowledged release mistake. Even though a reported detection failure was explained as an allowlisted placeholder, mutable or orphaned release provenance is an avoidable supply-chain concern. The baseline retains signed release 8.30.0 until a later release has ordinary immutable provenance and passes the canary.
- Gitleaks Action v2 has different licensing, bundles an additional JavaScript dependency surface, and has a published v2 deprecation path. The baseline does not use it; CI installs only the locked CLI binary.
- TruffleHog is valuable for incident response because it classifies and can verify whether credentials are live. Live verification can make outbound requests using a discovered value, so it is not the default repository gate. Use it only in a scoped incident environment with approved network behavior and redacted output.
- No maintained project or authoritative documentation for a scanner named “OhMyLeaks” could be established during this assessment. An unidentifiable tool is not eligible for organization-wide execution.

## Configuration and exceptions

Each repository keeps `.gitleaks.toml`, extends the built-in rules, and owns custom patterns for organization-specific credential formats. Monorepos keep one root configuration and scan the entire repository; component-specific allowlists still identify an exact rule and path.

Prefer changing a fixture to an unmistakably fake, low-value placeholder. When that is not possible, an allowlist must:

- name the reason and data classification;
- target the narrowest rule, path, and line pattern practical;
- never suppress an entire broad rule globally;
- receive code-owner review as a security-sensitive change;
- include an owner, expiry, or removal condition in the PR when temporary.

Do not use `gitleaks:allow` casually. `.gitleaksignore` fingerprints are reserved for already-reviewed immutable historical false positives when a precise configuration exception cannot express the case. Skipping the hook does not authorize merging; CI remains mandatory.

## Leak response

Treat a committed or transmitted secret as compromised even if it was deleted quickly or the repository is private.

1. Stop propagation without copying the value into another system.
2. Revoke or disable the credential first, then issue a replacement with the smallest required scope.
3. Review provider, GitHub, runner, and application audit logs for use from the earliest possible exposure time.
4. Notify the credential owner and incident lead through the approved private channel. Record only a fingerprint, provider, affected identity, dates, and remediation evidence.
5. Remove the value from the current tree. Rewrite Git history only after coordination because rewriting does not revoke cached, forked, cloned, logged, or indexed copies.
6. Rotate related credentials when trust boundaries or derivation are uncertain, then add a regression rule or test without embedding the real value.
7. Close the incident only after revocation is verified, downstream systems are healthy, and follow-up ownership is recorded.

## Review checklist

- Are new credentials short-lived, least-privilege, independently rotatable, and absent from build arguments and logs?
- Do workflows expose secrets only to trusted events and steps, with `persist-credentials: false` unless a write is explicitly required?
- Does every new secret format have provider-supported push protection or a custom detection rule?
- Did the staged scan, history scan, and synthetic canary pass with fully redacted output?
- Are exceptions narrow, explained, owned, and reviewable rather than a broad baseline?
- If a leak occurred, was the credential revoked before history cleanup?

## Primary references

- [GitHub push protection](https://docs.github.com/en/code-security/concepts/secret-security/push-protection)
- [GitHub secret-scanning scope and limitations](https://docs.github.com/en/code-security/reference/secret-security/secret-scanning-scope)
- [GitHub repository security and analysis settings](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/enabling-features-for-your-repository/managing-security-and-analysis-settings-for-your-repository)
- [Gitleaks source, configuration, redaction, and scan modes](https://github.com/gitleaks/gitleaks)
- [Gitleaks releases and checksums](https://github.com/gitleaks/gitleaks/releases)
- [TruffleHog discovery and credential verification](https://trufflesecurity.com/docs)
