#!/usr/bin/env node
// contract-lint-mcp — Model Context Protocol server wrapping contract-lint.
// Single-file by design, matching the parent CLI. Stdio transport only in v1.
//
// Three tools:
//   lint_contract  — lint a contract by path or inline text -> the --json report
//   list_rules     — the rule catalog (id, severity, default_enabled, description)
//   lint_demo      — lint the bundled, deliberately-flawed sample contract
//
// contract-lint is a Python CLI, so this server shells out to the installed
// `contract-lint` binary (override with $CONTRACT_LINT_BIN). It never parses prose:
// it returns the CLI's locked JSON. Findings (CLI exit 1) are a successful lint, not
// an error; only bad usage / unreadable input (exit 2) becomes an MCP tool error.

import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";
import { execFileSync } from "node:child_process";

export const MCP_VERSION = "0.1.0";
const BIN = process.env.CONTRACT_LINT_BIN || "contract-lint";

// ----------------------------------------------------------------------------
// Error class — carries a stable code for the MCP error envelope.
// ----------------------------------------------------------------------------

export class McpToolError extends Error {
  constructor(code, message) {
    super(message);
    this.code = code;
    this.name = "McpToolError";
  }
}

// ----------------------------------------------------------------------------
// Shell out to contract-lint (no shell; argv array; timeout + output cap).
// Returns { code, stdout, stderr }. code 0/1 are normal lint outcomes.
// ----------------------------------------------------------------------------

export function runContractLint(args, input = undefined) {
  try {
    const stdout = execFileSync(BIN, args, {
      input,
      timeout: 20000,
      maxBuffer: 32 * 1024 * 1024,
      encoding: "utf8",
      env: { ...process.env, NO_COLOR: "1" },
    });
    return { code: 0, stdout, stderr: "" };
  } catch (e) {
    if (typeof e.status === "number") {
      return { code: e.status, stdout: e.stdout || "", stderr: e.stderr || "" };
    }
    throw new McpToolError(
      "CONTRACT_LINT_NOT_FOUND",
      `could not run '${BIN}': ${e.message}. Install it with: pip install contract-lint ` +
        `(or set CONTRACT_LINT_BIN to its path).`,
    );
  }
}

function parseJsonOrThrow(text, what) {
  try {
    return JSON.parse(text);
  } catch {
    throw new McpToolError("BAD_OUTPUT", `contract-lint produced no JSON for ${what}`);
  }
}

// ----------------------------------------------------------------------------
// Tool handlers
// ----------------------------------------------------------------------------

const RULE_FLAGS = (ids, flag) =>
  Array.isArray(ids) ? ids.flatMap((id) => [flag, String(id)]) : [];

export function lintContract(args = {}) {
  const hasPath = typeof args.path === "string" && args.path.length > 0;
  const hasText = typeof args.text === "string";
  if (hasPath === hasText) {
    throw new McpToolError("INVALID_ARGS", "provide exactly one of 'path' or 'text'");
  }
  const failOn = args.fail_on || "error";
  if (!["error", "warning", "none"].includes(failOn)) {
    throw new McpToolError("INVALID_ARGS", `fail_on must be error|warning|none, got '${failOn}'`);
  }
  const target = hasPath ? args.path : "-";
  const fmt = args.format || (hasText ? "md" : "auto");
  const cliArgs = [
    target, "--json", "--fail-on", failOn, "--no-color", "--format", fmt,
    ...RULE_FLAGS(args.enable, "--enable"),
    ...RULE_FLAGS(args.disable, "--disable"),
  ];
  const { code, stdout, stderr } = runContractLint(cliArgs, hasText ? args.text : undefined);
  if (code === 2) {
    throw new McpToolError("LINT_ERROR", (stderr || "bad usage / unreadable input").trim());
  }
  return parseJsonOrThrow(stdout, "lint_contract"); // exit 0 (clean) or 1 (findings)
}

export function listRules() {
  const { code, stdout, stderr } = runContractLint(["rules", "--json"]);
  if (code !== 0) throw new McpToolError("LINT_ERROR", (stderr || "rules failed").trim());
  return parseJsonOrThrow(stdout, "list_rules");
}

