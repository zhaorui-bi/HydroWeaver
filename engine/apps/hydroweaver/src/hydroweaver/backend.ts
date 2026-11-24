import { spawn, spawnSync } from 'node:child_process';
import { accessSync, constants, existsSync, readFileSync, statSync } from 'node:fs';
import { homedir } from 'node:os';
import path from 'node:path';
import process from 'node:process';

import { findPackageRoot } from '../paths';

export interface HydroWeaverBackend {
  readonly command: readonly string[];
  readonly source: string;
}

export interface HydroWeaverBackendFileConfig {
  readonly command?: readonly string[];
  readonly python?: string;
}

export interface RunResult {
  readonly code: number | null;
  readonly signal: NodeJS.Signals | null;
  readonly stdout: string;
  readonly stderr: string;
  readonly stdoutTruncated: boolean;
  readonly stderrTruncated: boolean;
  readonly timedOut: boolean;
  readonly spawnError?: string;
}

export interface RunCommandOptions {
  readonly cwd?: string;
  readonly env?: NodeJS.ProcessEnv;
  readonly timeoutMs?: number;
  readonly maxOutputBytes?: number;
}

export class HydroWeaverBackendConfigError extends Error {
  override readonly name = 'HydroWeaverBackendConfigError';
}

const DEFAULT_TIMEOUT_MS = 120_000;
const DEFAULT_MAX_OUTPUT_BYTES = 1_000_000;
const FORCE_KILL_DELAY_MS = 2_000;
const OUTPUT_TRUNCATION_PREFIX = '… (truncated; showing the last output bytes)\n';

export function resolveHydroWeaverBackend(
  env: NodeJS.ProcessEnv = process.env,
  homeDir?: string,
): HydroWeaverBackend | undefined {
  const fromEnv = parseCommand(env['HYDROWEAVER_COMMAND']);
  if (fromEnv !== undefined) return { command: fromEnv, source: 'HYDROWEAVER_COMMAND' };

  if (homeDir !== undefined) {
    const configPath = path.join(homeDir, 'hydroweaver.json');
    const config = readBackendConfig(configPath);
    if (config?.command !== undefined) return { command: config.command, source: configPath };
    if (config?.python !== undefined) {
      const cmd = pythonEngineCommand(config.python, env);
      if (cmd !== undefined) return { command: cmd, source: configPath };
    }
  }

  const explicitPython = env['HYDROWEAVER_PYTHON']?.trim();
  if (explicitPython !== undefined && explicitPython !== '') {
    const cmd = pythonEngineCommand(explicitPython, env);
    if (cmd !== undefined) {
      return { command: cmd, source: `HYDROWEAVER_PYTHON:${explicitPython}` };
    }
  }

  return builtInEngineBackend(env);
}

export function backendAdapterPath(): string {
  return path.join(findPackageRoot(), 'backend', 'hydroweaver_cli.py');
}

export function pythonEngineCommand(
  pythonExecutable: string,
  env: NodeJS.ProcessEnv = process.env,
): readonly string[] | undefined {
  const adapter = backendAdapterPath();
  if (!existsSync(adapter)) return undefined;
  const resolved = findOnPath(expandHome(pythonExecutable), env) ?? findOnPath(pythonExecutable, env);
  if (resolved === undefined) return undefined;
  return [resolved, adapter];
}

function builtInEngineBackend(env: NodeJS.ProcessEnv): HydroWeaverBackend | undefined {
  const adapter = backendAdapterPath();
  if (!existsSync(adapter)) return undefined;
  const python = resolveSystemPython(env);
  if (python === undefined) return undefined;
  return { command: [...python, adapter], source: 'bundled-hydroweaver-engine' };
}

function resolveSystemPython(env: NodeJS.ProcessEnv): readonly string[] | undefined {
  const python3 = findOnPath('python3', env);
  if (python3 !== undefined) return [python3];
  const python = findOnPath('python', env);
  if (python !== undefined) return [python];
  if (process.platform === 'win32') {
    const launcher = findOnPath('py', env);
    if (launcher !== undefined) return [launcher, '-3'];
  }
  return undefined;
}

