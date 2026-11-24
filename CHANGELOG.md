# Changelog

All notable changes to HydroWeaver are documented in this file. The project
follows [Semantic Versioning](https://semver.org/) while in `0.x` beta
development.

## [0.3.0-beta.1] - 2026-11-25

- **Standalone Closed-Loop Joint Optimizer (`hydroweaver_py`)**: Implemented a
  self-contained Python scientific engine requiring no external repositories,
  combining:
  - knowledge-informed configuration generation over 17 canonical treatment
    units, 12 regulated/design contaminants, and 10 empirical template priors;
  - bounded coordinate-search and Hooke–Jeeves numerical operating-parameter
    optimization minimizing a feasibility-first LCOW objective;
  - a steady-state multi-unit mechanistic simulator and LCOW/SEC costing model
    tracking hydraulic integrity, scaling, fouling, CT disinfection, DBP risk,
    energy, residuals/brine constraints, CAPEX, and OPEX;
  - simulation-feedback violation diagnosis and closed-loop routing between
    operating-parameter refinement (`refine_parameters`) and train-structure
    revision (`revise_structure`: add, remove, replace, reorder);
  - a `SharedDesignHistory` preventing cyclic structural edits and recording
    every round and simulation evaluation.
- **AquaDesignGym Interactive Benchmark (`aquadesigngym`)**: Added 12
  standardized design tasks (`ADG-01-AS-RURAL` through `ADG-12-MULTI-CONTAM`),
  9 admissible structural and parametric actions under a matched simulation-call
  budget (`max_sim_calls`), 3 influent perturbation regimes (`nominal`,
  `mild_shift`, `severe_shift`), and 12 registered evaluators spanning
  HydroWeaver, baseline agents (`OneShotKnowledge`, `RuleCriticLoop`,
  `ReActBlindAgent`), conventional optimizers (`EvolutionaryMINLP`,
  `TemplateGridSearch`, `RandomSearch`), and 5 component ablations
  (`HW-NoParamOpt`, `HW-NoStructRev`, `HW-NoDiagRouter`, `HW-NoKnowledge`,
  `HW-NoHistory`).
- **WaterTAP Flowsheet Simulation & NLP Costing (`sim/runner.py`)**: Added
  `WaterTAPCosting` CAPEX/OPEX/LCOW/SEC reporting alongside the `optimize-design`
  Pyomo + IPOPT NLP optimization mode when `HYDROWEAVER_SIM_PYTHON` is
  configured.
- **Standalone CLI, MCP, Tests, and Brand Scrub**: Removed all external backend
  repository requirements, exposed `hydroweaver_gym_tasks` and
  `hydroweaver_evaluate_gym` within the 26-tool MCP surface, added
  `hydroweaver gym tasks|eval` and `--max-sim-calls` CLI options, replaced
  `--hydroweaver-repo` with `--hydroweaver-python`, updated TUI/Web branding,
  and added Python unit tests (`test_aquadesigngym.py`, `test_hydroweaver_cli.py`,
  `test_sim_runner.py`).

## [0.2.0-beta.1] - 2026-10-13

- **Gated Case-to-Report Research Controller (`hydroweaver research`, `hydroweaver_research_*`)**:
  Added a schema-versioned persistent research state machine managing case
  revisions, frozen scientific query normalization, declared scope, structured
  attention items, and bounded multi-stage job orchestration across `create`,
  `status`, `list`, `advance`, `respond`, and `cancel`.
- **Engineering Run Provenance (`hydroweaver_job_manifest`)**: Added schema-v2
  atomic run manifests recording backend identity, input/output SHA-256
  hashes, recursive benchmark directory fingerprinting, canonical payload
  digests, secret filtering, and tamper detection.
- **Bounded Log & Job Views**: Added cursor-paged log inspection, `errors`
  filtering, explicit job cancellation, and workspace-isolated job stores.

## [0.1.0-beta.1] - 2026-09-25

- Initial HydroWeaver workbench release built on the MIT-licensed Kimi Code
  agent engine with CLI, TUI, local Web UI, Electron desktop packaging, MCP
  stdio integration, onboarding, and diagnostics.
