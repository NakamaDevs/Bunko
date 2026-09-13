# Bunko services

These services are distributed together in the Bunko release bundle. Use the
root `bunko` CLI with a consumer `workspace.json`; do not launch the AppHost
without its workspace environment.

The docs renderer builds configured roots into `BUNKO_STATE/docs`. The review
API reads configured Git checkouts. A single notes process owns
`BUNKO_DATABASE`. The gateway routes docs, review, notes, and optional Tidewave
requests and checks browser origins.

The normal reviewer serves prebuilt static assets. `bunko start --dev-tools`
runs Vite with the Tidewave plugin and loads its toolbar in docs. Static docs
builds omit the toolbar. Tidewave's MCP endpoint is `/tidewave/mcp` on either
workspace host; configure clients with the URLs printed by `bunko start`.

Run `mise run test` for service tests and `mise run verify` for the full gate.
