import { parseArgs } from 'node:util';

export const PROVIDER_TYPES = [
  'anthropic',
  'openai',
  'kimi',
  'google-genai',
  'openai_responses',
  'vertexai',
] as const;

export type ProviderType = (typeof PROVIDER_TYPES)[number];

export const RESEARCH_ACTIONS = ['create', 'status', 'list', 'advance', 'respond', 'cancel'] as const;
export type ResearchAction = (typeof RESEARCH_ACTIONS)[number];

export const GYM_ACTIONS = ['tasks', 'eval'] as const;
export type GymAction = (typeof GYM_ACTIONS)[number];
export const GYM_PERTURBATIONS = ['nominal', 'mild_shift', 'severe_shift'] as const;
export type GymPerturbation = (typeof GYM_PERTURBATIONS)[number];

export type CliInvocation =
  | { readonly kind: 'tui' }
  | { readonly kind: 'help' }
  | { readonly kind: 'version' }
  | { readonly kind: 'run'; readonly prompt: string }
  | { readonly kind: 'chat' }
  | {
      readonly kind: 'web';
      readonly host?: string;
      readonly port?: number;
      readonly noOpen: boolean;
      readonly homeDir?: string;
    }
  | {
      readonly kind: 'doctor';
      readonly json: boolean;
      readonly probe: boolean;
      readonly homeDir?: string;
    }
  | {
      readonly kind: 'onboard';
      readonly yes: boolean;
      readonly homeDir?: string;
      readonly hydroweaverCommand?: string;
      readonly hydroweaverPython?: string;
      readonly importFrom?: string;
      readonly provider?: string;
      readonly apiKey?: string;
      readonly apiKeyEnv?: string;
      readonly model?: string;
      readonly baseUrl?: string;
      readonly providerType?: ProviderType;
    }
  | { readonly kind: 'tools'; readonly json: boolean; readonly homeDir?: string }
  | {
      readonly kind: 'research';
      readonly action: ResearchAction;
      readonly inputFile?: string;
      readonly taskId?: string;
      readonly expectedVersion?: number;
      readonly homeDir?: string;
    }
  | { readonly kind: 'info'; readonly homeDir?: string }
  | {
      readonly kind: 'optimize';
      readonly inputFile: string;
      readonly topK?: number;
      readonly maxRounds?: number;
      readonly maxSimCalls?: number;
      readonly wait: boolean;
      readonly homeDir?: string;
    }
  | {
      readonly kind: 'gym';
      readonly action: GymAction;
      readonly methods?: readonly string[];
      readonly tasks?: readonly string[];
      readonly perturbations?: readonly GymPerturbation[];
      readonly maxSimCalls?: number;
      readonly seed?: number;
      readonly wait: boolean;
      readonly homeDir?: string;
    };

export class CliArgumentError extends Error {
  override readonly name = 'CliArgumentError';
}

type OptionDefinition = {
  readonly type: 'boolean' | 'string';
  readonly short?: string;
};

type ParsedOptions = {
  readonly values: Record<string, string | boolean | undefined>;
  readonly positionals: readonly string[];
};

const HELP_OPTION = { type: 'boolean', short: 'h' } as const;

