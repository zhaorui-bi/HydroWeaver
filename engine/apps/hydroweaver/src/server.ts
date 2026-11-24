import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import path from 'node:path';
import process from 'node:process';

import { startServer } from '@moonshot-ai/kap-server';

import { ASCII_LOGO } from './banner';
import { createHydroWeaverHarness, ensureHydroWeaverSkillDirs, resolveHydroWeaverHome } from './harness';
import { ensureHydroWeaverMcpJson } from './mcp/register';
import { defaultWebAssetsDir, packageVersion, resolveUserPath } from './paths';

export interface WebOptions {
  readonly host?: string;
  readonly port?: number;
  readonly noOpen?: boolean;
  readonly homeDir?: string;
}

const REPLY_STYLE_GUIDE = `You are the HydroWeaver agent: an AI copilot for agentic closed-loop water-treatment train design.
Prefer the hydroweaver_* MCP tools for taxonomy lookup, query normalization, hybrid evidence retrieval,
treatment-train configuration generation, numerical parameter optimization, process simulation,
constraint-violation diagnosis, structural vs. parametric revision, knowledge staging, and AquaDesignGym evaluation.
For a complete case-to-report request, use the hydroweaver skill and the durable research controller.
Write the declared case to a snake_case UserQuery JSON file, then call hydroweaver_research_create with
a stable requestId, the research objective, and a bounded job budget. Creation starts no backend work.
Use hydroweaver_research_advance to reconcile and progress the same task; the controller owns its case
assessment, retrieval, recommendation, and audit jobs. Do not also launch those stages independently.
Recover the task with hydroweaver_research_list/status and return its task ID, current job ID, and next
action. Do not busy-poll. Surface structured attention items and obtain missing case data before
responding against the current task version. A caller-declared response is not verified human approval;
critical blockers and scientific audit failures cannot be waived. Retain conditional-screening gaps.
Use the following scientific checks in both modes. Invoke the named individual tools only for
independent operations; for a research task, inspect the controller's corresponding artifacts instead
of repeating its stage jobs:
1. Check runtime/data readiness with hydroweaver_status when unknown. Establish source water, measured
   influent values and units, contaminants, explicit effluent targets, intended use, site constraints,
   and the decision being supported. Use hydroweaver_catalog to verify controlled names.
2. Call hydroweaver_assess_case before recommendation. Report critical blockers and ask the highest-impact
   missing-information questions together. Do not invent missing values. With unresolved critical
   blockers, limit work to clarification or explicitly exploratory evidence retrieval. With high-priority
   gaps, any user-requested shortlist must state the gaps and cannot demonstrate target attainment.
   Preserve nitrate reporting basis (as NO3 versus as N), hardness basis, arsenic speciation, and flow.
   Do not silently convert units or adopt a standard's numeric targets from its name alone.
3. Retrieve evidence for the defined case with hydroweaver_retrieve_evidence. Compare its source-water
   matrix, speciation, scale, operating conditions, and residuals handling with this case. Distinguish
   retrieved findings, implemented rule results, and model synthesis. Record transferability gaps.
4. Use hydroweaver_recommend for ranked candidate trains, then hydroweaver_audit_report on the saved report.
   Inspect the audit's scientific status even when its job succeeded. A failed or empty audit cannot
   substantiate a recommendation. Retained extension fields do not imply upstream rules enforce them.
5. Hand off the case state, ordered trains, claim/source/chunk evidence, constraints and revisions,
   assumptions, uncertainty, missing information, job IDs, output paths, and manifest fingerprints.
   A rule pass or ranking score is not removal performance or proof of compliance. Without an explicit
   validated design basis, stay at technology screening rather than sizing, dose, or cost calculations.
Long operations run as durable jobs: use list/status, manifests, bounded log views, and artifacts
without busy-polling. Start with a small validation case before larger evaluations. Ask for confirmation
before rebuilding indexes, staging knowledge, overwriting explicit outputs, or launching expensive work;
an existing explicit authorization covers its stated scope. Never invent evidence, engineering results,
artifacts, completion states, or metrics. State the need for expert and applicable regulatory review,
treatability testing, pilot testing, and site-specific design before implementation.`;

