# Extraction record

Source: `NakamaDevs/sdlc` at
`a6787395ccbd92ce3daf17bdbdab385e5187cbec`.

The source owner completed the Tidewave work in Herdr pane `w1:p4` before the
snapshot was taken. The extraction uses committed application files only. It
does not copy notes, generated documentation, credentials, MCP configuration,
or installed dependencies.

The first Bunko release keeps the current DuckDB note schema. Stop the old
workspace before starting Bunko against its notes database. Bunko creates a
backup before opening an existing database for the first time at this version.
Do not run the old and new notes writers against the same file.

SDLC and the separate docs repository adopt Bunko through separate issues and
PRs. Their workspace configuration owns repository paths, names, routes, and
state. Their exact release pin includes the archive SHA256.

Rollback stops Bunko, restores the previous application pin, and uses the
pre-upgrade notes backup if a later schema migration requires it. Never replace
an already-published archive under the same version.
