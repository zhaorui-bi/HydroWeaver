# Process simulation integration (WaterTAP · IDAES · Pyomo · IPOPT)

HydroWeaver's closed loop currently stops at **rule-based feasibility**: the
OpenAqua critic checks declared constraints against implemented rules. This
document describes the optional simulation backend that upgrades the loop to
**mechanistic and economic feasibility**: build the candidate train as a
WaterTAP/IDAES flowsheet, solve it with IPOPT through Pyomo, and report
hydraulic, energy, and cost outcomes with full engineering provenance.

Everything here is **optional and external**, exactly like the OpenAqua
checkout. Nothing is vendored; the repository ships only the command contract,
the unit mapping, the runner, and the capability probes.

## Verified reference environment

The P0/P1 contract is verified against this environment (Python 3.10):

| Component | Verified version |
| --- | --- |
| Python | 3.10.22 |
| watertap | 1.8.0 |
| idaes-pse | 2.13.0 |
| pyomo | 6.10.1 |
| cyipopt | 1.7.0 |
| IPOPT (via `idaes get-extensions`) | 3.13.2 binaries in `~/.idaes/bin` |

Setup that works on macOS arm64:

```bash
micromamba create -y -n watertap -c conda-forge python=3.10 idaes-pse pyomo cyipopt "scipy=1.15"
micromamba run -n watertap pip install watertap
micromamba run -n watertap idaes get-extensions
export HYDROWEAVER_SIM_PYTHON=~/mamba/envs/watertap/bin/python
./bin/hydroweaver doctor --probe        # shows the simulation_backend check
```

A verified result (250 m³/day, 2.5 g/L TDS feed, Pump → Reverse Osmosis,
50 % recovery target): `status: optimal`, permeate 1.443 kg/s, permeate NaCl
0.083 g/L, membrane area 883.7 m², pump power 2 702 W, specific energy
0.52 kWh/m³.

## Scientific scope — read this first

| Question | Answered by | Mechanism |
| --- | --- | --- |
| Does the train violate declared constraints? | OpenAqua critic | Taxonomy, disinfection, brine, and energy rules |
| What recovery, pressure, and energy does the flowsheet need? | WaterTAP/IDAES simulation | Steady-state mass/energy balances, membrane transport |
| What does it cost? | WaterTAP costing (planned P2) | CAPEX/OPEX correlations, LCOW |
| What design minimizes cost or energy? | Pyomo + IPOPT (planned P3) | Nonlinear program over design variables |
| Will arsenic/nitrate/fluoride meet the target? | **Not answered by simulation in this phase** | The MVP property package (`NaCl`) models water + sodium chloride salinity only |

The MVP uses WaterTAP's `NaCl` property package because it is the package with
the most complete membrane unit models. It predicts **salinity-driven
hydraulics and energy** (recovery, osmotic pressure, feed pressure, specific
energy consumption). It does **not** contain trace contaminants such as
arsenic, nitrate, fluoride, or lead, so it cannot predict their rejection or
target attainment. Contaminant-level feasibility remains the rule-based
critic's responsibility, and every simulation result says so explicitly. A
multi-solute property package is a later phase, not a silent assumption.

A simulation result with `solver_status` other than optimal is reported as
unconverged, never as "infeasible" and never as a performance claim.

## Architecture

```text
HydroWeaver (MCP tool: hydroweaver_simulate_train)
  └─► durable job (same runner/manifest machinery as every other operation)
        └─► adapter command: simulate
              └─► <simulation python> engine/apps/hydroweaver/sim/runner.py simulate
                    └─► WaterTAP / IDAES / Pyomo  ──►  IPOPT (via cyipopt)
```

The simulation backend needs its own Python environment. WaterTAP, IDAES, and
Pyomo pin numpy/scipy/pint versions that conflict with the OpenAqua checkout,
so the runner is always launched as a **separate subprocess** with a
dedicated interpreter — never imported into the adapter process.

### Environment setup (Python 3.10)

```bash
mamba create -y -n watertap python=3.10 -c conda-forge idaes-pse pyomo cyipopt
mamba activate watertap
idaes get-extensions          # downloads the IPOPT solver binaries for this platform
pip install watertap
```

