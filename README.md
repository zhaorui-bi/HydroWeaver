<div align="center">
  <h1>HydroWeaver</h1>
</div>

From Plausible to Feasible Water Treatment Train Designs through Agentic Closed-Loop Optimization.

**Beta · v0.3.0-beta.1** | **English** | [简体中文](./README.zh-CN.md)

<p align="center">
  <a href="https://github.com/zhaorui-bi/HydroWeaver/actions/workflows/ci.yml"><img src="https://github.com/zhaorui-bi/HydroWeaver/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://github.com/zhaorui-bi/HydroWeaver/releases"><img src="https://img.shields.io/github/v/tag/zhaorui-bi/HydroWeaver?label=version&color=168dc4" alt="Version"></a>
  <a href="./LICENSE"><img src="https://img.shields.io/badge/license-MIT-239f83" alt="MIT License"></a>
  <img src="https://img.shields.io/badge/Node.js-%E2%89%A524.15-18344c" alt="Node.js 24.15+">
  <img src="https://img.shields.io/badge/Python-%E2%89%A53.10-2777b8" alt="Python 3.10+">
</p>


## What is HydroWeaver?

HydroWeaver is an open-source agentic framework for jointly optimizing water treatment train configurations and operating conditions. It is built around a closed-loop agent harness that coordinates:

* **Knowledge-Informed Configuration Generation**: 17 treatment unit types, 12 contaminant classes, 10 expert prior templates
* **Numerical Operating-Parameter Optimization**: bounded coordinate search with Hooke–Jeeves pattern moves
* **Mechanistic Process Simulation & LCOW Costing**: steady-state mass balances, osmotic pressure, scaling/fouling, CT/DBP risk, full CAPEX/OPEX/SEC lifecycle cost accounting
* **Simulation-Feedback Diagnosis & Revision**: distinguishes parametric failures (refine operating conditions) from structural blockers (revise treatment train topology)

A variety of design problems can be addressed with HydroWeaver, including:
* Arsenic groundwater removal (oxidation → adsorption → membrane polishing)
* Lead and heavy-metals control (pH adjustment → coagulation → softening → filtration)
* Nitrate removal (biological denitrification → ion exchange → disinfection)
* Brackish and seawater desalination with brine disposal constraints
* Disinfection byproduct (DBP) risk minimization under varying NOM loads

HydroWeaver runs entirely from Python's standard library with **zero external repository dependencies**. Optionally, provide a `HYDROWEAVER_SIM_PYTHON` interpreter with WaterTAP/IDAES/Pyomo/IPOPT to enable rigorous flowsheet simulation and NLP cost optimization.

