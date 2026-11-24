import { existsSync, readFileSync } from 'node:fs';
import path from 'node:path';
import process from 'node:process';

import { findPackageRoot, resolveUserPath } from '../paths';
import { parseCommand, runCommand, type RunResult } from './backend';

/**
 * Optional WaterTAP/IDAES/Pyomo/IPOPT simulation backend.
 *
 * The backend lives in its own Python environment; the runner is launched as a
 * subprocess with that interpreter. Nothing here imports WaterTAP into this
 * process. See docs/SIMULATION.md.
 */

export interface SimulationBackend {
  readonly python: string;
  readonly source: string;
}

export interface SimulationSelfCheck {
  readonly available: boolean;
  readonly versions: Record<string, string | null>;
  readonly python: string;
  readonly solver: { readonly name: string; readonly available: boolean; readonly detail: string };
  readonly supportedUnits: readonly string[];
  readonly error?: string;
}

export function simulationRunnerPath(env: NodeJS.ProcessEnv = process.env): string {
  const override = env['HYDROWEAVER_SIM_RUNNER']?.trim();
  if (override !== undefined && override !== '') return resolveUserPath(override);
  return path.join(findPackageRoot(), 'sim', 'runner.py');
}

const SELF_CHECK_TTL_MS = 60_000;
let selfCheckCache: { at: number; key: string; value: SimulationSelfCheck | undefined } | undefined;

export function simulationSelfCheckCacheKey(backend: SimulationBackend, runnerPath: string): string {
  return `${backend.python}|${backend.source}|${runnerPath}`;
}

export function probeSimulation(
  backend: SimulationBackend,
  timeoutMs = 120_000,
  env: NodeJS.ProcessEnv = process.env,
): Promise<SimulationSelfCheck | undefined> {
  const runnerPath = simulationRunnerPath(env);
  const key = simulationSelfCheckCacheKey(backend, runnerPath);
  const now = Date.now();
  if (selfCheckCache !== undefined && selfCheckCache.key === key && now - selfCheckCache.at < SELF_CHECK_TTL_MS) {
    return Promise.resolve(selfCheckCache.value);
  }
  return runSimulation(backend, ['self-check'], { timeoutMs, env }).then((result) => {
    if (result.code !== 0) {
      return {
        available: false,
        versions: {},
        python: backend.python,
        solver: { name: 'ipopt', available: false, detail: 'self-check failed' },
        supportedUnits: [],
        error: result.spawnError ?? (result.stderr.trim() || `self-check exited ${String(result.code)}`).slice(0, 500),
      };
    }
    return simulationSelfCheckPayload(result);
  }).then((value) => {
    selfCheckCache = { at: Date.now(), key, value };
    return value;
  });
}

export function resolveSimulationBackend(
  env: NodeJS.ProcessEnv = process.env,
  homeDir?: string,
): SimulationBackend | undefined {
  const explicit = env['HYDROWEAVER_SIM_PYTHON']?.trim();
  if (explicit !== undefined && explicit !== '') {
    return { python: resolveUserPath(explicit), source: 'HYDROWEAVER_SIM_PYTHON' };
  }
  if (homeDir !== undefined) {
    const configPath = path.join(resolveUserPath(homeDir), 'simulation.json');
    if (existsSync(configPath)) {
      try {
        const value = JSON.parse(readFileSync(configPath, 'utf8')) as { python?: unknown };
        if (typeof value.python === 'string' && value.python.trim() !== '') {
          return { python: resolveUserPath(value.python), source: configPath };
        }
      } catch {
        return undefined;
      }
    }
  }
  return undefined;
}

export function describeSimulationBackend(backend: SimulationBackend | undefined): string {
  if (backend === undefined) return 'not configured (set HYDROWEAVER_SIM_PYTHON; see docs/SIMULATION.md)';
  return `${backend.python}  (via ${backend.source})`;
}

export function runSimulation(
  backend: SimulationBackend,
  args: readonly string[],
  options: { timeoutMs?: number; cwd?: string; env?: NodeJS.ProcessEnv } = {},
): Promise<RunResult> {
  return runCommand(backend.python, [simulationRunnerPath(options.env), ...args], {
    timeoutMs: options.timeoutMs ?? 120_000,
    cwd: options.cwd,
    env: options.env,
  });
}

function simulationSelfCheckPayload(result: RunResult): SimulationSelfCheck | undefined {
  const payload = parseSimulationJson(result.stdout ?? '') ?? parseSimulationJson(result.stderr ?? '');
  if (payload === undefined) return undefined;
  const environment = asRecord(payload['environment']);
  const solver = asRecord(payload['solver']);
  const units = Array.isArray(payload['supported_units']) ? payload['supported_units'] : [];
  return {
    available: payload['available'] === true,
    versions: asVersionRecord(environment?.['versions']),
    python: typeof environment?.['python'] === 'string' ? environment['python'] : 'unknown',
    solver: {
      name: typeof solver?.['name'] === 'string' ? solver['name'] : 'ipopt',
      available: solver?.['available'] === true,
      detail: typeof solver?.['detail'] === 'string' ? solver['detail'] : '',
    },
    supportedUnits: units
      .map((unit) => (asRecord(unit)?.['unit'] as string | undefined) ?? '')
      .filter((unit) => unit !== ''),
  };
}

export function parseSimulationSelfCheck(text: string): SimulationSelfCheck | undefined {
  return simulationSelfCheckPayload({ stdout: text } as RunResult);
}

export function simulationSetupGuidance(): readonly string[] {
  return [
    'Create a Python 3.10 environment with WaterTAP: mamba create -y -n watertap python=3.10 -c conda-forge idaes-pse pyomo cyipopt, then pip install watertap.',
    'Download the solver binaries once: idaes get-extensions (provides IPOPT).',
    'Point HydroWeaver at it: export HYDROWEAVER_SIM_PYTHON=/path/to/watertap/env/bin/python, or write {"python": "..."} to ~/.hydroweaver/simulation.json.',
    'Verify with: hydroweaver doctor --probe, or hydroweaver_status.',
  ];
}

export function simulationCommandFromJson(raw: string): SimulationBackend {
  const parsed = parseCommand(raw);
  if (parsed === undefined) throw new Error('HYDROWEAVER_SIM_PYTHON is not a usable interpreter path');
  return { python: parsed[0]!, source: 'HYDROWEAVER_SIM_PYTHON' };
}

function parseSimulationJson(text: string): Record<string, unknown> | undefined {
  const trimmed = text.trim();
  if (trimmed === '') return undefined;
  const start = trimmed.indexOf('{');
  const end = trimmed.lastIndexOf('}');
  if (start < 0 || end <= start) return undefined;
  try {
    const value: unknown = JSON.parse(trimmed.slice(start, end + 1));
    return asRecord(value);
  } catch {
    return undefined;
  }
}

function asRecord(value: unknown): Record<string, unknown> | undefined {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : undefined;
}

function asVersionRecord(value: unknown): Record<string, string | null> {
  const record = asRecord(value);
  const result: Record<string, string | null> = {};
  if (record === undefined) return result;
  for (const [key, entry] of Object.entries(record)) {
    result[key] = typeof entry === 'string' ? entry : null;
  }
  return result;
}
