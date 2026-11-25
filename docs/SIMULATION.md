# WaterTAP Process Simulation & NLP Optimization (`hydroweaver_simulate_train`)

This document specifies HydroWeaver’s optional **WaterTAP / IDAES / Pyomo / IPOPT**
flowsheet backend (`engine/apps/hydroweaver/sim/runner.py` and `engine/apps/hydroweaver/sim/wastewater.py`).

## Supported Flowsheet Families

HydroWeaver’s WaterTAP runner supports three mechanistic flowsheet families:

1. **Membrane Desalination (`NaCl`)**:
   - Units: `Pumping`, `Reverse Osmosis`, `Nanofiltration`
   - Property package: `watertap.property_models.NaCl_prop_pack`
   - `simulate` (`optimizeDesign: false`): Solves at declared recovery and salinity.
   - `optimize-design` (`optimizeDesign: true`): Unfixes `Pump.outlet.pressure`,
     `ReverseOsmosis0D.area`, and recovery within bounds and minimizes `WaterTAPCosting.LCOW`.
2. **Activated Sludge (`ASM1`)**:
   - Flowsheet: `watertap.flowsheets.activated_sludge.ASM1_flowsheet`
   - Units: `Activated Sludge (ASM1)`, `Anoxic Reactor`, `Aerobic Reactor`, `Secondary Clarifier`
   - Models steady-state biological carbon oxidation, nitrification, and pre-denitrification
     (2 anoxic CSTR + 3 aerobic `CSTR_Injection` reactors + clarifier + RAS/internal recycle).
   - `optimize-design`: Unfixes reactor volumes, aeration `KLa`, and internal recycle split
     subject to effluent `COD`, `TN`, and `NH4-N` limits.
3. **Full-Plant Resource Recovery (`BSM2`)**:
   - Flowsheet: `watertap.flowsheets.full_water_resource_recovery_facility.BSM2`
   - Units: `BSM2 Full Plant`, `Primary Clarifier`, `Sludge Thickener`, `Anaerobic Digester`, `Sludge Dewatering`
   - Models the coupled **ASM1** waterline + **ADM1** anaerobic digester + sludge thickening/dewatering
     and `WaterTAPCosting` (CAPEX, OPEX, `LCOW`, `SEC`, biogas flow).
   - Supports configurable `n_anoxic` partitioning (1, 2, or 3 anoxic reactors), reactor volumes,
     aerobic DO setpoints, recycles, and `optimize-design` minimizing `LCOW` under effluent targets.

## Scope & Scientific Guarantees

- **NaCl vs. Trace Contaminants**: The `NaCl` property package models bulk water and TDS (`NaCl`)
  rejection only — it does **not** predict arsenic, nitrate, PFAS, or hardness scaling.
- **ASM1 / BSM2 Uncalibrated Scope**: WaterTAP ASM1 and BSM2 results evaluate steady-state
  biological nutrient/COD removal and plant costing under reference kinetic/stoichiometric parameters;
  they are uncalibrated (`mechanistic_unvalidated`) unless fitted to site data.
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
model blocks (`NaCl`, `ASM1`, and `BSM2`).
