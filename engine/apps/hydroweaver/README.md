# HydroWeaver package

`hydroweaver` is the product host for HydroWeaver. It starts the Kimi
Code agent engine through `@moonshot-ai/kimi-code-sdk` and
`@moonshot-ai/kap-server`, then exposes the external OpenAqua Python checkout as
an MCP stdio server.

The package provides onboarding, diagnostics, a bundled Python adapter, durable
jobs, request provenance, session-level tool registration, a branded Web UI,
and the executables used by the desktop application.

Candidate `0.2.0-beta.1` retains the `0.1.0-beta.1` compatibility baseline:
OpenAqua commit `0e39908` and Hugging Face dataset revision
`cc2d3c620e8ada7c62fa922cf3a827d8b42889e3`.

## Commands

| Command | Behavior |
| --- | --- |
| `hydroweaver run "<prompt>"` | Create a session, attach OpenAqua tools, stream one response, and exit. |
| `hydroweaver chat` | Lightweight persistent REPL. |
| `hydroweaver web [options]` | Start kap-server and the branded local Web UI. |
| `hydroweaver doctor [--json] [--probe]` | Check Node, storage, model configuration, backend health, MCP, Web assets, and skills. |
| `hydroweaver onboard [options]` | Configure the home directory, API model provider, OpenAqua repository/command, MCP, and skills. |
| `hydroweaver tools [--json]` | List all 25 tool schemas and annotations. |
| `hydroweaver optimize [options]` | Run the closed-loop optimization directly: `[--input FILE] [--top-k N] [--max-rounds N] [--wait]`. |
| `hydroweaver info` / `--version` | Print version and resolved paths. |

## Development

From `engine/`:

```bash
pnpm install --frozen-lockfile
pnpm --filter hydroweaver run typecheck
pnpm --filter hydroweaver run test
pnpm --filter hydroweaver run build
```

The build produces `dist/cli.mjs`, `dist/mcp-server.mjs`, and
`dist/job-runner.mjs`; the shared worker build adds `dist/search-worker.mjs`.

## Environment variables

- `HYDROWEAVER_HOME` — HydroWeaver configuration; defaults to `~/.hydroweaver`.
- `HYDROWEAVER_COMMAND` — adapter-compatible backend command.
- `HYDROWEAVER_REPO` — OpenAqua repository checkout.
- `HYDROWEAVER_PYTHON` — optional Python interpreter for that checkout.
- `HYDROWEAVER_WORKDIR` / `HYDROWEAVER_JOBS_DIR` — workspace and durable-job roots.
- `HYDROWEAVER_WEB_ASSETS_DIR` — branded Web UI override.
- `OPENROUTER_API_KEY` / `HYDROWEAVER_OPENROUTER_MODEL` — optional OpenAqua LLM configuration; use `HYDROWEAVER_DEFAULT_MODEL`, `HYDROWEAVER_PLANNER_MODEL`, and `HYDROWEAVER_EXPLANATION_MODEL` for per-stage overrides.

## Source map

```text
backend/hydroweaver_cli.py       stable adapter over the upstream Python project
src/cli.ts                    command dispatch
src/cli-args.ts               strict argument parsing
src/harness.ts                Kimi Code harness assembly and MCP attachment
src/server.ts                 kap-server startup and host identity
src/mcp/server.ts             MCP stdio server
src/mcp/register.ts           safe mcp.json registration
src/hydroweaver/backend.ts       checkout discovery and bounded process execution
src/hydroweaver/provenance.ts    engineering input/payload fingerprints
src/hydroweaver/jobs.ts          durable jobs, logs, artifacts, manifests
src/hydroweaver/job-runner.ts    independent process runner
src/hydroweaver/tools.ts         tool catalog and Zod schemas, including hydroweaver_optimize_trains
src/hydroweaver/research.ts       gated case-to-report research state machine
src/hydroweaver/research-tools.ts research-task MCP tools and CLI controller
skills/                       focused operation and campaign guidance
theme/hydroweaver.css            branded Web visual system
scripts/sync-web-ui.mjs       deterministic Web UI branding
```

The synchronous case-assessment tool turns a normalized query into a versioned
scientific case state with deterministic readiness blockers and prioritized
next-information actions. Recommendation, retrieval, index building, knowledge
staging, closed-loop optimization, and WContBench evaluation are asynchronous. They return a `jobId`; lifecycle state, bounded
logs, output metadata, and `run-manifest.json` remain available after the
initiating session exits.

The manifest keeps request and result identities separate. `requestSha256`
includes non-secret adapter-reported model/retrieval/planning settings and
explicit environment overrides, while completed jobs capture a verified
fingerprint of the configured output when present. API keys are never recorded.
Neither identity freezes remote provider behavior; preserve knowledge, index,
model, and result artifacts separately.

## Generated assets

`dist/` and `web-ui/` are generated. Do not edit them directly. From the
repository root:

```bash
npm run sync:web
```

## License

MIT. See the repository root for OpenAqua and Kimi Code attribution.