export function parseCliInvocation(argv: readonly string[]): CliInvocation {
  const [command, ...args] = argv;
  if (command === undefined) return { kind: 'tui' };
  if (command === '--help' || command === '-h' || command === 'help') {
    assertNoArguments(args, command);
    return { kind: 'help' };
  }
  if (command === '--version' || command === '-v' || command === 'version') {
    assertNoArguments(args, command);
    return { kind: 'version' };
  }

  switch (command) {
    case 'run': {
      const parsed = parseCommandArgs(args, { help: HELP_OPTION }, true);
      if (parsed.values['help'] === true) return { kind: 'help' };
      const prompt = parsed.positionals.join(' ').trim();
      if (prompt === '') throw new CliArgumentError('run requires a prompt');
      return { kind: 'run', prompt };
    }
    case 'chat': {
      const parsed = parseCommandArgs(args, { help: HELP_OPTION });
      if (parsed.values['help'] === true) return { kind: 'help' };
      return { kind: 'chat' };
    }
    case 'web': {
      const parsed = parseCommandArgs(args, {
        help: HELP_OPTION,
        host: { type: 'string' },
        port: { type: 'string' },
        'no-open': { type: 'boolean' },
        home: { type: 'string' },
      });
      if (parsed.values['help'] === true) return { kind: 'help' };
      return {
        kind: 'web',
        host: optionalNonEmptyString(parsed.values['host'], '--host'),
        port: optionalPort(parsed.values['port']),
        noOpen: parsed.values['no-open'] === true,
        homeDir: optionalNonEmptyString(parsed.values['home'], '--home'),
      };
    }
    case 'doctor': {
      const parsed = parseCommandArgs(args, {
        help: HELP_OPTION,
        json: { type: 'boolean' },
        probe: { type: 'boolean' },
        home: { type: 'string' },
      });
      if (parsed.values['help'] === true) return { kind: 'help' };
      return {
        kind: 'doctor',
        json: parsed.values['json'] === true,
        probe: parsed.values['probe'] === true,
        homeDir: optionalNonEmptyString(parsed.values['home'], '--home'),
      };
    }
    case 'onboard': {
      const parsed = parseCommandArgs(args, {
        help: HELP_OPTION,
        yes: { type: 'boolean' },
        home: { type: 'string' },
        'hydroweaver-command': { type: 'string' },
        'hydroweaver-python': { type: 'string' },
        'import-from': { type: 'string' },
        provider: { type: 'string' },
        'api-key': { type: 'string' },
        'api-key-env': { type: 'string' },
        model: { type: 'string' },
        'base-url': { type: 'string' },
        'provider-type': { type: 'string' },
      });
      if (parsed.values['help'] === true) return { kind: 'help' };
      if (parsed.values['api-key'] !== undefined && parsed.values['api-key-env'] !== undefined) {
        throw new CliArgumentError('--api-key and --api-key-env cannot be used together');
      }
      if (
        parsed.values['hydroweaver-command'] !== undefined &&
        parsed.values['hydroweaver-python'] !== undefined
      ) {
        throw new CliArgumentError('--hydroweaver-command and --hydroweaver-python cannot be used together');
      }
      return {
        kind: 'onboard',
        yes: parsed.values['yes'] === true,
        homeDir: optionalNonEmptyString(parsed.values['home'], '--home'),
        hydroweaverCommand: optionalNonEmptyString(
          parsed.values['hydroweaver-command'],
          '--hydroweaver-command',
        ),
        hydroweaverPython: optionalNonEmptyString(
          parsed.values['hydroweaver-python'],
          '--hydroweaver-python',
        ),
        importFrom: optionalNonEmptyString(parsed.values['import-from'], '--import-from'),
        provider: optionalNonEmptyString(parsed.values['provider'], '--provider'),
        apiKey: optionalNonEmptyString(parsed.values['api-key'], '--api-key'),
        apiKeyEnv: optionalNonEmptyString(parsed.values['api-key-env'], '--api-key-env'),
        model: optionalNonEmptyString(parsed.values['model'], '--model'),
        baseUrl: optionalNonEmptyString(parsed.values['base-url'], '--base-url'),
        providerType: optionalProviderType(parsed.values['provider-type']),
      };
    }
    case 'tools': {
      const parsed = parseCommandArgs(args, {
        help: HELP_OPTION,
        json: { type: 'boolean' },
        home: { type: 'string' },
      });
      if (parsed.values['help'] === true) return { kind: 'help' };
      return {
        kind: 'tools',
        json: parsed.values['json'] === true,
        homeDir: optionalNonEmptyString(parsed.values['home'], '--home'),
      };
    }
    case 'research': {
      const [action, ...actionArgs] = args;
      if (action === '--help' || action === '-h') {
        assertNoArguments(actionArgs, 'research --help');
        return { kind: 'help' };
      }
      if (!RESEARCH_ACTIONS.some((value) => value === action)) {
        throw new CliArgumentError(`research requires an action: ${RESEARCH_ACTIONS.join(', ')}`);
      }
      const parsed = parseCommandArgs(actionArgs, {
        help: HELP_OPTION,
        input: { type: 'string' },
        id: { type: 'string' },
        'expected-version': { type: 'string' },
        home: { type: 'string' },
      });
      if (parsed.values['help'] === true) return { kind: 'help' };
      const inputFile = optionalNonEmptyString(parsed.values['input'], '--input');
      const taskId = optionalNonEmptyString(parsed.values['id'], '--id');
      const expectedVersion = optionalVersion(parsed.values['expected-version']);
      if (inputFile !== undefined && (taskId !== undefined || expectedVersion !== undefined)) {
        throw new CliArgumentError('Use --input or --id/--expected-version, not both');
      }
      if (taskId !== undefined && action !== 'status' && action !== 'advance') {
        throw new CliArgumentError('--id is supported only for research status and advance');
      }
      if (expectedVersion !== undefined && action !== 'advance') {
        throw new CliArgumentError('--expected-version is supported only for research advance');
      }
      if (inputFile === undefined && action !== 'list' && taskId === undefined) {
        throw new CliArgumentError(`research ${String(action)} requires --input FILE${action === 'status' || action === 'advance' ? ' or --id ID' : ''}`);
      }
      return {
        kind: 'research',
        action: action as ResearchAction,
        inputFile,
        taskId,
        expectedVersion,
        homeDir: optionalNonEmptyString(parsed.values['home'], '--home'),
      };
    }
    case 'optimize': {
      const parsed = parseCommandArgs(args, {
        help: HELP_OPTION,
        input: { type: 'string' },
        'top-k': { type: 'string' },
        'max-rounds': { type: 'string' },
        'max-sim-calls': { type: 'string' },
        wait: { type: 'boolean' },
        home: { type: 'string' },
      });
      if (parsed.values['help'] === true) return { kind: 'help' };
      const inputFile = optionalNonEmptyString(parsed.values['input'], '--input');
      if (inputFile === undefined) throw new CliArgumentError('optimize requires --input FILE');
      const topK = optionalBoundedInteger(parsed.values['top-k'], '--top-k', 1, 10);
      const maxRounds = optionalBoundedInteger(parsed.values['max-rounds'], '--max-rounds', 1, 12);
      const maxSimCalls = optionalBoundedInteger(parsed.values['max-sim-calls'], '--max-sim-calls', 1, 500);
      return {
        kind: 'optimize',
        inputFile,
        topK,
        maxRounds,
        maxSimCalls,
        wait: parsed.values['wait'] === true,
        homeDir: optionalNonEmptyString(parsed.values['home'], '--home'),
      };
    }
    case 'gym': {
      const [action, ...actionArgs] = args;
      if (action === '--help' || action === '-h') {
        assertNoArguments(actionArgs, 'gym --help');
        return { kind: 'help' };
      }
      if (!GYM_ACTIONS.some((value) => value === action)) {
        throw new CliArgumentError(`gym requires an action: ${GYM_ACTIONS.join(', ')}`);
      }
      if (action === 'tasks') {
        const parsed = parseCommandArgs(actionArgs, {
          help: HELP_OPTION,
          home: { type: 'string' },
        });
        if (parsed.values['help'] === true) return { kind: 'help' };
        return {
          kind: 'gym',
          action: 'tasks',
          wait: false,
          homeDir: optionalNonEmptyString(parsed.values['home'], '--home'),
        };
      }
      const parsed = parseCommandArgs(actionArgs, {
        help: HELP_OPTION,
        methods: { type: 'string' },
        tasks: { type: 'string' },
        perturbations: { type: 'string' },
        'max-sim-calls': { type: 'string' },
        seed: { type: 'string' },
        wait: { type: 'boolean' },
        home: { type: 'string' },
      });
      if (parsed.values['help'] === true) return { kind: 'help' };
      const methods = optionalCsvList(parsed.values['methods'], '--methods');
      const tasks = optionalCsvList(parsed.values['tasks'], '--tasks');
      const perturbationsRaw = optionalCsvList(parsed.values['perturbations'], '--perturbations');
      if (perturbationsRaw !== undefined) {
        for (const entry of perturbationsRaw) {
          if (!GYM_PERTURBATIONS.some((p) => p === entry)) {
            throw new CliArgumentError(
              `--perturbations entries must be drawn from: ${GYM_PERTURBATIONS.join(', ')}`,
            );
          }
        }
      }
      const maxSimCalls = optionalBoundedInteger(parsed.values['max-sim-calls'], '--max-sim-calls', 5, 500);
      const seed = optionalBoundedInteger(parsed.values['seed'], '--seed', 0, 1_000_000);
      return {
        kind: 'gym',
        action: 'eval',
        methods,
        tasks,
        perturbations: perturbationsRaw as readonly GymPerturbation[] | undefined,
        maxSimCalls,
        seed,
        wait: parsed.values['wait'] === true,
        homeDir: optionalNonEmptyString(parsed.values['home'], '--home'),
      };
    }
    case 'info': {
      const parsed = parseCommandArgs(args, {
        help: HELP_OPTION,
        home: { type: 'string' },
      });
      if (parsed.values['help'] === true) return { kind: 'help' };
      return {
        kind: 'info',
        homeDir: optionalNonEmptyString(parsed.values['home'], '--home'),
      };
    }    default:
      throw new CliArgumentError(`unknown command: ${command}`);
  }
}

