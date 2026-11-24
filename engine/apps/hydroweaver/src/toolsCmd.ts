import process from 'node:process';

import { resolveOpenAquaHome } from './harness';
import { resolveUserPath } from './paths';
import { describeBackend, resolveOpenAquaBackend } from './hydroweaver/backend';
import { openAquaToolAnnotations, HYDROWEAVER_TOOLS } from './hydroweaver/tools';

export function runToolsList(json: boolean, homeDir: string = resolveOpenAquaHome()): void {
  const resolvedHomeDir = resolveUserPath(homeDir);
  let backend: ReturnType<typeof resolveOpenAquaBackend>;
  let backendError: string | undefined;
  try {
    backend = resolveOpenAquaBackend(process.env, resolvedHomeDir);
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
            annotations: openAquaToolAnnotations(t.name),
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