export function parseCommand(raw: string | undefined): readonly string[] | undefined {
  if (raw === undefined || raw.trim() === '') return undefined;
  const trimmed = raw.trim();
  if (trimmed.startsWith('[')) {
    let parsed: unknown;
    try {
      parsed = JSON.parse(trimmed) as unknown;
    } catch (error) {
      throw new HydroWeaverBackendConfigError(
        `HYDROWEAVER_COMMAND must be a valid JSON string array: ${errorMessage(error)}`,
      );
    }
    return validateCommand(parsed, 'HYDROWEAVER_COMMAND');
  }
  return validateCommand(splitCommandLine(trimmed), 'HYDROWEAVER_COMMAND');
}

export function readBackendConfig(filePath: string): HydroWeaverBackendFileConfig | undefined {
  if (!existsSync(filePath)) return undefined;
  let data: unknown;
  try {
    data = JSON.parse(readFileSync(filePath, 'utf8')) as unknown;
  } catch (error) {
    throw new HydroWeaverBackendConfigError(
      `Cannot parse ${filePath}; the file was left unchanged: ${errorMessage(error)}`,
    );
  }
  if (typeof data !== 'object' || data === null || Array.isArray(data)) {
    throw new HydroWeaverBackendConfigError(`${filePath} must contain a JSON object`);
  }
  const record = data as Record<string, unknown>;
  const command =
    record['command'] === undefined
      ? undefined
      : validateCommand(record['command'], `${filePath}: command`);
  const rawPython = record['python'];
  if (rawPython !== undefined && (typeof rawPython !== 'string' || rawPython.trim() === '')) {
    throw new HydroWeaverBackendConfigError(`${filePath}: python must be a non-empty string`);
  }
  return { command, python: typeof rawPython === 'string' ? rawPython.trim() : undefined };
}

export function findOnPath(
  name: string,
  env: NodeJS.ProcessEnv = process.env,
): string | undefined {
  if (name.includes('/') || name.includes('\\')) {
    const candidate = path.resolve(name);
    return isExecutableFile(candidate) ? candidate : undefined;
  }
  const pathValue = env['PATH'] ?? (process.platform === 'win32' ? env['Path'] : undefined) ?? '';
  const extensions = executableExtensions(name, env);
  for (const rawDir of pathValue.split(path.delimiter)) {
    const dir = stripMatchingQuotes(rawDir.trim());
    if (dir === '') continue;
    for (const extension of extensions) {
      const candidate = path.resolve(dir, `${name}${extension}`);
      if (isExecutableFile(candidate)) return candidate;
    }
  }
  return undefined;
}

export function describeBackend(backend: HydroWeaverBackend | undefined): string {
  if (backend === undefined) return 'not found';
  return `${backend.command.join(' ')}  (via ${backend.source})`;
}

export function runBackend(
  backend: HydroWeaverBackend,
  args: readonly string[],
  options: RunCommandOptions = {},
): Promise<RunResult> {
  const [command, ...prefixArgs] = backend.command;
  if (command === undefined) return Promise.resolve(spawnFailure('HydroWeaver backend command is empty'));
  return runCommand(command, [...prefixArgs, ...args], options);
}

