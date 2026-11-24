# Durable Research Tasks & Provenance

HydroWeaver’s `hydroweaver research` CLI and `hydroweaver_research_*` MCP tools
manage durable, schema-versioned case-to-report research tasks alongside
tamper-evident engineering run manifests (`hydroweaver_job_manifest`).

## Task Lifecycle

| Action | Tool / Command | Behavior |
| --- | --- | --- |
| `create` | `hydroweaver_research_create` | Registers a task idempotently from `requestId` + case snapshot + job budget (`maxJobs`). Starts no backend execution yet. |
| `status` | `hydroweaver_research_status` | Recovers full revision history, frozen query hash, pending attention items, and active job IDs. |
| `list` | `hydroweaver_research_list` | Lists tasks across active and compatible workspace job stores. |
| `advance` | `hydroweaver_research_advance` | Reconciles finished backend jobs, detects query drift, and launches the next stage job (`assess-case`, `retrieve`, `recommend`, `audit-report`). Optimistic locking via `expectedVersion`. |
| `respond` | `hydroweaver_research_respond` | Records amended query inputs or explicit human response to structured `attention` items without waiving critical blockers. |
| `cancel` | `hydroweaver_research_cancel` | Cancels an active task and records final state cleanly. |

## Engineering Run Provenance (`schemaVersion: 2`)

Every job started through HydroWeaver (`optimize`, `gym-eval`, `recommend`,
`retrieve`, `audit-report`, `simulate`, `optimize-design`, `build-indexes`,
`ingest`) writes an atomic SHA-256 run manifest storing:

- exact backend command & identity (`adapter_version`, `engine_mode`,
  optimization & AquaDesignGym capabilities);
- resolved parameter snapshot and canonical payload SHA-256 digests;
- file & recursive directory SHA-256 fingerprints (`benchmarkDir`, `queryFile`,
  `reportFile`, `output`);
- scrubbed environment overrides (secrets and API tokens are strictly excluded);
- tamper detection on `hydroweaver_job_manifest` inspection.

For CLI examples, inspect [examples/cases/arsenic-groundwater.json](../examples/cases/arsenic-groundwater.json)
or run `./bin/hydroweaver research --help`.