function parseCommandArgs(
  args: readonly string[],
  options: Readonly<Record<string, OptionDefinition>>,
  allowPositionals = false,
): ParsedOptions {
  try {
    const parsed = parseArgs({
      args: [...args],
      options,
      allowPositionals,
      strict: true,
    });
    return {
      values: parsed.values as Record<string, string | boolean | undefined>,
      positionals: parsed.positionals,
    };
  } catch (error) {
    throw new CliArgumentError(error instanceof Error ? error.message : String(error));
  }
}

function assertNoArguments(args: readonly string[], command: string): void {
  if (args.length > 0) {
    throw new CliArgumentError(`${command} does not accept arguments`);
  }
}

function optionalNonEmptyString(
  value: string | boolean | undefined,
  flag: string,
): string | undefined {
  if (value === undefined) return undefined;
  if (typeof value !== 'string' || value.trim() === '') {
    throw new CliArgumentError(`${flag} requires a non-empty value`);
  }
  return value.trim();
}

function optionalCsvList(
  value: string | boolean | undefined,
  flag: string,
): readonly string[] | undefined {
  const raw = optionalNonEmptyString(value, flag);
  if (raw === undefined) return undefined;
  const items = raw
    .split(',')
    .map((entry) => entry.trim())
    .filter((entry) => entry !== '');
  if (items.length === 0) {
    throw new CliArgumentError(`${flag} requires at least one comma-separated entry`);
  }
  return items;
}

