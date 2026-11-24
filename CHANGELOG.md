# Changelog

All notable user-facing changes are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and semantic
versioning.

## [Unreleased]

### Planned

- Additional dataset acquisition and curation helpers.
- Broader real-backend integration fixtures and benchmark reporting.

## [0.2.0-beta.1] - 2026-11-24

### Added

- Closed-loop treatment-train optimization. A new `optimize` adapter command and
  the `hydroweaver_optimize_trains` MCP tool apply the constraint critic to
  candidate trains, keep the critic's auto-revisions, and regenerate candidates
  through the planner with a structured revision directive when a round stalls.
  Each round records candidates before and after revision, the constraint
  report, unresolved violations, and the directive; the record stops at
  `feasible`, `stalled`, or `budget_exhausted` and always says which.
- A `hydroweaver optimize` CLI command (`--input`, `--top-k`, `--max-rounds`,
  `--wait`) that runs the closed loop directly as a durable job.
- An `optimization` stage in the persistent research flow between
  recommendation and audit. The stage optimizes the verified recommendation
  trains and gates handoff: a stalled or budget-exhausted loop raises an
  `optimization_inconclusive` attention item instead of claiming feasibility,
  and `continue_screening` can carry the limitation into the audit.
- Research tasks accept a bounded `maxRounds` optimization budget (default 3,
  maximum 8).

### Changed

- The product is renamed **HydroWeaver**. The CLI command is `hydroweaver`, the
  home directory defaults to `~/.hydroweaver`, the backend configuration file is
  `hydroweaver.json`, job stores live under `<workdir>/hydroweaver-jobs`, and
  the product environment namespace is `HYDROWEAVER_*`
  (`HYDROWEAVER_HOME`, `HYDROWEAVER_COMMAND`, `HYDROWEAVER_REPO`,
  `HYDROWEAVER_PYTHON`, `HYDROWEAVER_WORKDIR`, `HYDROWEAVER_JOBS_DIR`,
  `HYDROWEAVER_WEB_ASSETS_DIR`, `HYDROWEAVER_OPENROUTER_MODEL`,
  `HYDROWEAVER_DEFAULT_MODEL`, `HYDROWEAVER_PLANNER_MODEL`,
  `HYDROWEAVER_EXPLANATION_MODEL`). Onboarding flags are
  `--hydroweaver-repo` and `--hydroweaver-command`.
- MCP tools are renamed to the `hydroweaver_*` prefix (25 tools), the MCP server
  is registered as `hydroweaver`, and the skills are `hydroweaver` and
  `hydroweaver-campaign`. The engine workspace package is `hydroweaver` at
  `engine/apps/hydroweaver`.
- The default research job budget is six backend jobs (assessment, retrieval,
  recommendation, optimization, audit, plus retry headroom) instead of four.
- Desktop and Web branding, the ASCII banner, and the terminal host identity
  use the HydroWeaver name and the "from plausible to feasible" framing.
- The external OpenAqua project, its Hugging Face dataset, upstream environment
  variables, and the paper citation are unchanged; HydroWeaver remains an
  independent product layered on that pipeline.

### Added

- Optional WaterTAP/IDAES/Pyomo/IPOPT process simulation. Configure a Python
  3.10 environment with WaterTAP (`HYDROWEAVER_SIM_PYTHON`, or
  `~/.hydroweaver/simulation.json`), then `hydroweaver_simulate_train` builds a
  candidate train as a flowsheet and solves it with IPOPT: per-unit pressure,
  power, recovery, permeate salinity and membrane area, flowsheet totals and
  specific energy, solver status, unit coverage, and the package versions used.
  `hydroweaver doctor` and `hydroweaver_status` report simulation readiness.
  The MVP property package models water and sodium chloride, so results describe
  salinity-driven hydraulics and energy only; units without a mechanistic model
  are reported as unsupported rather than simulated.

### Added

- An optional simulation stage in the research flow. Between optimization and
  audit, the top feasible train is built as a WaterTAP/IDAES flowsheet and
  solved with IPOPT; the outcome (optimal, unsupported, unconverged, error, or
  skipped because no backend is configured) is recorded with its limitations,
  the manifest carries the package versions and solver settings, and handoff
  requires a recorded simulation outcome. The default job budget is eight.

### Repository maintenance

- Replaced the legacy droplet mark with new HydroWeaver brand artwork (woven
  droplet, two-tone wordmark) and regenerated every application icon from it;
  the framework diagram and both workbench screenshots now show HydroWeaver
  branding.
- Regenerated third-party notices and the SBOM for the renamed product
  packages and artifact names.
- Rewrote the README, quick start, architecture, research-task, FAQ,
  troubleshooting, and release documentation around HydroWeaver and the
  closed-loop optimization workflow.

## [0.1.0-beta.2] - 2026-11-02

### Added

- A scientific case-readiness tool that returns a versioned case state,
  critical blockers, and prioritized next-information actions.
- A durable claim–evidence report audit with structural citation checks,
  constraint and uncertainty checks, and a machine-readable claim ledger.

