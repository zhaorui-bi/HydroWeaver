import path from 'node:path';
import process from 'node:process';
import { createInterface, type Interface } from 'node:readline';

import type { KimiHarness, Session } from '@moonshot-ai/kimi-code-sdk';

import { ASCII_LOGO } from './banner';
import { CliArgumentError, parseCliInvocation } from './cli-args';
import { runDoctor, formatDoctorReport } from './doctor';
import {
  attachOpenAquaTools,
  createDefaultSession,
  createOpenAquaHarness,
  ensureOpenAquaSkillDirs,
  promptTurnToEnd,
  resolveOpenAquaHome,
} from './harness';
import { runOnboard } from './onboard';
import { runResearchCommand } from './hydroweaver/research-tools';
import { HYDROWEAVER_TOOLS } from './hydroweaver/tools';
import {
  defaultWebAssetsDir,
  findPackageRoot,
  packageVersion,
  resolveUserPath,
  resolveJobStores,
  skillsDir,
} from './paths';
import { runWeb } from './server';
import { runToolsList } from './toolsCmd';
import { launchTui } from './tui';

const USAGE = `HydroWeaver — from plausible to feasible water treatment train designs through agentic closed-loop optimization

Usage:
  hydroweaver                      launch the interactive workbench (full TUI)
  hydroweaver run "<prompt>"       one-shot mode: create a session, send one prompt,
                                    stream the reply to stdout, exit
  hydroweaver chat                 interactive REPL with one persistent session;
                                    type "quit" (or press Ctrl+C / stdin EOF) to exit
  hydroweaver web [options]        start the HydroWeaver web server + UI
                                    [--port N] [--host H] [--no-open] [--home DIR]
  hydroweaver doctor [options]     check the installation
                                    [--json] [--probe] [--home DIR]
  hydroweaver onboard [options]    guided setup: home dir, credentials import,
                                    [--yes] [--home DIR]
                                    backend detection, MCP + skills
                                    [--hydroweaver-command COMMAND | --hydroweaver-repo DIR]
                                    [--import-from DIR]
                                    model provider (API key, no login required):
                                    [--provider kimi-coding|zai|deepseek|custom]
                                    [--api-key KEY | --api-key-env ENV] [--model NAME]
                                    [--base-url URL] [--provider-type TYPE]
  hydroweaver tools [--json]       list HydroWeaver query, retrieval, design, evaluation,
                                    and durable-job tools exposed to the agent
                                    [--home DIR]
  hydroweaver optimize [options]   run the closed-loop treatment-train optimization
                                    [--input FILE] [--top-k N] [--max-rounds N]
                                    [--wait] [--home DIR]
                                    FILE is a UserQuery JSON document; without --wait
                                    a durable job id is returned immediately
  hydroweaver research <action>    control a durable case-to-report research task;
                                    actions: create, status, list, advance, respond, cancel
                                    [--input FILE] [--home DIR]
                                    status/advance: --id ID instead of --input
                                    advance: [--expected-version N]
                                    JSON input uses the matching research MCP schema;
                                    no conversational model is needed for task control
  hydroweaver info [--home DIR]    version + paths
  hydroweaver --version            print version
  hydroweaver <command> --help     print this help

Environment:
  HYDROWEAVER_HOME     HydroWeaver data directory (config.toml, credentials, mcp.json).
                      Defaults to ~/.hydroweaver.
  HYDROWEAVER_COMMAND  JSON array overriding the adapter-compatible backend command.
  HYDROWEAVER_REPO     OpenAqua repository checkout containing water_treatment_agent/.
  HYDROWEAVER_PYTHON   Optional Python interpreter for that checkout.
  OPENROUTER_API_KEY Optional key used by OpenAqua parsing/planning/explanation agents.
  HYDROWEAVER_WORKDIR  Default working directory for research and optimization jobs.
  HYDROWEAVER_JOBS_DIR Explicit job store; disables legacy-store discovery.
                      Default: <HYDROWEAVER_WORKDIR or cwd>/hydroweaver-jobs.
                      Older MCP jobs in <current cwd>/hydroweaver-jobs remain accessible;
                      set HYDROWEAVER_JOBS_DIR to access other old locations.
`;

let activeHarness: KimiHarness | undefined;

// Registered lazily by the run/chat paths — the TUI path must not get its
// wrapper killed by Ctrl+C (the child handles signals itself).
function registerSigintHandler(): void {
  process.once('SIGINT', () => {
    void (async () => {
      await activeHarness?.close().catch(() => undefined);
      process.exit(130);
    })();
  });
}