Verify with the runner itself:

```bash
<env python> engine/apps/hydroweaver/sim/runner.py self-check
```

### Backend resolution

The simulation backend is resolved independently of the OpenAqua backend:

1. `HYDROWEAVER_SIM_PYTHON` — path to a Python interpreter that has WaterTAP
   installed;
2. `~/.hydroweaver/simulation.json` — `{ "python": "/abs/path/to/python" }`,
   written by an explicit setup step;
3. not configured — capability probes report `unavailable` with setup guidance.

`HYDROWEAVER_SIM_PYTHON` is forwarded to the MCP server and desktop
environments like the OpenAqua backend variables. The runner path itself is
resolved from the installed package root, so the same build works from source,
from a staged smoke directory, and from the packaged desktop application.

## Runner command contract

The runner speaks the same JSON-in/JSON-out contract as the OpenAqua adapter
and writes its output atomically.

| Command | Input | Output |
| --- | --- | --- |
| `self-check` | none | `kind: hydroweaver.simulation-selfcheck`, package versions, solver availability, supported unit models, `available: true/false` |
| `simulate` | `--input case.json`, `--output result.json` | `kind: hydroweaver.simulation-result`, per-unit results, coverage, solver status, version provenance |

`self-check` is the acceptance probe: it is what `hydroweaver doctor` and
`hydroweaver_status` call, and what CI uses to prove the contract without a
WaterTAP installation.

### `simulate` input

```json
{
  "schema_version": 1,
  "case": { "…": "OpenAqua UserQuery fields (source_water, water_quality, constraints…)" },
  "train": { "chain_id": "chain-1", "chain": ["Pumping", "Reverse Osmosis", "Chlorination"] },
  "options": {
    "property_package": "NaCl",
    "solver": "ipopt",
    "feed_salinity_g_L": null,
    "design_flow_m3_day": null
  }
}
```

`feed_salinity_g_L` and `design_flow_m3_day` may be supplied explicitly;
otherwise the runner derives salinity from the case's declared measurements
(only NaCl-equivalent inputs such as TDS are used — unknown values stay
unknown and are reported, never invented).

### `simulate` output (MVP shape)

```json
{
  "kind": "hydroweaver.simulation-result",
  "schema_version": 1,
  "status": "optimal | unconverged | unsupported | error",
  "coverage": {
    "modeled": ["Pumping", "Reverse Osmosis"],
    "unsupported": ["Adsorption"],
    "note": "Unsupported units are excluded from the flowsheet and flagged."
  },
  "units": [
    { "unit": "Pumping", "model": "watertap.unit_models.pressure_changer", "results": { "…": "…" } }
  ],
  "flowsheet": { "feed_flow_m3_h": 0, "product_flow_m3_h": 0, "recovery_fraction": 0, "specific_energy_kWh_m3": 0 },
  "solver": { "name": "ipopt", "status": "optimal", "iterations": 0, "message": "" },
  "environment": { "watertap": "…", "idaes": "…", "pyomo": "…", "cyipopt": "…", "python": "…" },
  "limitations": ["…"]
}
```

`status: unsupported` means no unit in the train maps to a mechanistic model;
the tool then reports the rule-based screening result instead of a simulation.

## Unit mapping

The mapping table lives in `sim/unit_map.py`. It maps OpenAqua taxonomy unit
names to WaterTAP unit models and property packages. A unit with no entry is
`unsupported` — the runner never silently substitutes a different unit.

| OpenAqua unit (examples) | WaterTAP model (MVP) | Notes |
| --- | --- | --- |
| Pumping, Feed Pump, Booster Pump | `pressure_changer` | Isentropic/constant efficiency |
| Reverse Osmosis, RO, Membrane Separation | `reverse_osmosis_1D` | Salinity-driven; 1D spiral-wound |
| Nanofiltration, NF | `reverse_osmosis_1D` (NF config) | Same model class, NF membrane parameters |
| Ultrafiltration, Microfiltration | `pressure_changer` + rejection split | Pressure-driven; solute rejection from membrane parameters |
| Chlorination, Chlorine Dosing | `chemical_addition` | Dose-based; CT/disinfection is **not** modeled |
| Adsorption, Coagulation, Sedimentation, Media Filtration, Ion Exchange, AOP | — | No MVP mechanistic model → `unsupported` |

