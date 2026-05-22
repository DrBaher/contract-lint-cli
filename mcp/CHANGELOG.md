# Changelog — contract-lint-mcp

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-05-22

### Added — first release
- MCP stdio server wrapping the `contract-lint` CLI. Three tools: `lint_contract`
  (by `path` or inline `text`, with `format`/`fail_on`/`enable`/`disable`), `list_rules`,
  and `lint_demo`.
- Shells out to the installed `contract-lint` binary (`$CONTRACT_LINT_BIN` overrides) and
  returns the CLI's locked JSON. CLI exit `1` (findings) is a successful tool call; exit
  `2` (bad usage / unreadable input) becomes an MCP tool error with a stable code.
- Protocol tests (`node --test`) drive a real MCP client over stdio.
