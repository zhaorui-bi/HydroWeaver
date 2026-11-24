import { createHash, randomBytes } from 'node:crypto';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import process from 'node:process';

import { z } from 'zod';

import { resolveUserPath } from '../paths';
import {
  describeBackend,
  resolveHydroWeaverBackend,
  runBackend,
  type HydroWeaverBackend,
  type RunResult,
} from './backend';
import {
  cancelJob,
  configuredJobOutput,
  getJob,
  jobLog,
  listJobArtifacts,
  listJobs,
  readJobLog,
  readJobRunManifest,
  startJob,
  waitForJob,
  type JobSnapshot,
  type JobStatus,
} from './jobs';
import { createEngineeringJobRequest } from './provenance';
import { RESEARCH_TOOLS } from './research-tools';
import {
  describeSimulationBackend,
  probeSimulation,
  resolveSimulationBackend,
  simulationRunnerPath,
  simulationSetupGuidance,
} from './sim';

export interface ToolContext {
  readonly homeDir?: string;
  readonly jobsRoot: string;
  readonly legacyJobsRoot?: string;
  readonly env: NodeJS.ProcessEnv;
}

export interface ToolResult {
  [key: string]: unknown;
  content: { type: 'text'; text: string }[];
  isError?: boolean;
}

export interface HydroWeaverTool {
  readonly name: string;
  readonly title: string;
  readonly description: string;
  readonly inputSchema: Record<string, z.ZodType>;
  readonly strictInput?: boolean;
  run(args: Record<string, unknown>, ctx: ToolContext): Promise<ToolResult>;
}

export interface HydroWeaverToolAnnotations {
  readonly readOnlyHint: boolean;
  readonly destructiveHint: boolean;
  readonly idempotentHint: boolean;
  readonly openWorldHint: boolean;
}

const READ_ONLY_IDEMPOTENT = new Set([
  'hydroweaver_status',
  'hydroweaver_catalog',
  'hydroweaver_gym_tasks',
  'hydroweaver_job_list',
  'hydroweaver_job_status',
  'hydroweaver_job_manifest',
  'hydroweaver_job_log',
  'hydroweaver_job_artifacts',
  'hydroweaver_research_status',
  'hydroweaver_research_list',
]);
const READ_ONLY_OPEN_WORLD = new Set([
  'hydroweaver_normalize_query',
  'hydroweaver_assess_case',
  'hydroweaver_check_constraints',
]);
const IDEMPOTENT_WRITES = new Set([
  'hydroweaver_build_indexes',
  'hydroweaver_evaluate_gym',
  'hydroweaver_audit_report',
]);

export function hydroWeaverToolAnnotations(name: string): HydroWeaverToolAnnotations {
  if (READ_ONLY_IDEMPOTENT.has(name)) {
    return { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false };
  }
  if (READ_ONLY_OPEN_WORLD.has(name)) {
    return { readOnlyHint: true, destructiveHint: false, idempotentHint: false, openWorldHint: true };
  }
  if (name === 'hydroweaver_job_cancel') {
    return { readOnlyHint: false, destructiveHint: true, idempotentHint: true, openWorldHint: false };
  }
  if (name === 'hydroweaver_research_create' || name === 'hydroweaver_research_cancel') {
    return { readOnlyHint: false, destructiveHint: true, idempotentHint: true, openWorldHint: false };
  }
  if (IDEMPOTENT_WRITES.has(name)) {
    return { readOnlyHint: false, destructiveHint: true, idempotentHint: true, openWorldHint: false };
  }
  return { readOnlyHint: false, destructiveHint: true, idempotentHint: false, openWorldHint: true };
}

const PATH_NOTE =
  'File paths may be absolute or relative to HYDROWEAVER_WORKDIR (the agent workspace).';
const MAX_INLINE_JSON_BYTES = 24_000;

function ok(payload: unknown): ToolResult {
  return { content: [{ type: 'text', text: JSON.stringify(payload, null, 2) }] };
}

function fail(message: string, extra?: Record<string, unknown>): ToolResult {
  return {
    isError: true,
    content: [{ type: 'text', text: JSON.stringify({ error: message, ...extra }, null, 2) }],
  };
}

function backendOrError(ctx: ToolContext): HydroWeaverBackend | ToolResult {
  let backend: HydroWeaverBackend | undefined;
  try {
    backend = resolveHydroWeaverBackend(ctx.env, ctx.homeDir);
  } catch (error) {
    return fail('HydroWeaver backend configuration is invalid.', {
      detail: error instanceof Error ? error.message : String(error),
    });
  }
  if (backend === undefined) {
    return fail('HydroWeaver Python engine or Python 3.10+ interpreter was not found.', {
      how_to_fix: [
        'Ensure Python 3.10 or newer is available on PATH or set HYDROWEAVER_PYTHON.',
        'Alternatively set HYDROWEAVER_COMMAND to a backend-compatible JSON string array.',
      ],
    });
  }
  return backend;
}

function isToolResult(value: HydroWeaverBackend | ToolResult): value is ToolResult {
  return Array.isArray((value as ToolResult).content);
}

const scalarExtra = z.union([
  z.string().max(4_000),
  z.number().finite(),
  z.boolean(),
  z.null(),
]);
const extraRecord = z.record(z.string().min(1).max(128), scalarExtra).optional();
const finiteMeasurement = z.number().finite();
const nonEmptyPath = z.string().trim().min(1).max(8_192);
const shortText = z.string().trim().min(1).max(256);
const queryFileSchema = nonEmptyPath.describe(`JSON file containing a HydroWeaver UserQuery. ${PATH_NOTE}`);

const waterQualitySchema = z
  .object({
    pH: finiteMeasurement.optional().describe('Measured pH, dimensionless.'),
    temperature_C: finiteMeasurement.optional().describe('Water temperature in °C.'),
    tds_mg_L: finiteMeasurement.nonnegative().optional().describe('Total dissolved solids in mg/L.'),
    turbidity_NTU: finiteMeasurement.nonnegative().optional(),
    arsenic_ug_L: finiteMeasurement.nonnegative().optional(),
    nitrate_mg_L: finiteMeasurement.nonnegative().optional().describe('Nitrate concentration in mg/L; declare extra.nitrate_basis as "as NO3" or "as N".'),
    fluoride_mg_L: finiteMeasurement.nonnegative().optional(),
    toc_mg_L: finiteMeasurement.nonnegative().optional(),
    iron_mg_L: finiteMeasurement.nonnegative().optional(),
    hardness_mg_L: finiteMeasurement.nonnegative().optional().describe('Hardness in mg/L; declare extra.hardness_basis as "as CaCO3".'),
    e_coli_CFU_100mL: finiteMeasurement.nonnegative().optional(),
    lead_ug_L: finiteMeasurement.nonnegative().optional(),
    boron_mg_L: finiteMeasurement.nonnegative().optional(),
    silica_mg_L: finiteMeasurement.nonnegative().optional(),
    extra: extraRecord.describe('Additional source-water measurements and reporting metadata (e.g., nitrate_basis, hardness_basis, arsenic_speciation).'),
  })
  .strict();