function optionalPort(value: string | boolean | undefined): number | undefined {
  const raw = optionalNonEmptyString(value, '--port');
  if (raw === undefined) return undefined;
  if (!/^\d+$/.test(raw)) {
    throw new CliArgumentError('--port must be an integer from 0 to 65535');
  }
  const port = Number(raw);
  if (!Number.isSafeInteger(port) || port > 65_535) {
    throw new CliArgumentError('--port must be an integer from 0 to 65535');
  }
  return port;
}

function optionalProviderType(value: string | boolean | undefined): ProviderType | undefined {
  const raw = optionalNonEmptyString(value, '--provider-type');
  if (raw === undefined) return undefined;
  if (!PROVIDER_TYPES.some((type) => type === raw)) {
    throw new CliArgumentError(
      `--provider-type must be one of: ${PROVIDER_TYPES.join(', ')}`,
    );
  }
  return raw as ProviderType;
}

function optionalBoundedInteger(
  value: string | boolean | undefined,
  flag: string,
  minimum: number,
  maximum: number,
): number | undefined {
  const raw = optionalNonEmptyString(value, flag);
  if (raw === undefined) return undefined;
  if (!/^\d+$/.test(raw) || !Number.isSafeInteger(Number(raw))) {
    throw new CliArgumentError(`${flag} must be an integer from ${String(minimum)} to ${String(maximum)}`);
  }
  const parsed = Number(raw);
  if (parsed < minimum || parsed > maximum) {
    throw new CliArgumentError(`${flag} must be an integer from ${String(minimum)} to ${String(maximum)}`);
  }
  return parsed;
}

function optionalVersion(value: string | boolean | undefined): number | undefined {  const raw = optionalNonEmptyString(value, '--expected-version');
  if (raw === undefined) return undefined;
  if (!/^\d+$/.test(raw) || !Number.isSafeInteger(Number(raw)) || Number(raw) < 1) {
    throw new CliArgumentError('--expected-version must be a positive safe integer');
  }
  return Number(raw);
}