export async function runWeb(options: WebOptions): Promise<void> {
  const homeDir = resolveUserPath(options.homeDir ?? resolveHydroWeaverHome());
  const host = validateHost(options.host ?? '127.0.0.1');
  const port = validatePort(options.port ?? 58_627);
  const webAssetsDir = resolveUserPath(
    process.env['HYDROWEAVER_WEB_ASSETS_DIR'] ?? defaultWebAssetsDir(),
  );
  if (!existsSync(path.join(webAssetsDir, 'index.html'))) {
    throw new Error(
      `Web UI assets not found at ${webAssetsDir}. Run npm run setup from the HydroWeaver project directory, or set HYDROWEAVER_WEB_ASSETS_DIR to a valid asset directory.`,
    );
  }

  const mcpJsonPath = ensureHydroWeaverMcpJson(homeDir);
  const harness = createHydroWeaverHarness(homeDir);
  try {
    await ensureHydroWeaverSkillDirs(harness);
  } finally {
    await harness.close();
  }

  const version = packageVersion();
  const server = await startServer({
    host,
    port,
    homeDir,
    logLevel: 'silent',
    webTitle: 'HydroWeaver',
    webAssetsDir,
    serverVersion: version,
    telemetry: false,
    hostIdentity: {
      productName: 'hydroweaver',
      version,
      platform: 'hydroweaver',
      displayName: 'HydroWeaver',
      replyStyleGuide: REPLY_STYLE_GUIDE,
    },
  });

  const token = server.authTokenService.getToken();
  const url = localServerUrl(server.host, server.port, token);
  if (!isLoopbackHost(host)) {
    process.stderr.write(
      `warning: the server is listening on non-loopback host ${host}; keep the bearer URL private and use a firewall.\n`,
    );
  }
  process.stdout.write(
    [
      ASCII_LOGO,
      `  HydroWeaver server ready ${version}`,
      ``,
      `  Local:    ${url}`,
      ``,
      `  Home:     ${homeDir}`,
      `  MCP:      hydroweaver registered in ${mcpJsonPath}`,
      `  Stop:     Ctrl+C`,
      ``,
    ].join('\n'),
  );

  if (options.noOpen !== true) {
    openUrl(url);
  }

  let shuttingDown = false;
  const shutdown = (signal: NodeJS.Signals): void => {
    if (shuttingDown) return;
    shuttingDown = true;
    void server.close().finally(() => {
      process.exit(signal === 'SIGINT' ? 130 : 143);
    });
  };
  process.once('SIGINT', () => {
    shutdown('SIGINT');
  });
  process.once('SIGTERM', () => {
    shutdown('SIGTERM');
  });
}

function openUrl(url: string): void {
  const opener =
    process.platform === 'darwin'
      ? 'open'
      : process.platform === 'win32'
        ? 'explorer.exe'
        : 'xdg-open';
  const args = [url];
  const child = spawn(opener, args, { detached: true, stdio: 'ignore' });
  child.once('error', (error) => {
    process.stderr.write(`warning: could not open a browser: ${error.message}\n`);
  });
  child.unref();
}

function validateHost(host: string): string {
  const trimmed = host.trim();
  if (trimmed === '' || /[\s/?#]/.test(trimmed)) {
    throw new Error(`Invalid web server host: ${host}`);
  }
  return trimmed;
}

function validatePort(port: number): number {
  if (!Number.isSafeInteger(port) || port < 0 || port > 65_535) {
    throw new Error(`Invalid web server port: ${String(port)} (expected 0-65535)`);
  }
  return port;
}

function localServerUrl(host: string, port: number, token: string): string {
  let browserHost = host;
  if (host === '0.0.0.0') browserHost = '127.0.0.1';
  if (host === '::' || host === '[::]') browserHost = '::1';
  const authority = browserHost.includes(':') ? `[${withoutBrackets(browserHost)}]` : browserHost;
  return `http://${authority}:${String(port)}/#token=${encodeURIComponent(token)}`;
}

function isLoopbackHost(host: string): boolean {
  const normalized = withoutBrackets(host).toLowerCase();
  return normalized === '127.0.0.1' || normalized === '::1' || normalized === 'localhost';
}

function withoutBrackets(host: string): string {
  return host.startsWith('[') && host.endsWith(']') ? host.slice(1, -1) : host;
}
