import process from 'node:process';

import { resolveHydroWeaverHome } from './harness';
import { resolveUserPath } from './paths';
import { describeBackend, resolveHydroWeaverBackend } from './hydroweaver/backend';
import { hydroWeaverToolAnnotations, HYDROWEAVER_TOOLS } from './hydroweaver/tools';

export function runToolsList(json: boolean, homeDir: string = resolveHydroWeaverHome()): void {
  const resolvedHomeDir = resolveUserPath(homeDir);
  let backend: ReturnType<typeof resolveHydroWeaverBackend>;
  let backendError: string | undefined;
  try {
    backend = resolveHydroWeaverBackend(process.env, resolvedHomeDir);
  } catch (error) {
    backendError = error instanceof Error ? error.message : String(error);
  }
  if (json) {
    process.stdout.write(
      JSON.stringify(
        {
          backend: backend === undefined ? null : describeBackend(backend),
          backendError,
          tools: HYDROWEAVER_TOOLS.map((t) => ({
            name: t.name,
            title: t.title,
            description: t.description,
            parameters: Object.keys(t.inputSchema),
            annotations: hydroWeaverToolAnnotations(t.name),
          })),
        },
        null,
        2,
      ) + '\n',
    );
    return;
  }
  process.stdout.write(
    `HydroWeaver tools (backend: ${
      backendError === undefined ? describeBackend(backend) : `invalid configuration — ${backendError}`
    })\n\n`,
  );
  for (const tool of HYDROWEAVER_TOOLS) {
    const params = Object.keys(tool.inputSchema).join(', ');
    process.stdout.write(`  ${tool.name}\n    ${tool.title}\n    params: ${params || '(none)'}\n\n`);
  }
}
