export interface InteractiveHostBrand {
  readonly id: 'kimi-code' | 'hydroweaver';
  readonly productName: string;
  readonly assistantName: string;
  readonly commandName: string;
  readonly processName: string;
  readonly logo: readonly [string, string];
  readonly welcomeArt?: readonly string[];
  readonly welcomeTagline?: string;
  readonly welcomeDescription?: string;
  readonly welcomeSpecialties?: string;
  readonly transcriptMarker: string;
  readonly promptSymbol: string;
  readonly promptLabel?: string;
  readonly modelSetupHint: string;
  readonly modelMissingHint: string;
  readonly showRemoteBanners: boolean;
  readonly hiddenCommands: readonly string[];
  readonly identity?: {
    readonly productName: string;
    readonly platform: string;
    readonly uiMode: string;
  };
  readonly version?: string;
}

const KIMI_CODE_BRAND: InteractiveHostBrand = {
  id: 'kimi-code',
  productName: 'Kimi Code',
  assistantName: 'Kimi',
  commandName: 'kimi',
  processName: 'kimi-code',
  logo: ['▐█▛█▛█▌', '▐█████▌'],
  transcriptMarker: '● ',
  promptSymbol: '>',
  modelSetupHint: 'Run /login or /provider to get started.',
  modelMissingHint: 'not set, run /login or /provider',
  showRemoteBanners: true,
  hiddenCommands: [],
};

function openAquaVersion(env: NodeJS.ProcessEnv): string | undefined {
  const value = env['HYDROWEAVER_VERSION']?.trim();
  if (value === undefined || value.length === 0 || value.length > 64) return undefined;
  return /^[0-9A-Za-z.+-]+$/.test(value) ? value : undefined;
}

export function resolveInteractiveHostBrand(
  env: NodeJS.ProcessEnv = process.env,
): InteractiveHostBrand {
  if (env['HYDROWEAVER_TUI'] !== '1') return KIMI_CODE_BRAND;
  return {
    id: 'hydroweaver',
    productName: 'HydroWeaver',
    assistantName: 'HydroWeaver',
    commandName: 'hydroweaver',
    processName: 'hydroweaver',
    logo: ['<~AQUA~>', ' WEAVER'],
    welcomeArt: [
      '   ____                   ___',
      '  / __ \\____  ___  ____  /   | ____ ___  ______ _',
      ' / / / / __ \\/ _ \\/ __ \\/ /| |/ __ `/ / / / __ `/',
      '/ /_/ / /_/ /  __/ / / / ___ / /_/ / /_/ / /_/ /',
      '\\____/ .___/\\___/_/ /_/_/  |_\\__, /\\__,_/\\__,_/',
      '    /_/                       /_/',
      '       <====[ H Y D R O W E A V E R ]====>',
    ],
    welcomeTagline: 'FROM PLAUSIBLE TO FEASIBLE',
    welcomeDescription: 'Closed-loop optimization for water-treatment train design',
    welcomeSpecialties: 'PARSE  ::  RETRIEVE  ::  PLAN  ::  CRITIQUE  ::  OPTIMIZE',
    transcriptMarker: '› ',
    promptSymbol: '›',
    promptLabel: 'WATER QUERY',
    modelSetupHint: 'Run /provider to configure a model.',
    modelMissingHint: 'not set, run /provider',
    showRemoteBanners: false,
    hiddenCommands: ['desktop', 'feedback', 'login', 'plugins', 'remote-control', 'web'],
    identity: {
      productName: 'hydroweaver',
      platform: 'hydroweaver',
      uiMode: 'hydroweaver',
    },
    version: openAquaVersion(env),
  };
}

export const INTERACTIVE_HOST = resolveInteractiveHostBrand();

export function isInteractiveHostCommandEnabled(commandName: string): boolean {
  return !INTERACTIVE_HOST.hiddenCommands.includes(commandName);
}