async function main(argv: readonly string[]): Promise<void> {
  const invocation = parseCliInvocation(argv);

  switch (invocation.kind) {
    case 'run':
      await runOnce(invocation.prompt);
      return;
    case 'chat':
      await chatRepl();
      return;
    case 'web':
      await runWeb({
        host: invocation.host,
        port: invocation.port,
        noOpen: invocation.noOpen,
        homeDir: invocation.homeDir,
      });
      return;
    case 'doctor': {
      const report = await runDoctor({
        probe: invocation.probe,
        homeDir: invocation.homeDir,
      });
      if (invocation.json) {
        process.stdout.write(`${JSON.stringify(report, null, 2)}\n`);
      } else {
        process.stdout.write(`${formatDoctorReport(report)}\n`);
      }
      if (!report.healthy) process.exitCode = 1;
      return;
    }
    case 'onboard':
      await runOnboard({
        yes: invocation.yes,
        homeDir: invocation.homeDir,
        hydroweaverCommand: invocation.hydroweaverCommand,
        hydroweaverRepo: invocation.hydroweaverRepo,
        importFrom: invocation.importFrom,
        provider: invocation.provider,
        apiKey: invocation.apiKey,
        apiKeyEnv: invocation.apiKeyEnv,
        model: invocation.model,
        baseUrl: invocation.baseUrl,
        providerType: invocation.providerType,
      });
      return;
    case 'tools':
      runToolsList(invocation.json, invocation.homeDir);
      return;
    case 'research': {
      const env = invocation.homeDir === undefined
        ? process.env
        : { ...process.env, HYDROWEAVER_HOME: invocation.homeDir };
      const homeDir = resolveOpenAquaHome(env);
      const stores = resolveJobStores(env);
      const result = await runResearchCommand(invocation.action, {
        inputFile: invocation.inputFile,
        taskId: invocation.taskId,
        expectedVersion: invocation.expectedVersion,
      }, { homeDir, ...stores, env });
      for (const item of result.content) process.stdout.write(`${item.text}\n`);
      if (result.isError === true) process.exitCode = 1;
      return;
    }
    case 'optimize': {
      const env =
        invocation.homeDir === undefined
          ? process.env
          : { ...process.env, HYDROWEAVER_HOME: invocation.homeDir };
      const homeDir = resolveOpenAquaHome(env);
      const stores = resolveJobStores(env);
      const tool = HYDROWEAVER_TOOLS.find((entry) => entry.name === 'hydroweaver_optimize_trains');
      if (tool === undefined) throw new Error('The closed-loop optimization tool is not registered.');
      const result = await tool.run({
        queryFile: invocation.inputFile,
        topK: invocation.topK,
        maxRounds: invocation.maxRounds,
        wait: invocation.wait,
      }, { homeDir, ...stores, env });
      for (const item of result.content) process.stdout.write(`${item.text}\n`);
      if (result.isError === true) process.exitCode = 1;
      return;
    }
    case 'info': {
      const env =
        invocation.homeDir === undefined
          ? process.env
          : { ...process.env, HYDROWEAVER_HOME: invocation.homeDir };
      const homeDir = resolveOpenAquaHome(env);
      const workDir = resolveUserPath(env['HYDROWEAVER_WORKDIR'] ?? process.cwd());
      const jobsDir = resolveUserPath(
        env['HYDROWEAVER_JOBS_DIR'] ?? path.join(workDir, 'hydroweaver-jobs'),
      );
      process.stdout.write(
        [
          `hydroweaver ${packageVersion()}`,
          `package: ${findPackageRoot()}`,
          `home: ${homeDir}`,
          `workdir: ${workDir}`,
          `jobs: ${jobsDir}`,
          `skills: ${skillsDir()}`,
          `web-ui: ${defaultWebAssetsDir()}`,
          '',
        ].join('\n'),
      );
      return;
    }
    case 'version':
      process.stdout.write(`${packageVersion()}\n`);
      return;
    case 'help':
      process.stdout.write(USAGE);
      return;
    case 'tui': {
      const code = await launchTui();
      if (code < 0) {
        process.stderr.write(
          'TUI bundle not built yet — run `npm run build:tui` in the HydroWeaver repo once. Falling back to plain REPL chat.\n\n',
        );
        await chatRepl();
      } else {
        process.exitCode = code;
      }
    }
  }
}

async function openHarness(): Promise<{ harness: KimiHarness; session: Session }> {
  registerSigintHandler();
  const homeDir = resolveOpenAquaHome();
  const harness = createOpenAquaHarness(homeDir);
  activeHarness = harness;
  process.stderr.write(ASCII_LOGO);
  await ensureOpenAquaSkillDirs(harness);
  const session = await createDefaultSession(harness);
  try {
    await attachOpenAquaTools(session, homeDir);
  } catch (error: unknown) {
    process.stderr.write(`warning: could not attach HydroWeaver MCP tools: ${String(error)}\n`);
  }
  return { harness, session };
}

async function runOnce(promptText: string): Promise<void> {
  const { harness, session } = await openHarness();
  try {
    process.stderr.write(`session: ${session.id}\n`);
    await promptTurnToEnd(session, promptText);
  } finally {
    await closeHarness(harness);
  }
}

async function chatRepl(): Promise<void> {
  const { harness, session } = await openHarness();
  let rl: Interface | undefined;
  try {
    process.stderr.write(`chat session: ${session.id} (workDir: ${session.workDir})\n`);

    rl = createInterface({
      input: process.stdin,
      output: process.stdout,
      prompt: '> ',
      terminal: process.stdin.isTTY,
    });
    const promptAgain = (): void => {
      if (rl !== undefined) {
        rl.prompt();
      }
    };
    promptAgain();

    for await (const line of rl) {
      const input = line.trim();
      if (input.length === 0) {
        promptAgain();
        continue;
      }
      if (input === 'quit' || input === 'exit') {
        break;
      }
      try {
        await promptTurnToEnd(session, input);
      } catch (error: unknown) {
        process.stderr.write(`turn failed: ${String(error)}\n`);
      }
      promptAgain();
    }
  } finally {
    rl?.close();
    await closeHarness(harness);
  }
}

async function closeHarness(harness: KimiHarness): Promise<void> {
  await harness.close();
  if (activeHarness === harness) {
    activeHarness = undefined;
  }
}

try {
  await main(process.argv.slice(2));
} catch (error: unknown) {
  process.stderr.write(`error: ${error instanceof Error ? error.message : String(error)}\n`);
  if (error instanceof CliArgumentError) {
    process.stderr.write(`\n${USAGE}`);
  } else if (
    process.env['HYDROWEAVER_DEBUG'] === '1' &&
    error instanceof Error &&
    error.stack !== undefined
  ) {
    process.stderr.write(`${error.stack}\n`);
  }
  process.exitCode = 1;
}