const treatmentTargetsSchema = z
  .object({
    tds_mg_L: finiteMeasurement.nonnegative().optional(),
    arsenic_ug_L: finiteMeasurement.nonnegative().optional(),
    nitrate_mg_L: finiteMeasurement.nonnegative().optional().describe('Nitrate effluent target in mg/L; declare extra.nitrate_basis as "as NO3" or "as N".'),
    fluoride_mg_L: finiteMeasurement.nonnegative().optional(),
    turbidity_NTU: finiteMeasurement.nonnegative().optional(),
    toc_mg_L: finiteMeasurement.nonnegative().optional(),
    hardness_mg_L: finiteMeasurement.nonnegative().optional(),
    iron_mg_L: finiteMeasurement.nonnegative().optional(),
    boron_mg_L: finiteMeasurement.nonnegative().optional(),
    e_coli: z.string().trim().max(256).optional(),
    compliance_standard: z.string().trim().max(256).optional(),
    extra: extraRecord.describe('Additional effluent targets and reporting metadata (e.g., lead_ug_L, nitrate_basis).'),
  })
  .strict();

const constraintsSchema = z
  .object({
    budget: z.string().trim().max(128).optional(),
    energy: z.string().trim().max(128).optional(),
    brine_disposal: z.boolean().optional(),
    operator_skill: z.string().trim().max(128).optional(),
    use_for_drinking: z.boolean().optional(),
    footprint_constraint: z.string().trim().max(512).optional(),
    chemical_dosing_allowed: z.boolean().optional(),
    extra: extraRecord.describe('Additional site constraints: design_flow_m3_day, min_recovery, max_sec_kwh_m3, max_lcow_usd_m3, max_footprint_m2.'),
  })
  .strict();

const QUERY_SHAPE = {
  queryFile: queryFileSchema.optional(),
  rawQuery: z.string().trim().min(1).max(8_000).optional(),
  sourceWater: z.string().trim().min(1).max(256).optional(),
  waterQuality: waterQualitySchema.optional(),
  contaminants: z.array(shortText).max(64).optional(),
  treatmentTargets: treatmentTargetsSchema.optional(),
  constraints: constraintsSchema.optional(),
  context: z.string().trim().min(1).max(8_000).optional(),
};

const waitShape = {
  wait: z
    .boolean()
    .optional()
    .describe('Wait for bounded completion. Default false returns a durable job id immediately.'),
  waitTimeoutMs: z
    .number()
    .int()
    .min(1)
    .max(3_600_000)
    .optional()
    .describe('Maximum wait when wait=true (default 600000 ms; max 3600000 ms).'),
};

const jobIdSchema = z.string().regex(/^job_\d{14}_[a-z0-9]{6,16}$/);

interface QueryBuildResult {
  readonly argv: readonly string[];
  readonly error?: ToolResult;
}

function queryArguments(args: Record<string, unknown>, workDir: string): QueryBuildResult {
  const queryKeys = [
    'rawQuery',
    'sourceWater',
    'waterQuality',
    'contaminants',
    'treatmentTargets',
    'constraints',
    'context',
  ];
  const hasInline = queryKeys.some((key) => args[key] !== undefined);
  if (typeof args['queryFile'] === 'string') {
    if (hasInline) {
      return { argv: [], error: fail('Use queryFile or inline query fields, not both.') };
    }
    return { argv: ['--query-file', resolveJobPath(args['queryFile'], workDir)] };
  }
  if (!hasInline) {
    return {
      argv: [],
      error: fail('Provide queryFile or at least one inline query field.'),
    };
  }
  const query: Record<string, unknown> = {};
  if (typeof args['rawQuery'] === 'string') query['raw_query'] = args['rawQuery'];
  if (typeof args['sourceWater'] === 'string') query['source_water'] = args['sourceWater'];
  if (args['waterQuality'] !== undefined) query['water_quality'] = args['waterQuality'];
  if (args['contaminants'] !== undefined) query['contaminants'] = args['contaminants'];
  if (args['treatmentTargets'] !== undefined) query['treatment_targets'] = args['treatmentTargets'];
  if (args['constraints'] !== undefined) query['constraints'] = args['constraints'];
  if (typeof args['context'] === 'string') query['context'] = args['context'];
  const rendered = JSON.stringify(query);
  if (Buffer.byteLength(rendered) > MAX_INLINE_JSON_BYTES) {
    return {
      argv: [],
      error: fail('Inline query is too large for a portable process invocation.', {
        how_to_fix: 'Write the UserQuery JSON to a workspace file and use queryFile.',
      }),
    };
  }
  return { argv: ['--query-json', rendered] };
}

async function immediateBackendCall(
  ctx: ToolContext,
  args: readonly string[],
  timeoutMs = 120_000,
): Promise<ToolResult> {
  const backend = backendOrError(ctx);
  if (isToolResult(backend)) return backend;
  const result = await runBackend(backend, args, {
    timeoutMs,
    cwd: jobWorkDir(ctx),
    env: ctx.env,
  });
  const report = commandReport(result);
  return result.code === 0 ? ok(report) : fail('HydroWeaver backend command failed.', report);
}