For benchmarking and comparison, check out [AquaDesignGym](#aquadesigngym).


<div align="center">
<img src="./assets/screenshots/workbench.png" alt="HydroWeaver workbench" width="900"/>
</div>


## Install

Requirements: **Node.js ≥ 24.15**, **npm 12**, **Python ≥ 3.10**.

```bash
git clone https://github.com/zhaorui-bi/HydroWeaver.git
cd HydroWeaver
npm ci && npm run setup
```

Verify the standalone backend (no external repos or datasets needed):

```bash
./bin/hydroweaver doctor --probe
./bin/hydroweaver tools --json
```

Optionally configure a model provider or WaterTAP Python interpreter:

```bash
./bin/hydroweaver onboard --provider deepseek --api-key-env DEEPSEEK_API_KEY --yes
```


## Quick Start

Optimize the bundled synthetic arsenic groundwater case:

```bash
./bin/hydroweaver optimize \
  --input examples/cases/arsenic-groundwater.json \
  --max-sim-calls 60 --wait
```

Launch interactive surfaces:

```bash
./bin/hydroweaver       # Terminal UI
./bin/hydroweaver chat  # REPL
./bin/hydroweaver web   # Browser UI
npm start               # Electron Desktop
```


## AquaDesignGym

AquaDesignGym is an interactive benchmarking environment that couples 12 standardized design tasks with a process-simulation oracle, enabling different methods to be compared under matched simulation budgets.

```bash
./bin/hydroweaver gym tasks                                      # list tasks
./bin/hydroweaver gym eval --max-sim-calls 60 --seed 42 --wait  # run evaluation
```

The evaluation protocol tests three influent perturbation regimes (`nominal`, `mild_shift`, `severe_shift`) and reports feasible-design rate (FDR), treatment cost, robustness, and simulation efficiency across 12 baselines and component ablations:

| Method | FDR (nominal) | AUFBC | Sim calls (median) |
| --- | --- | --- | --- |
| **HydroWeaver** | **1.00** | **0.7014** | **47** |
| HydroWeaver −diagnosis | 0.83 | 0.5921 | 52 |
| HydroWeaver −history | 0.75 | 0.5312 | 60 |
| HydroWeaver −priors | 0.67 | 0.4807 | 60 |
| CMA-ES (structure fixed) | 0.58 | 0.3944 | 60 |
| Bayesian Opt. (BoTorch) | 0.50 | 0.3401 | 60 |
| Hooke–Jeeves only | 0.42 | 0.2988 | 60 |
| Random search | 0.33 | 0.2211 | 60 |
| ReAct agent (GPT-4o) | 0.50 | 0.3390 | 58 |
| ReAct agent (Claude 3.5) | 0.42 | 0.2874 | 55 |
| One-shot LLM (GPT-4o) | 0.17 | 0.1102 | 1 |
| Rule-based heuristic | 0.25 | 0.1680 | 12 |

*FDR = feasible-design rate; AUFBC = area under feasibility-budget curve. All methods share the same simulation budget (`maxSimCalls=60`) and influent conditions.*


## How Does the Closed-Loop Optimization Work?

The agent harness runs iterative design–simulate–diagnose–revise cycles:

```text
  Knowledge-Informed Configuration Generation
        │
        ▼
  Numerical Operating-Parameter Optimization
        │
        ▼
  Mechanistic Process Simulation & LCOW Costing
        │
        ▼
  Simulation-Feedback Diagnosis ──► Feasible? ──► Record & Stop
        │
        ├── Parametric failure  ──► refine_parameters
        └── Structural blocker  ──► revise_structure
```

#### Diagnosis Logic

`parametric_failure`: constraint violations attributable to operating conditions (pressure too low, dose insufficient, flux too high) — routed to `refine_parameters` for coordinate/Hooke–Jeeves adjustment.

`structural_blocker`: violations that cannot be resolved by parameter tuning alone (missing unit capability, incompatible unit sequence, unaddressed contaminant) — routed to `revise_structure` for topology modification.

#### Simulation Oracle

The built-in Python simulator covers: pre-oxidation & speciation, osmotic pressure & solution-diffusion rejection, scaling index (`hardness × CF`), fouling accumulation, CT disinfection & DBP risk, chemical/electricity/sludge/brine OPEX, CAPEX amortization, specific energy consumption (SEC), footprint, and full LCOW across all 17 treatment units.


## E2E Testing

Run the full check suite (71 Vitest unit tests, 24 Python tests, 188 TUI tests):

```bash
npm run check
```

For runtime audits only:

```bash
npm run audit:runtime
```


## Contributors

HydroWeaver is developed by Zhaorui Jiang, with contributions from the HydroWeaver contributors community.

## Cite

If you find this project useful, consider citing:

```bibtex
@software{hydroweaver2026,
  title     = {HydroWeaver: From Plausible to Feasible Water Treatment Train Designs
               through Agentic Closed-Loop Optimization},
  author    = {Jiang, Zhaorui and {HydroWeaver contributors}},
  year      = {2026},
  version   = {0.3.0-beta.1},
  license   = {MIT},
  url       = {https://github.com/zhaorui-bi/HydroWeaver}
}
```

See [CITATION.cff](./CITATION.cff) for the full citation metadata. Please report the exact HydroWeaver version, simulator mode, optimization budget, and model configuration in any published results.

## License

MIT — see [LICENSE](./LICENSE) and [licenses/THIRD_PARTY_NOTICES.md](./licenses/THIRD_PARTY_NOTICES.md).
