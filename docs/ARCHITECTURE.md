# HydroWeaver Architecture

HydroWeaver is a self-contained framework implementing **agentic closed-loop
optimization** for joint treatment-train configuration and operating-parameter
design, coupled with the **AquaDesignGym** benchmark suite and an optional
**WaterTAP / IPOPT** flowsheet backend.

## Components

```text
+-------------------------------------------------------------------+
| User Surfaces                                                     |
|   CLI · TUI (Kimi Code host) · Local Web UI · Electron Desktop    |
+---------------------------------+---------------------------------+
                                  |
                                  v
+-------------------------------------------------------------------+
| TypeScript Harness & Control Plane (engine/apps/hydroweaver/src/) |
|   - 26 MCP tools (hydroweaver_*) & strict path/policy enforcement |
|   - Durable Job Store & SHA-256 Engineering Run Manifests         |
|   - Gated Case-to-Report Research Controller                      |
+--------------------+----------------------------------+-----------+
                     |                                  |
                     v                                  v
+--------------------------------------+   +------------------------+
| Standalone Python Scientific Engine  |   | Optional WaterTAP Mode |
| (backend/hydroweaver_cli.py)         |   | (sim/runner.py)        |
|                                      |   |                        |
| 1. hydroweaver_py/                   |   | - unit_map.py          |
|    - knowledge.py (17 units, 12      |   | - WaterTAPCosting      |
|      contaminants, 10 template priors|   | - optimize-design      |
|      deterministic normalizer & KB)  |   |   (Pyomo + IPOPT NLP)  |
|    - simulator.py (mass balance,     |   +------------------------+
|      osmotic & solution-diffusion RO,|
|      scaling, fouling, CT/DBP, LCOW) |
|    - optimizer.py (bounded coordinate|
|      & Hooke-Jeeves parameter opt)   |
|    - diagnosis.py (violation routing:|
|      refine_parameters vs.           |
|      revise_structure)               |
|    - history.py (SharedDesignHistory)|
|    - harness.py (closed-loop runner) |
|                                      |
| 2. aquadesigngym/                    |
|    - tasks.py (12 tasks, 3 regimes)  |
|    - env.py (9 actions, sim oracle)  |
|    - baselines.py (12 methods)       |
|    - evaluate.py (metrics & shifts)  |
+--------------------------------------+
```

## Closed-Loop Joint Optimization

1. **Knowledge-Informed Candidate Generation (`knowledge.py`)**: Normalizes
   influent quality, treatment targets, resource bounds (brine disposal,
   energy/area/cost caps), and operating context, then proposes structured unit
   sequences prioritized by contaminant mechanisms and template priors.
2. **Numerical Operating-Parameter Optimization (`optimizer.py`)**: Uses bounded
   coordinate search with Hooke–Jeeves pattern extrapolation to optimize
   continuous operating variables (`recovery`, `feed_pressure_bar`,
   `flux_lmh`, `dose_mg_L`, `ebct_min`, `ct_mg_min_L`, `uv_dose_mj_cm2`) against
   a feasibility-first objective (`total_penalty`, then `lcow_usd_m3`).
3. **Process Simulation & Costing (`simulator.py`)**: Computes unit-by-unit
   effluent concentrations, concentration polarization / osmotic pressure,
   hardness × CF scaling indices, membrane fouling loading, disinfection CT and
   DBP formation risk, specific energy consumption (SEC), footprint, CAPEX,
   OPEX, and LCOW.
4. **Diagnostic Routing (`diagnosis.py`) & Shared Design History (`history.py`)**:
   Simulation constraint violations are categorized (`water_quality`,
   `resource`, `cost`, `integrity`) and routed either to
   `refine_parameters` (when unit capabilities match requirements) or to
   `revise_structure` (`add`, `remove`, `replace`, `reorder` actions such as
   pre-oxidation for As(III), hardness softening, membrane pretreatment, brine
   concentrator or non-brine alternatives, ERD addition, or UV swap).
   `SharedDesignHistory` records every evaluated topology and blocks revisiting
   exhausted configurations.

## Isolation & Security Boundaries

- **Standard-library default Python**: All default commands and CI checks run
  with Python 3.10+ stdlib alone.
- **No shell interpolation**: External commands use explicit argv arrays and
  `shell: false`.
- **Workspace path validation**: File paths in MCP tools and CLI jobs are
  validated inside the declared workspace.
- **Secret isolation**: Model API keys stay out of run manifests and backup
  archives.
