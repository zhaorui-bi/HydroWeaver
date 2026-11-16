import { existsSync, lstatSync, readFileSync, realpathSync } from 'node:fs';
import { homedir } from 'node:os';
import path from 'node:path';
import process from 'node:process';

declare const __OPENAQUA_VERSION__: string | undefined;

let cachedPackageRoot: string | undefined;
let cachedPackageVersion: string | undefined;

export function resolveUserPath(value: string): string {
  const trimmed = value.trim();
  if (trimmed === '~') return homedir();
  if (trimmed.startsWith('~/') || trimmed.startsWith('~\\')) {
    return path.resolve(homedir(), trimmed.slice(2));
  }
  return path.resolve(trimmed);
}

export function resolveOpenAquaHome(env: NodeJS.ProcessEnv = process.env): string {
  const explicit = env['OPENAQUA_HOME']?.trim();
  return explicit === undefined || explicit === ''
    ? path.join(homedir(), '.openaqua')
    : resolveUserPath(explicit);
}

export function resolveJobStores(
  env: NodeJS.ProcessEnv = process.env,
  cwd: string = process.cwd(),
): { jobsRoot: string; legacyJobsRoot?: string } {
  if (env['OPENAQUA_JOBS_DIR'] !== undefined) {
    return { jobsRoot: resolveUserPath(env['OPENAQUA_JOBS_DIR']) };
  }
  const workDir = resolveUserPath(env['OPENAQUA_WORKDIR'] ?? cwd);
  const jobsRoot = path.join(workDir, 'openaqua-jobs');
  const legacyJobsRoot = path.join(path.resolve(cwd), 'openaqua-jobs');
  let sameStore = false;
  try { sameStore = realpathSync(jobsRoot) === realpathSync(legacyJobsRoot); } catch { /* One or both stores do not exist yet. */ }
  if (sameStore) {
    if (lstatSync(jobsRoot).isSymbolicLink() || lstatSync(legacyJobsRoot).isSymbolicLink()) {
      throw new Error('Job store must not be a symbolic link; select its real directory with OPENAQUA_JOBS_DIR.');
    }
    return { jobsRoot: legacyJobsRoot };
  }
  let sameDirectory = workDir === path.resolve(cwd);
  if (!sameDirectory) {
    try { sameDirectory = realpathSync(workDir) === realpathSync(cwd); } catch { /* Preserve both paths when either does not exist yet. */ }
  }
  return { jobsRoot, legacyJobsRoot: sameDirectory ? undefined : legacyJobsRoot };
}

export function findPackageRoot(): string {
  if (cachedPackageRoot !== undefined) return cachedPackageRoot;
  let dir = import.meta.dirname;
  for (;;) {
    const manifest = path.join(dir, 'package.json');
    if (existsSync(manifest)) {
      try {
        const pkg = JSON.parse(readFileSync(manifest, 'utf8')) as { name?: string };
        if (pkg.name === 'openaqua-harness') {
          cachedPackageRoot = dir;
          return dir;
        }
      } catch {
        // keep walking
      }
    }
    if (
      existsSync(path.join(dir, 'dist', 'mcp-server.mjs')) &&
      existsSync(path.join(dir, 'skills'))
    ) {
      cachedPackageRoot = dir;
      return dir;
    }
    const parent = path.dirname(dir);
    if (parent === dir) break;
    dir = parent;
  }
  throw new Error('could not locate the openaqua-harness package root');
}

export function packageVersion(): string {
  if (cachedPackageVersion !== undefined) return cachedPackageVersion;
  try {
    const manifest = path.join(findPackageRoot(), 'package.json');
    cachedPackageVersion = (JSON.parse(readFileSync(manifest, 'utf8')) as { version: string }).version;
  } catch {
    cachedPackageVersion =
      typeof __OPENAQUA_VERSION__ === 'string' ? __OPENAQUA_VERSION__ : '0.0.0-unknown';
  }
  return cachedPackageVersion;
}

export function monorepoRoot(): string {
  return path.resolve(findPackageRoot(), '..', '..');
}

export function defaultWebAssetsDir(): string {
  const branded = path.join(findPackageRoot(), 'web-ui');
  if (existsSync(path.join(branded, 'index.html'))) return branded;
  return path.join(monorepoRoot(), 'apps', 'kimi-code', 'dist-web');
}

export function skillsDir(): string {
  return path.join(findPackageRoot(), 'skills');
}
