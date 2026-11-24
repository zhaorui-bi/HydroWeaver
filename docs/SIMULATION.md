# WaterTAP Process Simulation & NLP Optimization (`hydroweaver_simulate_train`)

This document specifies HydroWeaver’s optional **WaterTAP / IDAES / Pyomo / IPOPT**
flowsheet backend (`engine/apps/hydroweaver/sim/runner.py`).

## Scope & Scientific Guarantees

- **NaCl property package**: The WaterTAP flowsheet models water and TDS
  (`NaCl` mass fraction) using `watertap.property_models.NaCl_prop_pack`.
- **Supported metrics**: Converged runs return mass-balance flows, osmotic
  pressure, pump power, **SEC (`kWh/m³`)**, **WaterTAPCosting CAPEX (`$`), OPEX
  (`$/yr`), and LCOW (`$/m³`)**.
- **Two execution modes**:
  - `simulate` (`optimizeDesign: false`, default): Solves the flowsheet at
    declared water recovery and feed salinity.
  - `optimize-design` (`optimizeDesign: true`): Unfixes `Pump.outlet.pressure`,
    `ReverseOsmosis0D.area`, and overall product recovery within physical bounds
    and runs **IPOPT** to minimize `WaterTAPCosting.LCOW`.
- **Unsupported trace contaminants**: NaCl models bulk TDS rejection and osmotic
  hydraulics only. Use HydroWeaver’s built-in multi-contaminant engine
  (`hydroweaver_check_constraints` / `hydroweaver_optimize_trains`) to evaluate
  arsenic, nitrate, PFAS, VOCs, hardness scaling, NOM/DBPs, and pathogen CT.
- **Unconverged vs. infeasible**: An unconverged IPOPT solve is reported
  honestly as unconverged/failed, never silently treated as infeasible design.

## Setup (Separate Python Environment)

WaterTAP is **not** required for default HydroWeaver usage or `npm run check`.
When available in an existing Conda/Mamba/venv environment:

```bash
export HYDROWEAVER_SIM_PYTHON="$HOME/mamba/envs/watertap/bin/python"
./bin/hydroweaver doctor --probe
```

You can also record it persistently in `~/.hydroweaver/simulation.json`:

```json
{
  "python": "/path/to/watertap-env/bin/python"
}
```

## Direct Runner Usage

```bash
"$HYDROWEAVER_SIM_PYTHON" engine/apps/hydroweaver/sim/runner.py self-check
"$HYDROWEAVER_SIM_PYTHON" engine/apps/hydroweaver/sim/runner.py optimize-design \
  --input path/to/sim-input.json \
  --output path/to/sim-output.json
```

See [engine/apps/hydroweaver/sim/unit_map.py](../engine/apps/hydroweaver/sim/unit_map.py)
for unit-name normalization between HydroWeaver taxonomy labels and WaterTAP
model blocks.
