# Releases

Use Semantic Versioning. Update `VERSION` through a reviewed release change.
Run `mise run verify`. The package step emits:

- `dist/bunko-<version>.tar.gz`: application code, built reviewer, docs assets,
  Aspire host, and exact dependency locks;
- `dist/SHA256SUMS`: archive integrity;
- `dist/bunko.lock.json`: exact consumer pin.

Run the extracted archive against two separate fixture workspaces before
publication. Check docs, review, notes, lifecycle isolation, and a static build.
Record the source commit, Node/Python/uv/Aspire versions, checks, and known
platform limits in the release notes. Publish to private GitHub Releases with
the matching `v<version>` tag. Never overwrite a published version.

Consumers copy the small `consumer/bunko.py` bootstrap to `scripts/bunko.py` and
the release's `bunko.lock.json` to their repository root. Existing GitHub CLI
authentication supplies private release access. No token goes in repository
configuration. The bootstrap verifies the pinned archive SHA256, rejects unsafe
archive entries, and verifies each extracted file against its manifest.

Python, Node, npm, uv, and Git remain prerequisites. The release includes
prebuilt browser assets; first setup installs the frozen runtime dependencies.
`--dev-tools` additionally installs the frozen reviewer development dependencies
to enable Tidewave. No live package registry is needed for ordinary restarts
after setup.

Application installation is cached by archive digest. Each checkout owns its
runtime directory, generated files, service identity, and database. Upgrading
one checkout does not change another checkout's release. Port collisions fail
startup; choose a different `runtime.port` in that workspace.