async function launchJob(
  ctx: ToolContext,
  argv: readonly string[],
  toolName: string,
  label: string,
  args: Record<string, unknown>,
): Promise<ToolResult> {
  const backend = backendOrError(ctx);
  if (isToolResult(backend)) return backend;
  const workDir = jobWorkDir(ctx);
  const command = [...backend.command, ...argv];
  const [versionProbe, identityProbe] = await Promise.all([
    runBackend(backend, ['--version'], {
      timeoutMs: 30_000,
      cwd: workDir,
      env: ctx.env,
    }),
    runBackend(backend, ['identity'], {
      timeoutMs: 30_000,
      cwd: workDir,
      env: ctx.env,
    }),
  ]);
  const backendVersion =
    versionProbe.code === 0 ? firstOutputLine(versionProbe.stdout, 1_000) : undefined;
  const scientificConfiguration = scientificConfigurationForRun(
    identityProbe.code === 0 ? parseJson(identityProbe.stdout) : undefined,
    ctx.env,
  );
  let provenance: ReturnType<typeof createEngineeringJobRequest>;
  try {
    provenance = createEngineeringJobRequest({
      toolName,
      operation: label,
      backend,
      backendVersion,
      args,
      workDir,
      scientificConfiguration,
    });
  } catch (error) {
    return fail('Could not record the engineering request.', {
      detail: error instanceof Error ? error.message : String(error),
    });
  }

  const unusableInputs = provenance.inputs.filter((input) => {
    if (input.kind === 'directory') return input.role !== 'benchmark';
    return ['missing', 'unreadable', 'other', 'symlink'].includes(input.kind);
  });
  if (unusableInputs.length > 0) {
    return fail('Input preflight failed; no job was launched.', {
      inputs: unusableInputs,
      how_to_fix:
        'Use readable regular JSON files for queries, reports, and staged knowledge. Benchmark directories must be readable. Symbolic links are rejected.',
    });
  }

  let job: JobSnapshot;
  try {
    job = startJob(ctx.jobsRoot, command, {
      workDir,
      env: ctx.env,
      label,
      provenance,
    });
  } catch (error) {
    return fail('Could not start the HydroWeaver background job.', {
      detail: error instanceof Error ? error.message : String(error),
    });
  }

  if (args['wait'] !== true) {
    return ok({
      status: 'started',
      job: publicJob(job),
      next: `Use hydroweaver_job_status(jobId="${job.id}"), hydroweaver_job_manifest(jobId="${job.id}"), and bounded hydroweaver_job_log reads. Recover it later with hydroweaver_job_list.`,
    });
  }

  const timeoutMs = typeof args['waitTimeoutMs'] === 'number' ? args['waitTimeoutMs'] : 600_000;
  const finished = await waitForJob(ctx.jobsRoot, job.id, timeoutMs);
  const finalJob = finished ?? job;
  const payload = { job: publicJob(finalJob), log_tail: jobLog(ctx.jobsRoot, job.id) ?? '' };
  if (finalJob.status === 'failed' || finalJob.status === 'cancelled') {
    return fail(`HydroWeaver job ${finalJob.status}.`, payload);
  }
  return ok(payload);
}

function publicJob(job: JobSnapshot): Record<string, unknown> {
  return {
    jobId: job.id,
    status: job.status,
    command: job.command.join(' '),
    commandArgv: job.command,
    workDir: job.workDir,
    label: job.label,
    startedAt: job.startedAt,
    finishedAt: job.finishedAt,
    durationMs: job.durationMs,
    exitCode: job.exitCode,
    signal: job.signal,
    logPath: job.logPath,
    jobDir: job.dir,
    configuredOutput: configuredJobOutput(job),
  };
}

function jobWorkDir(ctx: ToolContext): string {
  return resolveUserPath(ctx.env['HYDROWEAVER_WORKDIR'] ?? process.cwd());
}

function resolveJobPath(value: string, workDir: string): string {
  const trimmed = value.trim();
  if (trimmed === '~' || trimmed.startsWith('~/') || trimmed.startsWith('~\\')) {
    return resolveUserPath(trimmed);
  }
  return path.isAbsolute(trimmed) ? path.normalize(trimmed) : path.resolve(workDir, trimmed);
}

function outputPath(args: Record<string, unknown>, workDir: string, label: string): string {
  if (typeof args['output'] === 'string') return resolveJobPath(args['output'], workDir);
  const stamp = new Date().toISOString().replaceAll(/[-:.TZ]/g, '').slice(0, 14);
  const nonce = randomBytes(6).toString('hex');
  return path.join(workDir, 'hydroweaver-output', `${label}_${stamp}_${nonce}.json`);
}

function timestampStamp(): string {
  return new Date().toISOString().replaceAll(/[-:.TZ]/g, '').slice(0, 14);
}

