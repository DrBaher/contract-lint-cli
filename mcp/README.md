# contract-lint-mcp

An [MCP](https://modelcontextprotocol.io) server that exposes **contract-lint** as agent
tools. Point an MCP-capable client (Claude Desktop, an agent runtime, etc.) at it and the
model can lint a contract for internal-consistency defects and gate on the result — without
shelling out itself.

It wraps the `contract-lint` Python CLI (it shells out to the installed binary and returns
the CLI's **locked JSON**, never parsed prose). Part of the
[contract-ops CLI suite](https://github.com/DrBaher).

## Tools

| Tool | What it does |
|---|---|
| `lint_contract` | Lint a contract by `path` **or** inline `text`. Optional `format`, `fail_on` (`error`\|`warning`\|`none`), `enable[]`, `disable[]`. Returns `{ ok, exit_code, summary, findings[] }`; each finding is `{ rule, severity, message, line, column?, excerpt }`. Findings are a *successful* lint, not an error. |
| `list_rules` | The rule catalog: `id`, `severity`, `default_enabled`, `description`. Discover rule ids here instead of hardcoding them. |
| `lint_demo` | Lint the bundled, deliberately-flawed sample contract (zero-config, offline). |

## Prerequisites

The `contract-lint` **Python** CLI must be installed and on `PATH`:

```bash
pip install contract-lint
```

(Override the binary location with the `CONTRACT_LINT_BIN` environment variable.)

## Run

```bash
npm install            # installs the MCP SDK
node contract-lint-mcp.mjs     # stdio transport
```

### Claude Desktop / MCP client config

```json
{
  "mcpServers": {
    "contract-lint": {
      "command": "npx",
      "args": ["-y", "contract-lint-mcp"],
      "env": { "CONTRACT_LINT_BIN": "contract-lint" }
    }
  }
}
```

## Develop

```bash
npm install
CONTRACT_LINT_BIN=$(command -v contract-lint) npm test   # node --test, real stdio client
```

Stdio transport only in v1. See the parent CLI's [AGENTS.md](../AGENTS.md) for the output
contract and exit codes.