export function runCommand(
  command: string,
  args: readonly string[],
  options: RunCommandOptions = {},
): Promise<RunResult> {
  const timeoutMs = positiveInteger(options.timeoutMs, DEFAULT_TIMEOUT_MS);
  const maxOutputBytes = positiveInteger(options.maxOutputBytes, DEFAULT_MAX_OUTPUT_BYTES);

  return new Promise((resolve) => {
    let stdout: Buffer = Buffer.alloc(0);
    let stderr: Buffer = Buffer.alloc(0);
    let stdoutTruncated = false;
    let stderrTruncated = false;
    let timedOut = false;
    let settled = false;
    let timeout: ReturnType<typeof setTimeout> | undefined;
    let forceKillTimeout: ReturnType<typeof setTimeout> | undefined;

    const finish = (
      code: number | null,
      signal: NodeJS.Signals | null,
      spawnError?: string,
    ): void => {
      if (settled) return;
      settled = true;
      if (timeout !== undefined) clearTimeout(timeout);
      if (forceKillTimeout !== undefined) clearTimeout(forceKillTimeout);
      // oxlint-disable-next-line promise/no-multiple-resolved -- guarded by `settled` above.
      resolve({
        code,
        signal,
        stdout: formatOutput(stdout, stdoutTruncated),
        stderr: formatOutput(stderr, stderrTruncated),
        stdoutTruncated,
        stderrTruncated,
        timedOut,
        spawnError,
      });
    };

    let child;
    try {
      child = spawn(command, [...args], {
        cwd: options.cwd,
        env: options.env ?? process.env,
        detached: process.platform !== 'win32',
        stdio: ['ignore', 'pipe', 'pipe'],
      });
    } catch (error) {
      finish(null, null, errorMessage(error));
      return;
    }

    child.stdout.on('data', (chunk: Buffer) => {
      const captured = appendTail(stdout, chunk, maxOutputBytes);
      stdout = captured.buffer;
      stdoutTruncated ||= captured.truncated;
    });
    child.stderr.on('data', (chunk: Buffer) => {
      const captured = appendTail(stderr, chunk, maxOutputBytes);
      stderr = captured.buffer;
      stderrTruncated ||= captured.truncated;
    });
    child.on('error', (error) => {
      finish(null, null, error.message);
    });
    child.on('close', (code, signal) => {
      finish(code, signal);
    });

    timeout = setTimeout(() => {
      timedOut = true;
      terminateProcess(child.pid, 'SIGTERM', () => child.kill('SIGTERM'));
      forceKillTimeout = setTimeout(() => {
        terminateProcess(child.pid, 'SIGKILL', () => child.kill('SIGKILL'));
      }, FORCE_KILL_DELAY_MS);
      forceKillTimeout.unref();
    }, timeoutMs);
    timeout.unref();
  });
}

export function probeBackend(backend: HydroWeaverBackend, timeoutMs = 120_000): Promise<RunResult> {
  return runBackend(backend, ['health', '--json'], { timeoutMs });
}

export function backendRecommendationReady(result: RunResult): boolean | undefined {
  const payload = parseObject(result.stdout) ?? parseObject(result.stderr);
  return typeof payload?.['ready_for_recommendation'] === 'boolean'
    ? payload['ready_for_recommendation']
    : undefined;
}

export function summarizeBackendHealth(result: RunResult): string {
  const payload = parseObject(result.stdout) ?? parseObject(result.stderr);
  if (payload === undefined) {
    return result.spawnError ?? (firstOutputLine(result.stderr || result.stdout) || 'no health output');
  }
  if (typeof payload['error'] === 'string') {
    const detail = typeof payload['detail'] === 'string' ? `: ${payload['detail']}` : '';
    return `${payload['error']}${detail}`;
  }

  const details: string[] = [];
  const kb = parseObject(payload['knowledge_base']);
  if (kb !== undefined) {
    const units = typeof kb['units'] === 'number' ? kb['units'] : '?';
    const templates = typeof kb['templates'] === 'number' ? kb['templates'] : '?';
    const chunks = typeof kb['chunk_count'] === 'number' ? kb['chunk_count'] : '?';
    details.push(`KB ready (${String(units)} units, ${String(templates)} templates, ${String(chunks)} chunks)`);
  }
  const gym = parseObject(payload['aquadesigngym']);
  if (gym !== undefined) {
    const tasks = typeof gym['tasks'] === 'number' ? gym['tasks'] : '?';
    const methods = typeof gym['methods'] === 'number' ? gym['methods'] : '?';
    details.push(`AquaDesignGym ready (${String(tasks)} tasks, ${String(methods)} methods)`);
  }
  return details.join('; ') || `health ok=${String(payload['ok'])}`;
}

function validateCommand(value: unknown, source: string): readonly string[] {
  if (
    !Array.isArray(value) ||
    value.length === 0 ||
    !value.every((part) => typeof part === 'string' && part.trim() !== '')
  ) {
    throw new HydroWeaverBackendConfigError(`${source} must be a non-empty array of non-empty strings`);
  }
  return value.map((part) => (part as string).trim());
}

