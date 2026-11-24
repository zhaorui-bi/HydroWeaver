import process from 'node:process';

import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import { z } from 'zod';

import { packageVersion, resolveJobStores, resolveOpenAquaHome } from '../paths';
import {
  openAquaToolAnnotations,
  HYDROWEAVER_TOOLS,
  type ToolContext,
} from '../hydroweaver/tools';

const homeDir = resolveOpenAquaHome();
const stores = resolveJobStores();

const ctx: ToolContext = {
  homeDir,
  ...stores,
  env: process.env,
};

const server = new McpServer({
  name: 'hydroweaver',
  version: packageVersion(),
});

for (const tool of HYDROWEAVER_TOOLS) {
  const inputSchema = tool.strictInput === true ? z.object(tool.inputSchema).strict() : tool.inputSchema;
  server.registerTool<Record<string, z.ZodType>, typeof inputSchema>(
    tool.name,
    {
      title: tool.title,
      description: tool.description,
      inputSchema,
      annotations: openAquaToolAnnotations(tool.name),
    },
    async (args) => tool.run(args as Record<string, unknown>, ctx),
  );
}

await server.connect(new StdioServerTransport());