The mapping is data, not code: adding a unit model means adding one entry and
a test, and the self-check reports the supported set so agents can see
coverage before promising a simulation.

## The research-flow stage

`hydroweaver research` runs the simulation as an optional stage between
optimization and audit:

- the train is the top train the closed loop certified feasible (falling back to
  the recommendation shortlist);
- the case is the frozen normalized query, so salinity and design flow come from
  the declared case unless explicitly overridden;
- with no simulation backend configured the stage is recorded as
  `skipped_unconfigured` with a limitation and no job is launched;
- `unsupported`, `unconverged`, and `error` outcomes are recorded with
  limitations and never promoted to a mechanistic claim;
- handoff requires a recorded simulation outcome for the current revision, and
  the manifest carries the package versions, solver, property package, and
  supported-unit list.

## Numerical recipe (verified)

These choices are what makes the screening solve converge across salinities;
they follow the WaterTAP membrane examples and are reported with every result.

| Step | Choice | Why |
| --- | --- | --- |
| Unit model | `reverse_osmosis_0D` | WaterTAP's default screening model; no DAE discretization, robust initialization |
| Membrane configuration | `concentration_polarization_type=fixed` (cp_modulus 1.1), `mass_transfer_coefficient=none`, `has_pressure_change=True`, nominal 3 bar retentate drop | Correlation-free, salinity-robust |
| Feed boundary | IDAES `Feed` unit with pressure, temperature, and both component mass flows fixed | Standard WaterTAP boundary |
| Operating pressure | `atmospheric + pressure drop + calculate_operating_pressure(...)` | WaterTAP's correlation returns the brine osmotic pressure × over-pressure factor **without** the atmospheric and drop floors; without them the retentate end has a negative driving force and the model is genuinely infeasible at low salinity |
| Scaling | Property-level `set_default_scaling` declared **before** unit construction (covers permeate-side states), plus explicit factors on membrane area and the permeate mass-fraction constraints | Missing permeate-side scaling is the usual cause of local infeasibility |
| Solver | `watertap.core.solvers.get_solver()` with `nlp_scaling_method=user-scaling` | IDAES extensions resolve IPOPT; user scaling is required for the constraint factors to apply |
| Initialization | Relaxed membrane recipe: release the area, drive the declared recovery with an area objective, then fix the recovery and remove the objective | WaterTAP's documented remedy for initialization trouble |
| Square formulation | Membrane area free, declared water-recovery target fixed; degrees of freedom asserted to be 0 before solving | A non-square model is a reported build failure, never a silent wrong answer |

## Provenance and reproducibility

Simulation runs use the same durable-job and manifest machinery as every other
operation. In addition to the standard request/result fingerprints, a
simulation manifest records:

- `watertap`, `idaes`, `pyomo`, `cyipopt`, and Python versions;
- solver name, status, iteration count, and termination message;
- the property package and the unit-model versions actually used;
- the coverage decision (modeled vs unsupported units).

Two runs with identical inputs, unit versions, and solver versions should
produce identical outputs; a changed solver version is a new run, not a
reproduction. This is why versions are recorded rather than assumed.

## Roadmap

| Phase | Delivered | Status |
| --- | --- | --- |
| P0 | Design (this document), `sim/runner.py` self-check, capability detection in `doctor`/`status`, unit-map skeleton, tests | done |
| P1 | `hydroweaver_simulate_train` — steady-state simulation of RO/NF + pumping with coverage reporting | done |
| P2 | WaterTAP costing — `hydroweaver_cost_train` (CAPEX/OPEX/LCOW) | planned |
| P3 | Pyomo + IPOPT design optimization — `hydroweaver_optimize_design`, results fed back into the research optimization stage | planned |
| P4 | Optional `simulation` research stage between optimization and audit | done |

P0 and P1 are independently useful: even without costing or optimization, a
verified hydraulic/energy result per candidate train is a large step beyond
rule-based screening.