export function lintDemo() {
  const { stdout } = runContractLint(["demo", "--json"]); // demo always exits 0
  return parseJsonOrThrow(stdout, "lint_demo");
}

// ----------------------------------------------------------------------------
// Tool catalog
// ----------------------------------------------------------------------------

export const TOOLS = [
  {
    name: "lint_contract",
    description:
      "Lint a contract for internal-consistency defects (leftover placeholders, broken " +
      "cross-references, undefined/unused/duplicate defined terms, numbering gaps, " +
      "inconsistent parties/dates, written-vs-figure number mismatches). Returns the locked " +
      "JSON report: { ok, exit_code, summary, findings[] }, each finding { rule, severity, " +
      "message, line, column?, excerpt }. Findings are a successful lint, not an error.",
    inputSchema: {
      type: "object",
      properties: {
        path: { type: "string", description: "Path to a contract file (.md/.txt/.html; .docx/.pdf need the matching extra)." },
        text: { type: "string", description: "Inline contract text to lint instead of a path." },
        format: {
          type: "string",
          enum: ["auto", "md", "markdown", "txt", "text", "html", "docx", "pdf"],
          description: "Input format. Default: auto-detect by extension for a path, 'md' for inline text.",
        },
        fail_on: {
          type: "string",
          enum: ["error", "warning", "none"],
          description: "Gate threshold reflected in ok/exit_code (default: error).",
        },
        enable: { type: "array", items: { type: "string" }, description: "Rule ids to enable (e.g. 'signature-block', 'undefined-term')." },
        disable: { type: "array", items: { type: "string" }, description: "Rule ids to disable." },
      },
      additionalProperties: false,
    },
  },
  {
    name: "list_rules",
    description:
      "List every lint rule: id, severity (error|warning), default_enabled, and description. " +
      "Call this to discover rule ids instead of hardcoding them.",
    inputSchema: { type: "object", properties: {}, additionalProperties: false },
  },
  {
    name: "lint_demo",
    description:
      "Lint the bundled, deliberately-flawed sample contract and return its JSON report. " +
      "Zero-config, offline — a quick way to see the shape of contract-lint's output.",
    inputSchema: { type: "object", properties: {}, additionalProperties: false },
  },
];

// ----------------------------------------------------------------------------
// Dispatch
// ----------------------------------------------------------------------------

export async function dispatchMcp(name, args) {
  try {
    let report;
    if (name === "lint_contract") report = lintContract(args || {});
    else if (name === "list_rules") report = listRules();
    else if (name === "lint_demo") report = lintDemo();
    else throw new McpToolError("UNKNOWN_TOOL", `no such tool: ${name}`);
    return { content: [{ type: "text", text: JSON.stringify(report, null, 2) }] };
  } catch (err) {
    const code = err instanceof McpToolError ? err.code : "INTERNAL";
    return { isError: true, content: [{ type: "text", text: `${code}: ${err.message || err}` }] };
  }
}

// ----------------------------------------------------------------------------
// Serve over stdio
// ----------------------------------------------------------------------------

export async function serveMcpStdio() {
  const server = new Server(
    { name: "contract-lint-mcp", version: MCP_VERSION },
    { capabilities: { tools: {} } },
  );
  server.setRequestHandler(ListToolsRequestSchema, async () => ({ tools: TOOLS }));
  server.setRequestHandler(CallToolRequestSchema, async (req) => {
    const { name, arguments: args } = req.params;
    return await dispatchMcp(name, args);
  });
  const transport = new StdioServerTransport();
  await server.connect(transport);
}

// ----------------------------------------------------------------------------
// Entry
// ----------------------------------------------------------------------------

const isMain = import.meta.url === `file://${process.argv[1]}`;
if (isMain) {
  // Don't log to stdout — the stdio transport claims it.
  serveMcpStdio().catch((e) => {
    process.stderr.write(`contract-lint-mcp: fatal: ${e.message || e}\n`);
    process.exit(1);
  });
}