function parseObject(value: unknown): Record<string, unknown> | undefined {
  if (typeof value === 'string') {
    try {
      return parseObject(JSON.parse(value) as unknown);
    } catch {
      return undefined;
    }
  }
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : undefined;
}

function firstOutputLine(text: string): string {
  return text.trim().split('\n')[0] ?? '';
}

function splitCommandLine(raw: string): string[] {
  const parts: string[] = [];
  let current = '';
  let quote: 'single' | 'double' | undefined;
  for (let index = 0; index < raw.length; index++) {
    const character = raw[index]!;
    if (quote === 'single') {
      if (character === "'") quote = undefined;
      else current += character;
      continue;
    }
    if (quote === 'double') {
      if (character === '"') quote = undefined;
      else if (character === '\\' && raw[index + 1] === '"') {
        current += '"';
        index++;
      } else current += character;
      continue;
    }
    if (character === "'") quote = 'single';
    else if (character === '"') quote = 'double';
    else if (/\s/.test(character)) {
      if (current !== '') {
        parts.push(current);
        current = '';
      }
    } else current += character;
  }
  if (quote !== undefined) {
    throw new HydroWeaverBackendConfigError('HYDROWEAVER_COMMAND contains an unterminated quote');
  }
  if (current !== '') parts.push(current);
  return parts;
}

function executableExtensions(name: string, env: NodeJS.ProcessEnv): readonly string[] {
  if (process.platform !== 'win32') return [''];
  const pathExt = env['PATHEXT'] ?? '.COM;.EXE;.BAT;.CMD';
  const extensions = pathExt
    .split(';')
    .map((extension) => extension.trim())
    .filter((extension) => extension !== '');
  const lowerName = name.toLowerCase();
  return extensions.some((extension) => lowerName.endsWith(extension.toLowerCase()))
    ? ['', ...extensions]
    : extensions;
}

function isExecutableFile(candidate: string): boolean {
  try {
    if (!statSync(candidate).isFile()) return false;
    if (process.platform !== 'win32') accessSync(candidate, constants.X_OK);
    return true;
  } catch {
    return false;
  }
}

function stripMatchingQuotes(value: string): string {
  if (value.length >= 2 && value.startsWith('"') && value.endsWith('"')) return value.slice(1, -1);
  return value;
}

function expandHome(value: string): string {
  if (value === '~') return homedir();
  if (value.startsWith('~/') || value.startsWith('~\\')) return path.join(homedir(), value.slice(2));
  return path.resolve(value);
}

function appendTail(
  current: Buffer,
  chunk: Buffer,
  maxBytes: number,
): { readonly buffer: Buffer; readonly truncated: boolean } {
  const combined = Buffer.concat([current, chunk]);
  if (combined.length <= maxBytes) return { buffer: combined, truncated: false };
  return { buffer: combined.subarray(combined.length - maxBytes), truncated: true };
}

function formatOutput(buffer: Buffer, truncated: boolean): string {
  const text = buffer.toString('utf8');
  return truncated ? OUTPUT_TRUNCATION_PREFIX + text : text;
}

function terminateProcess(
  pid: number | undefined,
  signal: NodeJS.Signals,
  fallback: () => boolean,
): void {
  if (pid !== undefined && process.platform === 'win32') {
    const args = ['/pid', String(pid), '/t'];
    if (signal === 'SIGKILL') args.push('/f');
    const result = spawnSync('taskkill', args, { stdio: 'ignore' });
    if (result.status === 0 || signal !== 'SIGKILL') return;
  } else if (pid !== undefined) {
    try {
      process.kill(-pid, signal);
      return;
    } catch {}
  }
  try {
    fallback();
  } catch {}
}

function positiveInteger(value: number | undefined, fallback: number): number {
  return value !== undefined && Number.isSafeInteger(value) && value > 0 ? value : fallback;
}

function spawnFailure(message: string): RunResult {
  return {
    code: null,
    signal: null,
    stdout: '',
    stderr: '',
    stdoutTruncated: false,
    stderrTruncated: false,
    timedOut: false,
    spawnError: message,
  };
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
