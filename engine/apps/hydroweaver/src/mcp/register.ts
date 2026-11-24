import { existsSync, readFileSync } from 'node:fs';
import path from 'node:path';
import process from 'node:process';

import { atomicWriteJson } from '../fs-utils';
import { findPackageRoot, monorepoRoot } from '../paths';

export const MCP_SERVER_NAME = 'hydroweaver';

export interface McpLaunch {
  readonly command: string;
  readonly args: readonly string[];
}

export function resolveMcpLaunch(): McpLaunch {
  const packageRoot = findPackageRoot();
  const built = path.join(packageRoot, 'dist', 'mcp-server.mjs');
  if (existsSync(built)) {
    return { command: process.execPath, args: [built] };
  }
  const tsxCli = path.join(monorepoRoot(), 'node_modules', 'tsx', 'dist', 'cli.mjs');
  const source = path.join(packageRoot, 'src', 'mcp', 'server.ts');
  if (existsSync(tsxCli) && existsSync(source)) {
    return { command: process.execPath, args: [tsxCli, source] };
  }
  throw new Error(
    'HydroWeaver MCP server entry not found: build the package or install the monorepo dependencies.',
  );
}

export function mcpEnvironment(
  homeDir: string,
  env: NodeJS.ProcessEnv = process.env,
): Record<string, string> {
  const result: Record<string, string> = { HYDROWEAVER_HOME: homeDir };
  copyEnvironmentValue(result, env, 'ELECTRON_RUN_AS_NODE');
  copyEnvironmentValue(result, env, 'HYDROWEAVER_COMMAND');
  copyEnvironmentValue(result, env, 'HYDROWEAVER_REPO');
  copyEnvironmentValue(result, env, 'HYDROWEAVER_PYTHON');
  copyEnvironmentValue(result, env, 'HYDROWEAVER_WORKDIR');
  copyEnvironmentValue(result, env, 'HYDROWEAVER_JOBS_DIR');
  copyEnvironmentValue(result, env, 'HYDROWEAVER_SIM_PYTHON');
  copyEnvironmentValue(result, env, 'HYDROWEAVER_OPENROUTER_MODEL');
  copyEnvironmentValue(result, env, 'HYDROWEAVER_DEFAULT_MODEL');
  copyEnvironmentValue(result, env, 'HYDROWEAVER_PLANNER_MODEL');
  copyEnvironmentValue(result, env, 'HYDROWEAVER_EXPLANATION_MODEL');
  copyEnvironmentValue(result, env, 'OPENROUTER_API_KEY');
  copyEnvironmentValue(result, env, 'HF_HOME');
  copyEnvironmentValue(result, env, 'HUGGINGFACE_HUB_CACHE');
  return result;
}

export function mcpServerConfig(
  homeDir: string,
  env: NodeJS.ProcessEnv = process.env,
): Record<string, unknown> {
  const launch = resolveMcpLaunch();
  return {
    transport: 'stdio',
    command: launch.command,
    args: [...launch.args],
    env: mcpEnvironment(homeDir, env),
  };
}

export function ensureOpenAquaMcpJson(homeDir: string): string {
  const filePath = path.join(homeDir, 'mcp.json');
  const data = readMcpConfig(filePath);
  const existingServers = data['mcpServers'];
  if (
    existingServers !== undefined &&
    (typeof existingServers !== 'object' || existingServers === null || Array.isArray(existingServers))
  ) {
    throw new Error(`${filePath}: mcpServers must be a JSON object; the file was left unchanged`);
  }
  const servers = {
    ...(existingServers as Record<string, unknown> | undefined),
    [MCP_SERVER_NAME]: mcpServerConfig(homeDir),
  };
  atomicWriteJson(filePath, { ...data, mcpServers: servers });
  return filePath;
}

function readMcpConfig(filePath: string): Record<string, unknown> {
  if (!existsSync(filePath)) return {};
  let parsed: unknown;
  try {
    parsed = JSON.parse(readFileSync(filePath, 'utf8')) as unknown;
  } catch (error) {
    throw new Error(
      `${filePath} is not valid JSON; the file was left unchanged: ${
        error instanceof Error ? error.message : String(error)
      }`,
      { cause: error },
    );
  }
  if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
    throw new Error(`${filePath} must contain a JSON object; the file was left unchanged`);
  }
  return parsed as Record<string, unknown>;
}

function copyEnvironmentValue(
  target: Record<string, string>,
  source: NodeJS.ProcessEnv,
  name: string,
): void {
  const value = source[name];
  if (value !== undefined) target[name] = value;
}