function canonicalJson(value: unknown): string {
  if (value === null || typeof value !== 'object') return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map((entry) => canonicalJson(entry)).join(',')}]`;
  return `{${Object.entries(value as Record<string, unknown>)
    .filter(([, entry]) => entry !== undefined)
    .toSorted(([left], [right]) => left.localeCompare(right))
    .map(([key, entry]) => `${JSON.stringify(key)}:${canonicalJson(entry)}`)
    .join(',')}}`;
}

function writeSimulationInput(filePath: string, payload: unknown): void {
  mkdirSync(path.dirname(filePath), { recursive: true });
  writeFileSync(filePath, `${JSON.stringify(payload, null, 2)}\n`);
}

function inlineJsonArgument(value: unknown, label: string): string | ToolResult {
  const rendered = JSON.stringify(value);
  if (Buffer.byteLength(rendered) > MAX_INLINE_JSON_BYTES) {
    return fail(`${label} is too large for a portable process invocation.`, {
      how_to_fix: 'Use a workspace JSON file for larger inputs.',
    });
  }
  return rendered;
}

export const HYDROWEAVER_TOOLS: readonly HydroWeaverTool[] = [
  {
    name: 'hydroweaver_status',
    title: 'HydroWeaver status',
    description:
      'Inspect the standalone HydroWeaver scientific engine, Python runtime, built-in unit/template knowledge base, AquaDesignGym benchmark readiness, and the optional WaterTAP simulation backend.',
    inputSchema: {},
    async run(_args, ctx) {
      const backend = backendOrError(ctx);
      if (isToolResult(backend)) return backend;
      const [version, health] = await Promise.all([
        runBackend(backend, ['--version'], { timeoutMs: 30_000, cwd: jobWorkDir(ctx), env: ctx.env }),
        runBackend(backend, ['health', '--json'], {
          timeoutMs: 60_000,
          cwd: jobWorkDir(ctx),
          env: ctx.env,
        }),
      ]);
      const healthPayload = parseJson(health.stdout);
      const simulationBackend = resolveSimulationBackend(ctx.env, ctx.homeDir);
      const simulation =
        simulationBackend === undefined
          ? { available: false, backend: describeSimulationBackend(undefined), guidance: simulationSetupGuidance() }
          : { available: (await probeSimulation(simulationBackend))?.available === true, backend: describeSimulationBackend(simulationBackend) };
      return ok({
        available: version.code === 0 && health.code === 0,
        readyForRecommendation:
          isRecord(healthPayload) && healthPayload['ready_for_recommendation'] === true,
        backend: describeBackend(backend),
        version: commandReport(version),
        health: commandReport(health),
        simulation,
      });
    },
  },
  {
    name: 'hydroweaver_catalog',
    title: 'Browse HydroWeaver taxonomy',
    description:
      'List or search canonical contaminant names, treatment units, operating parameter bounds, and mechanisms from HydroWeaver’s standalone knowledge base.',
    inputSchema: {
      kind: z.enum(['all', 'contaminants', 'units']).optional(),
      search: z.string().trim().max(256).optional(),
      limit: z.number().int().min(1).max(1_000).optional(),
    },
    async run(args, ctx) {
      const argv = ['catalog'];
      if (typeof args['kind'] === 'string') argv.push('--kind', args['kind']);
      if (typeof args['search'] === 'string') argv.push('--search', args['search']);
      if (typeof args['limit'] === 'number') argv.push('--limit', String(args['limit']));
      return immediateBackendCall(ctx, argv, 60_000);
    },
  },
  {
    name: 'hydroweaver_normalize_query',
    title: 'Normalize a water-treatment query',
    description:
      'Normalize source water, contaminants, treatment targets, resource/cost constraints, and measurement units into HydroWeaver’s canonical query structure.',
    inputSchema: { ...QUERY_SHAPE },
    async run(args, ctx) {
      const workDir = jobWorkDir(ctx);
      const query = queryArguments(args, workDir);
      if (query.error !== undefined) return query.error;
      return immediateBackendCall(ctx, ['normalize', ...query.argv], 180_000);
    },
  },
  {
    name: 'hydroweaver_assess_case',
    title: 'Assess water-treatment case readiness',
    description:
      'Normalize a case into a machine-readable scientific state, identify critical blockers and decision-sensitive missing information, and return a prioritized next-information checklist.',
    inputSchema: { ...QUERY_SHAPE },
    async run(args, ctx) {
      const workDir = jobWorkDir(ctx);
      const query = queryArguments(args, workDir);
      if (query.error !== undefined) return query.error;
      return immediateBackendCall(ctx, ['assess-case', ...query.argv], 180_000);
    },
  },
  {
    name: 'hydroweaver_recommend',
    title: 'Recommend water-treatment trains',
    description:
      `Run HydroWeaver’s knowledge-informed generation, joint parameter optimization, simulation, and evidence-binding recommendation pipeline. ${PATH_NOTE}`,
    inputSchema: {
      ...QUERY_SHAPE,
      topK: z.number().int().min(1).max(10).optional(),
      output: nonEmptyPath.optional().describe('Result JSON path. A timestamped workspace path is used by default.'),
      ...waitShape,
    },
    async run(args, ctx) {
      const workDir = jobWorkDir(ctx);
      const query = queryArguments(args, workDir);
      if (query.error !== undefined) return query.error;
      const output = outputPath(args, workDir, 'recommendations');
      const topK = typeof args['topK'] === 'number' ? args['topK'] : 3;
      const argv = ['recommend', ...query.argv, '--top-k', String(topK), '--output', output];
      return launchJob(ctx, argv, 'hydroweaver_recommend', 'recommend', { ...args, output });
    },
  },
  {
    name: 'hydroweaver_retrieve_evidence',
    title: 'Retrieve HydroWeaver knowledge priors',
    description:
      `Normalize a query and retrieve unit-level mechanistic capabilities and template-level process priors from HydroWeaver’s local knowledge base. ${PATH_NOTE}`,
    inputSchema: {
      ...QUERY_SHAPE,
      output: nonEmptyPath.optional(),
      ...waitShape,
    },
    async run(args, ctx) {
      const workDir = jobWorkDir(ctx);
      const query = queryArguments(args, workDir);
      if (query.error !== undefined) return query.error;
      const output = outputPath(args, workDir, 'retrieval');
      return launchJob(
        ctx,
        ['retrieve', ...query.argv, '--output', output],
        'hydroweaver_retrieve_evidence',
        'retrieve',
        { ...args, output },
      );
    },
  },
  {
    name: 'hydroweaver_check_constraints',
    title: 'Simulate and diagnose candidate treatment trains',
    description:
      'Simulate candidate trains with HydroWeaver’s mechanistic and economic engine, check water-quality, resource, cost, and hydraulic integrity constraints, and return violation diagnoses.',
    inputSchema: {
      ...QUERY_SHAPE,
      candidateChains: z
        .array(
          z.union([
            z.array(shortText).min(1).max(64),
            z
              .object({
                chain_id: z.string().trim().min(1).max(256).optional(),
                chain: z.array(shortText).min(1).max(64),
                parameters: z.record(z.string(), z.record(z.string(), z.number().finite())).optional(),
                rationale: z.string().trim().max(4_000).optional(),
              })
              .strict(),
          ]),
        )
        .min(1)
        .max(50),
    },
    async run(args, ctx) {
      const workDir = jobWorkDir(ctx);
      const query = queryArguments(args, workDir);
      if (query.error !== undefined) return query.error;
      const candidates = inlineJsonArgument(args['candidateChains'], 'candidateChains');
      if (typeof candidates !== 'string') return candidates;
      return immediateBackendCall(
        ctx,
        ['check-constraints', ...query.argv, '--candidates-json', candidates],
        180_000,
      );
    },
  },
  {
    name: 'hydroweaver_optimize_trains',
    title: 'Jointly optimize treatment train structure and operating parameters',
    description:
      'Run HydroWeaver’s closed-loop joint optimizer: coordinates knowledge-informed generation, numerical operating-parameter optimization, process simulation, violation diagnosis, structural-vs-parametric routing, and a shared design history under water-quality, resource, and cost constraints.',
    inputSchema: {
      ...QUERY_SHAPE,
      topK: z.number().int().min(1).max(10).optional(),
      maxRounds: z.number().int().min(1).max(12).optional().describe('Maximum closed-loop rounds. Default 4.'),
      maxSimCalls: z.number().int().min(1).max(500).optional().describe('Matched simulation oracle call budget. Default 60.'),
      candidateChains: z
        .array(
          z.union([
            z.array(shortText).min(1).max(64),
            z
              .object({
                chain_id: z.string().trim().min(1).max(256).optional(),
                chain: z.array(shortText).min(1).max(64),
                parameters: z.record(z.string(), z.record(z.string(), z.number().finite())).optional(),
                rationale: z.string().trim().max(4_000).optional(),
              })
              .strict(),
          ]),
        )
        .min(1)
        .max(50)
        .optional(),
      output: nonEmptyPath.optional().describe('Optimization record JSON path. A timestamped workspace path is used by default.'),
      ...waitShape,
    },
    async run(args, ctx) {
      const workDir = jobWorkDir(ctx);
      const query = queryArguments(args, workDir);
      if (query.error !== undefined) return query.error;
      const argv = ['optimize', ...query.argv];
      if (args['candidateChains'] !== undefined) {
        const candidates = inlineJsonArgument(args['candidateChains'], 'candidateChains');
        if (typeof candidates !== 'string') return candidates;
        argv.push('--candidates-json', candidates);
      }
      const output = outputPath(args, workDir, 'optimization');
      const topK = typeof args['topK'] === 'number' ? args['topK'] : 3;
      const maxRounds = typeof args['maxRounds'] === 'number' ? args['maxRounds'] : 4;
      const maxSimCalls = typeof args['maxSimCalls'] === 'number' ? args['maxSimCalls'] : 60;
      argv.push(
        '--top-k',
        String(topK),
        '--max-rounds',
        String(maxRounds),
        '--max-sim-calls',
        String(maxSimCalls),
        '--output',
        output,
      );
      return launchJob(ctx, argv, 'hydroweaver_optimize_trains', 'optimize', { ...args, output });
    },
  },
  {
    name: 'hydroweaver_simulate_train',
    title: 'Simulate or NLP-optimize a flowsheet with WaterTAP',
    description:
      'Build the declared treatment train as a WaterTAP/IDAES flowsheet with WaterTAPCosting and solve (or NLP-optimize LCOW when optimizeDesign=true) with IPOPT. Scientific scope: the NaCl property package models water and sodium chloride salinity, so WaterTAP results describe salinity-driven hydraulics, energy, and CAPEX/OPEX/LCOW — they do NOT predict trace-contaminant rejection, and units without a WaterTAP model are reported as unsupported. An unconverged solver status means unconverged, not infeasible. Requires HYDROWEAVER_SIM_PYTHON; see docs/SIMULATION.md.',
    inputSchema: {
      queryFile: nonEmptyPath.describe(`JSON file containing the HydroWeaver UserQuery case. ${PATH_NOTE}`),
      chain: z.array(shortText).min(1).max(64).describe('Ordered treatment-unit names of the candidate train, for example ["Pumping", "Reverse Osmosis"].'),
      chainId: z.string().trim().min(1).max(256).optional().describe('Identifier recorded with the train.'),
      optimizeDesign: z.boolean().optional().describe('When true, unfixes pump pressure, membrane area, and recovery within bounds and solves a Pyomo+IPOPT NLP minimizing LCOW.'),
      waterRecovery: z.number().min(0.05).max(0.95).optional().describe('Declared water-recovery target for the last membrane; default 0.5.'),
      feedSalinityGL: z.number().nonnegative().optional().describe('Feed salinity in g/L NaCl-equivalent; declared case TDS is used when absent.'),
      designFlowM3Day: z.number().positive().optional().describe('Design feed flow in m3/day; the declared case value or a nominal 100 m3/day basis is used when absent.'),
      output: nonEmptyPath.optional().describe('Simulation result JSON path.'),
      ...waitShape,
    },
    async run(args, ctx) {
      const backend = resolveSimulationBackend(ctx.env, ctx.homeDir);
      if (backend === undefined) {
        return fail('The simulation backend is not configured.', {
          how_to_fix: simulationSetupGuidance(),
        });
      }
      const workDir = jobWorkDir(ctx);
      const casePath = resolveJobPath(String(args['queryFile']), workDir);
      let caseData: unknown;
      try {
        caseData = JSON.parse(readFileSync(casePath, 'utf8')) as unknown;
      } catch (error) {
        return fail('The simulation case file could not be read as JSON.', {
          detail: error instanceof Error ? error.message : String(error),
          queryFile: casePath,
        });
      }
      const chain = (args['chain'] as string[]).map((unit) => unit.trim()).filter((unit) => unit !== '');
      if (chain.length === 0) return fail('chain must contain at least one non-empty unit name.');
      const inputPath = path.join(workDir, 'hydroweaver-output', `simulate-input_${timestampStamp()}_${randomBytes(6).toString('hex')}.json`);
      const output = outputPath(args, workDir, 'simulation');
      const options: Record<string, unknown> = { property_package: 'NaCl', solver: 'ipopt' };
      if (typeof args['waterRecovery'] === 'number') options['water_recovery'] = args['waterRecovery'];
      if (typeof args['feedSalinityGL'] === 'number') options['feed_salinity_g_L'] = args['feedSalinityGL'];
      if (typeof args['designFlowM3Day'] === 'number') options['design_flow_m3_day'] = args['designFlowM3Day'];
      const payload = {
        schema_version: 1,
        case: caseData,
        train: {
          chain_id: typeof args['chainId'] === 'string' ? args['chainId'] : `train_${createHash('sha256').update(canonicalJson(chain)).digest('hex').slice(0, 12)}`,
          chain,
        },
        options,
      };
      writeSimulationInput(inputPath, payload);
      const selfCheck = await probeSimulation(backend);
      if (selfCheck === undefined || !selfCheck.available) {
        return fail('The simulation backend did not report WaterTAP/IDAES availability.', {
          backend: describeSimulationBackend(backend),
          detail: selfCheck?.error ?? 'self-check returned no report',
          how_to_fix: simulationSetupGuidance(),
        });
      }
      const simSubcommand = args['optimizeDesign'] === true ? 'optimize-design' : 'simulate';
      const command = [backend.python, simulationRunnerPath(ctx.env), simSubcommand, '--input', inputPath, '--output', output];
      let provenance: ReturnType<typeof createEngineeringJobRequest>;
      try {
        provenance = createEngineeringJobRequest({
          toolName: 'hydroweaver_simulate_train',
          operation: simSubcommand,
          backend: { command: [backend.python, simulationRunnerPath(ctx.env)], source: backend.source },
          backendVersion: selfCheck.versions['watertap'] ?? undefined,
          args: { queryFile: casePath, chain, chainId: payload.train.chain_id, output, options: payload.options },
          workDir,
          scientificConfiguration: {
            watertap: selfCheck.versions['watertap'] ?? null,
            idaes: selfCheck.versions['idaes-pse'] ?? null,
            pyomo: selfCheck.versions['pyomo'] ?? null,
            solver: 'ipopt',
            property_package: 'NaCl',
            supported_units: selfCheck.supportedUnits,
          },
        });
      } catch (error) {
        return fail('Could not record the simulation request.', {
          detail: error instanceof Error ? error.message : String(error),
        });
      }
      let job: JobSnapshot;
      try {
        job = startJob(ctx.jobsRoot, command, {
          workDir,
          env: ctx.env,
          label: simSubcommand,
          provenance,
        });
      } catch (error) {
        return fail('Could not start the simulation job.', {
          detail: error instanceof Error ? error.message : String(error),
        });
      }
      if (args['wait'] !== true) {
        return ok({
          status: 'started',
          job: publicJob(job),
          next: `Use hydroweaver_job_status(jobId="${job.id}") and hydroweaver_job_manifest(jobId="${job.id}") to follow the run.`,
        });
      }
      const timeoutMs = typeof args['waitTimeoutMs'] === 'number' ? args['waitTimeoutMs'] : 600_000;
      const finished = await waitForJob(ctx.jobsRoot, job.id, timeoutMs);
      const finalJob = finished ?? job;
      const payloadOut = { job: publicJob(finalJob), log_tail: jobLog(ctx.jobsRoot, job.id) ?? '' };
      if (finalJob.status === 'failed' || finalJob.status === 'cancelled') {
        return fail(`Simulation job ${finalJob.status}.`, payloadOut);
      }
      return ok(payloadOut);
    },
  },
  {
    name: 'hydroweaver_build_indexes',
    title: 'Build HydroWeaver local knowledge index',
    description:
      `Rebuild HydroWeaver’s local corpus.jsonl from built-in unit/template priors and staged local knowledge records under HYDROWEAVER_HOME. ${PATH_NOTE}`,
    inputSchema: {
      output: nonEmptyPath.optional().describe('JSON build report path.'),
      ...waitShape,
    },
    async run(args, ctx) {
      const workDir = jobWorkDir(ctx);
      const output = outputPath(args, workDir, 'index-build');
      return launchJob(
        ctx,
        ['build-indexes', '--output', output],
        'hydroweaver_build_indexes',
        'build-indexes',
        { ...args, output },
      );
    },
  },
  {
    name: 'hydroweaver_ingest_knowledge',
    title: 'Stage local HydroWeaver knowledge',
    description:
      `Stage a kb_unit or kb_case JSON record under HYDROWEAVER_HOME/ingest and optionally rebuild the local HydroWeaver knowledge corpus. ${PATH_NOTE}`,
    inputSchema: {
      kbType: z.enum(['kb_unit', 'kb_case']),
      dataFile: nonEmptyPath.describe('Regular JSON object file to stage.'),
      rebuild: z.boolean().optional(),
      output: nonEmptyPath.optional().describe('JSON ingestion report path.'),
      ...waitShape,
    },
    async run(args, ctx) {
      const workDir = jobWorkDir(ctx);
      const dataFile = resolveJobPath(String(args['dataFile']), workDir);
      const output = outputPath(args, workDir, 'ingest');
      const argv = [
        'ingest',
        '--kb-type',
        String(args['kbType']),
        '--data-file',
        dataFile,
        args['rebuild'] === false ? '--no-rebuild' : '--rebuild',
        '--output',
        output,
      ];
      return launchJob(ctx, argv, 'hydroweaver_ingest_knowledge', 'ingest', {
        ...args,
        dataFile,
        output,
      });
    },
  },
  {
    name: 'hydroweaver_gym_tasks',
    title: 'Inspect AquaDesignGym tasks and methods',
    description:
      'List standardized AquaDesignGym benchmark tasks, admissible structural/parametric actions, varying influent perturbation profiles, and registered baselines/ablations.',
    inputSchema: {},
    async run(_args, ctx) {
      return immediateBackendCall(ctx, ['gym-tasks'], 60_000);
    },
  },
  {
    name: 'hydroweaver_evaluate_gym',
    title: 'Run AquaDesignGym benchmark evaluation',
    description:
      `Run the AquaDesignGym matched-budget evaluation protocol comparing HydroWeaver against conventional optimizers, existing agent baselines, and component ablations across nominal and perturbed influent conditions (assessing feasible-design rates, LCOW, robustness, and simulation efficiency). ${PATH_NOTE}`,
    inputSchema: {
      methods: z.array(shortText).min(1).max(30).optional().describe('Subset of registered methods to evaluate; defaults to all.'),
      tasks: z.array(shortText).min(1).max(30).optional().describe('Subset of AquaDesignGym task_ids; defaults to all.'),
      perturbations: z.array(z.enum(['nominal', 'mild_shift', 'severe_shift'])).min(1).max(5).optional(),
      maxSimCalls: z.number().int().min(5).max(500).optional().describe('Matched simulation budget per episode (default 60).'),
      seed: z.number().int().min(0).max(1_000_000).optional(),
      benchmarkDir: nonEmptyPath.optional().describe('Optional local benchmark metadata directory to fingerprint in run provenance.'),
      output: nonEmptyPath.optional().describe('Evaluation JSON path.'),
      ...waitShape,
    },
    async run(args, ctx) {
      const workDir = jobWorkDir(ctx);
      const output = outputPath(args, workDir, 'aquadesigngym-evaluation');
      const argv = ['gym-eval', '--output', output];
      if (Array.isArray(args['methods'])) argv.push('--methods', args['methods'].join(','));
      if (Array.isArray(args['tasks'])) argv.push('--tasks', args['tasks'].join(','));
      if (Array.isArray(args['perturbations'])) argv.push('--perturbations', args['perturbations'].join(','));
      if (typeof args['maxSimCalls'] === 'number') argv.push('--max-sim-calls', String(args['maxSimCalls']));
      if (typeof args['seed'] === 'number') argv.push('--seed', String(args['seed']));
      const benchmarkDir =
        typeof args['benchmarkDir'] === 'string'
          ? resolveJobPath(args['benchmarkDir'], workDir)
          : undefined;
      return launchJob(ctx, argv, 'hydroweaver_evaluate_gym', 'gym-eval', {
        ...args,
        ...(benchmarkDir === undefined ? {} : { benchmarkDir }),
        output,
      });
    },
  },
  {
    name: 'hydroweaver_audit_report',
    title: 'Audit a HydroWeaver recommendation report',
    description:
      `Build a machine-readable claim-evidence ledger and structurally audit citations, declared support types, constraint feasibility, and uncertainty declarations. ${PATH_NOTE}`,
    inputSchema: {
      reportFile: nonEmptyPath.describe('HydroWeaver recommendation report JSON file to audit.'),
      output: nonEmptyPath.optional().describe('Audit JSON path.'),
      ...waitShape,
    },
    async run(args, ctx) {
      const workDir = jobWorkDir(ctx);
      const reportFile = resolveJobPath(String(args['reportFile']), workDir);
      const output = outputPath(args, workDir, 'claim-evidence-audit');
      return launchJob(
        ctx,
        ['audit-report', '--report-file', reportFile, '--output', output],
        'hydroweaver_audit_report',
        'audit-report',
        { ...args, reportFile, output },
      );
    },
  },
  {
    name: 'hydroweaver_job_list',
    title: 'List HydroWeaver jobs',
    description: 'Recover recent durable HydroWeaver jobs after a CLI, Web, or desktop session closes.',
    inputSchema: {
      status: z.enum(['running', 'succeeded', 'failed', 'cancelled', 'unknown']).optional(),
      limit: z.number().int().min(1).max(100).optional(),
    },
    async run(args, ctx) {
      const status = args['status'] as JobStatus | undefined;
      const limit = typeof args['limit'] === 'number' ? args['limit'] : 20;
      const jobs = listJobs(ctx.jobsRoot);
      const legacy = ctx.legacyJobsRoot === undefined ? [] : listJobs(ctx.legacyJobsRoot);
      const ids = new Set(jobs.map((job) => job.id));
      if (legacy.some((job) => ids.has(job.id))) {
        return fail('A job exists in both job stores; set HYDROWEAVER_JOBS_DIR to select one.');
      }
      const matching = [...jobs, ...legacy]
        .filter((job) => status === undefined || job.status === status)
        .toSorted((a, b) => b.startedAt.localeCompare(a.startedAt));
      return ok({
        jobsRoot: ctx.jobsRoot,
        total: matching.length,
        returned: Math.min(limit, matching.length),
        jobs: matching.slice(0, limit).map(publicJob),
      });
    },
  },
  {
    name: 'hydroweaver_job_status',
    title: 'HydroWeaver job status',
    description: 'Read lifecycle state, timestamps, duration, exit state, and output location for a job.',
    inputSchema: { jobId: jobIdSchema },
    async run(args, ctx) {
      const store = jobStoreForId(ctx, String(args['jobId']));
      if (store === undefined) return fail('Job exists in both job stores; set HYDROWEAVER_JOBS_DIR to select one.');
      ctx = { ...ctx, jobsRoot: store };
      const job = getJob(ctx.jobsRoot, String(args['jobId']));
      return job === undefined ? fail(`unknown job id: ${String(args['jobId'])}`) : ok(publicJob(job));
    },
  },
  {
    name: 'hydroweaver_job_manifest',
    title: 'Inspect HydroWeaver run manifest',
    description:
      'Read validated parameters, backend/runtime identity, scientific configuration, input/payload fingerprints, lifecycle state, output fingerprint, and artifact inventory.',
    inputSchema: {
      jobId: jobIdSchema,
      maxEntries: z.number().int().min(1).max(1_000).optional(),
      maxDepth: z.number().int().min(0).max(8).optional(),
    },
    async run(args, ctx) {
      const store = jobStoreForId(ctx, String(args['jobId']));
      if (store === undefined) return fail('Job exists in both job stores; set HYDROWEAVER_JOBS_DIR to select one.');
      ctx = { ...ctx, jobsRoot: store };
      const jobId = String(args['jobId']);
      const job = getJob(ctx.jobsRoot, jobId);
      if (job === undefined) return fail(`unknown job id: ${jobId}`);
      const provenance = readJobRunManifest(ctx.jobsRoot, jobId);
      if (provenance?.error !== undefined) {
        return fail('HydroWeaver run manifest is malformed.', {
          job: publicJob(job),
          detail: provenance.error,
        });
      }
      const artifacts = listJobArtifacts(ctx.jobsRoot, jobId, {
        maxEntries: typeof args['maxEntries'] === 'number' ? args['maxEntries'] : undefined,
        maxDepth: typeof args['maxDepth'] === 'number' ? args['maxDepth'] : undefined,
      });
      return ok({
        job: publicJob(job),
        engineeringRun: provenance?.manifest ?? null,
        artifacts,
        note:
          provenance?.manifest === undefined
            ? 'No run manifest is available for this legacy or non-engineering job.'
            : 'requestSha256 identifies the requested operation; result.resultSha256 identifies the captured configured output when present.',
      });
    },
  },
  {
    name: 'hydroweaver_job_log',
    title: 'Read HydroWeaver job log',
    description:
      'Read a bounded log excerpt. Omit cursor for the latest tail, use errors/events views to reduce noise, or start at cursor=0 and follow nextCursor.',
    inputSchema: {
      jobId: jobIdSchema,
      view: z.enum(['raw', 'errors', 'events']).optional(),
      cursor: z.number().int().nonnegative().optional(),
      maxBytes: z.number().int().min(1).max(1_000_000).optional(),
      maxLines: z.number().int().min(1).max(2_000).optional(),
      tailBytes: z.number().int().min(1).max(1_000_000).optional(),
    },
    async run(args, ctx) {
      const store = jobStoreForId(ctx, String(args['jobId']));
      if (store === undefined) return fail('Job exists in both job stores; set HYDROWEAVER_JOBS_DIR to select one.');
      ctx = { ...ctx, jobsRoot: store };
      const job = getJob(ctx.jobsRoot, String(args['jobId']));
      if (job === undefined) return fail(`unknown job id: ${String(args['jobId'])}`);
      if (args['maxBytes'] !== undefined && args['tailBytes'] !== undefined) {
        return fail('Use maxBytes or tailBytes, not both.');
      }
      const excerpt = readJobLog(ctx.jobsRoot, job.id, {
        view: args['view'] === 'errors' || args['view'] === 'events' ? args['view'] : 'raw',
        cursor: typeof args['cursor'] === 'number' ? args['cursor'] : undefined,
        maxBytes:
          typeof args['maxBytes'] === 'number'
            ? args['maxBytes']
            : typeof args['tailBytes'] === 'number'
              ? args['tailBytes']
              : undefined,
        maxLines: typeof args['maxLines'] === 'number' ? args['maxLines'] : undefined,
      });
      if (excerpt === undefined) return ok({ job: publicJob(job), log: '(no log yet)' });
      const { text, ...metadata } = excerpt;
      return ok({
        job: publicJob(job),
        log: text || '(no matching log lines in this excerpt)',
        excerpt: metadata,
        next:
          excerpt.nextCursor === undefined
            ? undefined
            : `Continue with hydroweaver_job_log(jobId="${job.id}", cursor=${String(excerpt.nextCursor)}).`,
      });
    },
  },
  {
    name: 'hydroweaver_job_artifacts',
    title: 'List HydroWeaver job artifacts',
    description:
      'List bounded metadata below a job’s explicit output path. Symbolic links are reported but not followed; contents are not read.',
    inputSchema: {
      jobId: jobIdSchema,
      maxEntries: z.number().int().min(1).max(1_000).optional(),
      maxDepth: z.number().int().min(0).max(8).optional(),
    },
    async run(args, ctx) {
      const store = jobStoreForId(ctx, String(args['jobId']));
      if (store === undefined) return fail('Job exists in both job stores; set HYDROWEAVER_JOBS_DIR to select one.');
      ctx = { ...ctx, jobsRoot: store };
      const listing = listJobArtifacts(ctx.jobsRoot, String(args['jobId']), {
        maxEntries: typeof args['maxEntries'] === 'number' ? args['maxEntries'] : undefined,
        maxDepth: typeof args['maxDepth'] === 'number' ? args['maxDepth'] : undefined,
      });
      if (listing === undefined) return fail(`unknown job id: ${String(args['jobId'])}`);
      return ok({
        ...listing,
        note:
          listing.root === undefined
            ? 'This job did not declare --output; inspect its bounded log for backend-reported paths.'
            : undefined,
      });
    },
  },
  {
    name: 'hydroweaver_job_cancel',
    title: 'Cancel HydroWeaver job',
    description:
      'Cancel a running job gracefully, then terminate its process tree forcefully after a bounded grace period if needed.',
    inputSchema: { jobId: jobIdSchema },
    async run(args, ctx) {
      const store = jobStoreForId(ctx, String(args['jobId']));
      if (store === undefined) return fail('Job exists in both job stores; set HYDROWEAVER_JOBS_DIR to select one.');
      ctx = { ...ctx, jobsRoot: store };
      try {
        const job = await cancelJob(ctx.jobsRoot, String(args['jobId']));
        return job === undefined ? fail(`unknown job id: ${String(args['jobId'])}`) : ok(publicJob(job));
      } catch (error) {
        return fail('Could not cancel the HydroWeaver job.', {
          jobId: String(args['jobId']),
          detail: error instanceof Error ? error.message : String(error),
        });
      }
    },
  },
  ...RESEARCH_TOOLS,
];

function jobStoreForId(ctx: ToolContext, id: string): string | undefined {
  if (ctx.legacyJobsRoot === undefined) return ctx.jobsRoot;
  const current = getJob(ctx.jobsRoot, id);
  const legacy = getJob(ctx.legacyJobsRoot, id);
  if (current !== undefined && legacy !== undefined) return undefined;
  return legacy === undefined ? ctx.jobsRoot : ctx.legacyJobsRoot;
}

const SCIENTIFIC_ENVIRONMENT_KEYS = [
  'HYDROWEAVER_PYTHON',
  'HYDROWEAVER_SIM_PYTHON',
  'HYDROWEAVER_DEFAULT_MODEL',
  'HYDROWEAVER_PLANNER_MODEL',
  'HYDROWEAVER_EXPLANATION_MODEL',
] as const;

function scientificConfigurationForRun(
  adapterIdentity: unknown,
  env: NodeJS.ProcessEnv,
): Record<string, unknown> | undefined {
  const configuration: Record<string, unknown> = {};
  if (isRecord(adapterIdentity)) {
    const adapterReported: Record<string, unknown> = {};
    copyConfigurationValues(adapterIdentity, adapterReported, [
      'adapter_version',
      'engine_mode',
      'python',
    ]);
    for (const [section, keys] of [
      ['knowledge', ['units', 'contaminants', 'templates']],
      ['optimization', ['joint_config_and_params', 'parameter_optimizer', 'diagnosis_router', 'shared_design_history']],
      ['aquadesigngym', ['tasks']],
      ['gym', ['benchmark', 'tasks', 'perturbations', 'baselines']],
      ['models', ['default_model', 'planner_model', 'explanation_model', 'llm_temperature', 'llm_max_tokens']],
      ['retrieval', ['top_k_retrieval', 'top_k_rerank', 'bm25_weight', 'embedding_weight', 'embedding_model']],
      ['planning', ['top_k_recommendations', 'max_planning_candidates', 'max_critic_iterations']],
    ] as const) {
      const source = adapterIdentity[section];
      if (!isRecord(source)) continue;
      const selected: Record<string, unknown> = {};
      copyConfigurationValues(source, selected, keys);
      if (Object.keys(selected).length > 0) adapterReported[section] = selected;
    }
    if (Object.keys(adapterReported).length > 0) {
      configuration['adapterReported'] = adapterReported;
    }
  }

  const environmentOverrides: Record<string, string> = {};
  for (const key of SCIENTIFIC_ENVIRONMENT_KEYS) {
    const value = env[key]?.trim();
    if (value !== undefined && value !== '') environmentOverrides[key] = value;
  }
  if (Object.keys(environmentOverrides).length > 0) {
    configuration['environmentOverrides'] = environmentOverrides;
  }
  return Object.keys(configuration).length > 0 ? configuration : undefined;
}

function copyConfigurationValues(
  source: Record<string, unknown>,
  target: Record<string, unknown>,
  keys: readonly string[],
): void {
  for (const key of keys) {
    const value = source[key];
    if (
      value === null ||
      typeof value === 'string' ||
      typeof value === 'boolean' ||
      (typeof value === 'number' && Number.isFinite(value))
    ) {
      target[key] = value;
    }
  }
}

function commandReport(result: RunResult): Record<string, unknown> {
  const parsed = parseJson(result.stdout);
  return {
    ok: result.code === 0,
    exitCode: result.code,
    timedOut: result.timedOut,
    truncated: result.stdoutTruncated || result.stderrTruncated,
    error: result.spawnError,
    result: parsed ?? (result.stdout.trim() || result.stderr.trim()),
    stderr: result.code === 0 ? undefined : result.stderr.trim() || undefined,
  };
}

function firstOutputLine(text: string, maxLength: number): string | undefined {
  const line = text
    .split(/\r?\n/)
    .map((value) => value.trim())
    .find((value) => value !== '');
  return line === undefined ? undefined : line.slice(0, maxLength);
}

function parseJson(text: string): unknown {
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return undefined;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}
