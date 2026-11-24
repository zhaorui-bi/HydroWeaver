#!/usr/bin/env node

import { spawnSync } from 'node:child_process';
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import process from 'node:process';
import { fileURLToPath } from 'node:url';

import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StdioClientTransport } from '@modelcontextprotocol/sdk/client/stdio.js';

const packageRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const entry = path.resolve(process.argv[2] ?? path.join(packageRoot, 'dist', 'mcp-server.mjs'));
const scratch = mkdtempSync(path.join(tmpdir(), 'hydroweaver-mcp-smoke-'));
const transport = new StdioClientTransport({
  command: process.execPath,
  args: [entry],
  env: {
    ...process.env,
    HYDROWEAVER_HOME: path.join(scratch, 'home'),
    HYDROWEAVER_JOBS_DIR: path.join(scratch, 'jobs'),
    HYDROWEAVER_WORKDIR: scratch,
    HYDROWEAVER_COMMAND: '',
    HYDROWEAVER_REPO: '',
  },
});
const client = new Client({ name: 'hydroweaver-mcp-smoke', version: '1.0.0' });

try {
  await client.connect(transport);
  const catalog = await client.listTools();
  assert(catalog.tools.length === 25, `expected 25 tools, found ${String(catalog.tools.length)}`);
  assert(
    new Set(catalog.tools.map((tool) => tool.name)).size === catalog.tools.length,
    'tool names are not unique',
  );
  const assess = catalog.tools.find((tool) => tool.name === 'hydroweaver_assess_case');
  assert(assess?.annotations?.readOnlyHint === true, 'case assessment lacks read-only annotation');
  const audit = catalog.tools.find((tool) => tool.name === 'hydroweaver_audit_report');
  assert(audit?.annotations?.idempotentHint === true, 'report audit lacks idempotent annotation');
  const cancel = catalog.tools.find((tool) => tool.name === 'hydroweaver_job_cancel');
  assert(cancel?.annotations?.destructiveHint === true, 'cancel tool lacks destructive annotation');
  const manifest = catalog.tools.find((tool) => tool.name === 'hydroweaver_job_manifest');
  assert(manifest?.annotations?.readOnlyHint === true, 'manifest tool lacks read-only annotation');
  for (const name of ['status', 'list']) {
    const tool = catalog.tools.find((item) => item.name === `hydroweaver_research_${name}`);
    assert(tool?.annotations?.readOnlyHint === true, `research ${name} lacks read-only annotation`);
  }
  for (const name of ['create', 'advance', 'respond', 'cancel']) {
    const tool = catalog.tools.find((item) => item.name === `hydroweaver_research_${name}`);
    assert(tool?.annotations?.readOnlyHint === false, `research ${name} must declare writes`);
  }

  const jobs = await client.callTool({ name: 'hydroweaver_job_list', arguments: {} });
  const jobsText = jobs.content.find((item) => item.type === 'text')?.text ?? '';
  assert(jobsText.includes('"total": 0'), `unexpected empty job list: ${jobsText}`);

  const status = await client.callTool({ name: 'hydroweaver_status', arguments: {} });
  assert(status.content.some((item) => item.type === 'text'), 'status tool returned no text content');

  const queryFile = path.join(scratch, 'query.json');
  writeFileSync(queryFile, JSON.stringify({
    source_water: 'groundwater',
    contaminants: ['arsenic'],
    water_quality: { arsenic_ug_L: 150 },
    treatment_targets: { arsenic_ug_L: 10 },
  }));
  const request = {
    requestId: 'mcp-smoke-arsenic-case',
    objective: 'Screen arsenic treatment options',
    queryFile,
  };
  const created = payload(await client.callTool({ name: 'hydroweaver_research_create', arguments: request }));
  assert(/^research_[a-f0-9]{24}$/.test(created.id), 'research task id is invalid');
  assert(created.version === 1 && created.status === 'open', 'creation unexpectedly advanced research');
  assert(created.assignments.length === 0, 'creation launched an assignment without advance');
  const duplicate = payload(await client.callTool({ name: 'hydroweaver_research_create', arguments: request }));
  assert(duplicate.id === created.id && duplicate.version === created.version, 'repeated request is not idempotent');
  const recovered = payload(await client.callTool({
    name: 'hydroweaver_research_status', arguments: { taskId: created.id },
  }));
  assert(recovered.id === created.id && recovered.version === created.version, 'status did not recover the same research task');
  const listed = payload(await client.callTool({ name: 'hydroweaver_research_list', arguments: {} }));
  assert(listed.returned === 1 && listed.tasks[0]?.id === created.id, 'research list did not recover the registered task');
  writeFileSync(queryFile, JSON.stringify({ source_water: 'surface water' }));
  const conflict = await client.callTool({ name: 'hydroweaver_research_create', arguments: request });
  assert(conflict.isError === true, 'a changed input reused the original request id');
  let unknownRejected = false;
  try {
    const invalid = await client.callTool({
      name: 'hydroweaver_research_create',
      arguments: { ...request, requestId: 'mcp-smoke-unknown-parameter', maxJbos: 1 },
    });
    unknownRejected = invalid.isError === true;
  } catch {
    unknownRejected = true;
  }
  assert(unknownRejected, 'research creation silently discarded an unknown budget parameter');
  const unchanged = payload(await client.callTool({ name: 'hydroweaver_research_list', arguments: {} }));
  assert(unchanged.returned === 1, 'rejected research input nevertheless registered a task');
  const after = payload(await client.callTool({ name: 'hydroweaver_job_list', arguments: {} }));
  assert(after.total === 0, 'research registration or status unexpectedly launched a backend job');

  const launchDir = path.join(scratch, 'old-launch');
  mkdirSync(launchDir);
  const cli = path.join(packageRoot, 'dist', 'cli.mjs');
  const { HYDROWEAVER_JOBS_DIR: _ignored, ...baseEnv } = process.env;
  const sharedEnv = { ...baseEnv, HYDROWEAVER_HOME: path.join(scratch, 'home'), HYDROWEAVER_WORKDIR: scratch };
  const researchRequest = path.join(scratch, 'request.json');
  writeFileSync(queryFile, JSON.stringify({ source_water: 'groundwater', contaminants: ['arsenic'] }));
  writeFileSync(researchRequest, JSON.stringify({ ...request, requestId: 'legacy-case' }));
  function runCli(args, env = sharedEnv) {
    const result = spawnSync(process.execPath, [cli, 'research', ...args], { cwd: launchDir, env, encoding: 'utf8' });
    assert(result.status === 0, `CLI failed: ${result.stderr} ${result.stdout}`);
    return JSON.parse(result.stdout);
  }
  const legacy = runCli(['create', '--input', researchRequest], {
    ...sharedEnv, HYDROWEAVER_JOBS_DIR: path.join(launchDir, 'hydroweaver-jobs'),
  });
  const migrationTransport = new StdioClientTransport({ command: process.execPath, args: [entry], cwd: launchDir, env: sharedEnv });
  const migrationClient = new Client({ name: 'hydroweaver-store-smoke', version: '1.0.0' });
  try {
    await migrationClient.connect(migrationTransport);
    const oldStatus = payload(await migrationClient.callTool({ name: 'hydroweaver_research_status', arguments: { taskId: legacy.id } }));
    assert(oldStatus.id === legacy.id && oldStatus.mandate.jobsRoot === legacy.mandate.jobsRoot, 'legacy MCP task was not recovered in place');
    const current = payload(await migrationClient.callTool({ name: 'hydroweaver_research_create', arguments: { ...request, requestId: 'current-case' } }));
    assert(current.mandate.jobsRoot === path.join(scratch, 'hydroweaver-jobs'), 'new MCP task did not use the workspace store');
    const cliList = runCli(['list']);
    assert(cliList.tasks.some((task) => task.id === legacy.id) && cliList.tasks.some((task) => task.id === current.id), 'CLI did not list both stores');
  } finally {
    await migrationClient.close().catch(() => undefined);
  }

  process.stdout.write('MCP smoke: tools, research recovery, and shared CLI/MCP job stores verified\n');
} finally {
  await client.close().catch(() => undefined);
  rmSync(scratch, { recursive: true, force: true });
}

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function payload(result) {
  assert(result.isError !== true, `MCP tool failed: ${JSON.stringify(result.content)}`);
  const text = result.content.find((item) => item.type === 'text')?.text;
  assert(typeof text === 'string', 'MCP tool returned no JSON text');
  return JSON.parse(text);
}