### Changed

- Case screening now checks quantitative values, nitrate reporting bases,
  hardness basis, lead endpoints, arsenic speciation, and declared design flow.
- Explicit extension context is retained across upstream normalization at the
  adapter boundary without implying enforcement by the upstream planner.
- CLI/REPL turns explicitly activate the OpenAqua operation skill, and Web
  guidance follows case assessment, evidence review, recommendation, and audit.
- Parallel research jobs use distinct default result paths, and CLI sessions
  share the configured research workspace with the scientific tools.
- Engineering manifests now fingerprint benchmark directories and completed
  outputs, record non-secret effective scientific settings, and retain schema-v1
  read compatibility.

### Fixed

- Empty reports, malformed citations, and missing or unknown constraint states
  no longer pass the structural report audit; warning and unreviewed states
  remain visible.
- Desktop startup waits for complete engine output lines before reading the
  server address and bearer token; packaged backends exclude Python caches.

### Security

- Update compatible HTTP, URI, schema-validation, and desktop-packaging
  dependencies while retaining dependency audits as public-release gates.
- Update image-processing schema validation and the visualization HTTP adapter,
  and replace legacy desktop archive and file-matching dependencies; add
  installation, image, HTTP, and packaging compatibility checks.

### Compatibility and scope

- Retains the OpenAqua commit `0e39908` and Hugging Face dataset revision
  `cc2d3c620e8ada7c62fa922cf3a827d8b42889e3` compatibility baseline.
- OpenAqua source, Python dependencies, and knowledge/benchmark data remain
  external installations; they are not included in the desktop application.
- Case screening and report audits support early-stage engineering research.
  Software regression and synthetic-case compatibility tests do not demonstrate
  field performance, regulatory compliance, or scientific effectiveness.

## [0.1.0-beta.1] - 2026-10-23

### Added

- Complete OpenAqua Harness product shell with CLI, TUI, Web, and Electron
  desktop interfaces based on the open-source Kimi Code engine.
- Bundled `openaqua_cli.py` adapter over the OpenAqua Parser → Retriever →
  Planner → Critic → Explanation workflow, with clean JSON stdout, current
  WContBench evidence-layout compatibility, and evaluator-module isolation.
- MCP tools for status, taxonomy browsing, query normalization, recommendation,
  evidence retrieval, candidate constraint checking, index building, knowledge
  staging, and WContBench train/retrieval evaluation.
- Durable background jobs with recovery, status, cancellation, bounded
  raw/error/event logs, cursor pagination, and symlink-safe artifact metadata.
- Schema-versioned engineering run manifests with validated parameters,
  backend command plus adapter-reported version/revision, runtime identity,
  regular-file and inline-payload SHA-256 identities, explicit requested-only
  semantics, and request fingerprints.
- API-key provider onboarding, explicit OpenAqua repository/Python discovery,
  health diagnostics, MCP registration, and focused operation/campaign skills.
- OpenAqua branding, generated desktop icons, English and Simplified Chinese
  documentation, CI, native desktop packaging, license notices, and SPDX SBOM.
- Standard-library Python adapter regression tests covering JSON stream hygiene,
  ingestion aliases, dataclass-based evaluators, and current WContBench evidence.
- A documented validation baseline at OpenAqua commit `0e39908` and Hugging Face
  dataset revision `cc2d3c620e8ada7c62fa922cf3a827d8b42889e3`.

### Changed

- Brightened the desktop and Web visual system with a logo-aligned mint, aqua,
  and blue palette; first launch now defaults to the light theme while retaining
  explicit user preferences, and all application icon formats use a luminous
  aqua-white tile.

### Security

- Atomic private configuration writes and strict malformed-config handling.
- No-shell backend execution, bounded output capture, timeout/process-tree
  cleanup, strict user-path handling, and preflight rejection of unsafe inputs.
- Sandboxed Electron renderer, loopback/token validation, permission/webview
  denial, navigation guards, secret redaction, and bounded shutdown.
- HTTPS required for non-loopback custom model-provider endpoints.

### Known limitations

- OpenAqua source, Python dependencies, and Hugging Face knowledge/benchmark
  assets are external and must be installed separately.
- Knowledge ingestion follows OpenAqua v1 staging semantics; staged records are
  not automatically merged into canonical index sources.
- Recommendations remain early-stage engineering decision support and require
  expert, regulatory, laboratory, pilot, and site-specific review.

[Unreleased]: https://github.com/zhaorui-bi/HydroWeaver/commits/main
[0.2.0-beta.1]: https://github.com/zhaorui-bi/HydroWeaver/tree/v0.2.0-beta.1
[0.1.0-beta.2]: https://github.com/zhaorui-bi/HydroWeaver/compare/6acc5252aff11946f6be8eca23882662ba4e8cb8...main
[0.1.0-beta.1]: https://github.com/zhaorui-bi/HydroWeaver/tree/6acc5252aff11946f6be8eca23882662ba4e8cb8
