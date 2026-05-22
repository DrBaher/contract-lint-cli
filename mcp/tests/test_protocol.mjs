// Protocol test: connect a real MCP client to the server over stdio, list the tools,
// and call each one. contract-lint is reached via $CONTRACT_LINT_BIN (set below to the
// repo's module so the test needs no global install).
import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";

const HERE = dirname(fileURLToPath(import.meta.url));
const SERVER = join(HERE, "..", "contract-lint-mcp.mjs");
const REPO = join(HERE, "..", "..");
// Run contract-lint as the repo module, so the test is self-contained.
const CONTRACT_LINT_BIN = process.env.CONTRACT_LINT_BIN || join(REPO, ".venv", "bin", "contract-lint");

let client;

before(async () => {
  const transport = new StdioClientTransport({
    command: process.execPath,
    args: [SERVER],
    env: { ...process.env, CONTRACT_LINT_BIN },
  });
  client = new Client({ name: "test-client", version: "0.0.0" }, { capabilities: {} });
  await client.connect(transport);
});

after(async () => {
  await client?.close();
});

test("lists the three tools", async () => {
  const { tools } = await client.listTools();
  const names = tools.map((t) => t.name).sort();
  assert.deepEqual(names, ["lint_contract", "lint_demo", "list_rules"]);
  for (const t of tools) assert.ok(t.inputSchema && t.description);
});

test("list_rules returns the rule catalog", async () => {
  const res = await client.callTool({ name: "list_rules", arguments: {} });
  assert.ok(!res.isError);
  const payload = JSON.parse(res.content[0].text);
  assert.equal(payload.tool, "contract-lint");
  assert.ok(payload.rules.length >= 8);
  assert.ok(payload.rules.every((r) => r.id && r.severity && "default_enabled" in r));
});

test("lint_contract on inline text finds the placeholder", async () => {
  const res = await client.callTool({
    name: "lint_contract",
    arguments: { text: "# Deal\nFee is {{amount}} per month.\n", format: "md" },
  });
  assert.ok(!res.isError);
  const report = JSON.parse(res.content[0].text);
  assert.equal(report.tool, "contract-lint");
  assert.equal(report.ok, false); // placeholder is an error
  assert.equal(report.summary.by_rule.placeholder, 1);
});

test("lint_contract honors enable (opt-in rule)", async () => {
  const res = await client.callTool({
    name: "lint_contract",
    arguments: { text: "The Disclosing Party notifies the Disclosing Party.\n", enable: ["undefined-term"] },
  });
  const report = JSON.parse(res.content[0].text);
  assert.ok("undefined-term" in report.summary.by_rule);
});

test("lint_contract rejects both path and text", async () => {
  const res = await client.callTool({
    name: "lint_contract",
    arguments: { path: "x.md", text: "y" },
  });
  assert.ok(res.isError);
  assert.match(res.content[0].text, /INVALID_ARGS/);
});

test("lint_demo returns a populated report", async () => {
  const res = await client.callTool({ name: "lint_demo", arguments: {} });
  assert.ok(!res.isError);
  const report = JSON.parse(res.content[0].text);
  assert.ok(report.summary.total > 5);
});
