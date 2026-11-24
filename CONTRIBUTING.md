# Contributing to HydroWeaver

Contributions that improve optimization algorithms, physical/cost models,
AquaDesignGym benchmarks, WaterTAP simulation coverage, workflow clarity, or
cross-platform reliability are welcome.

## Development setup

Requirements:

- Node.js **24.15.0 or newer**
- npm **12**
- Python **3.10 or newer** (standard library only for the default engine and CI)
- Optional WaterTAP environment (`HYDROWEAVER_SIM_PYTHON`) for detailed
  WaterTAP/IDAES/Pyomo/IPOPT flowsheet runs

```bash
git clone https://github.com/zhaorui-bi/HydroWeaver.git
cd HydroWeaver
npm ci
npm run setup
```

Most TypeScript tests use fake backend fixtures and run without extra Python
dependencies; Python scientific engine and AquaDesignGym tests use standard
library `unittest`.

## Code & safety guidelines

1. Keep the scientific core cleanly separated:
   - Domain knowledge, mechanistic simulator, numerical parameter optimizer,
     violation diagnosis, shared design history, and closed-loop harness live
     under `engine/apps/hydroweaver/hydroweaver_py/`.
   - The benchmark environment, baselines, and component ablations live under
     `engine/apps/hydroweaver/aquadesigngym/`.
   - WaterTAP/IDAES/Pyomo/IPOPT integration lives under
     `engine/apps/hydroweaver/sim/`.
   - CLI/Web/TUI/MCP orchestration lives under `engine/apps/hydroweaver/src/`.
2. Preserve local-first security invariants:
   - Validate and resolve file paths strictly within allowed workspaces.
   - Never invoke shell interpolation (`shell: false` in subprocess calls).
   - Never log or serialize raw API keys into run manifests or config backups.
3. Update corresponding tests when modifying MCP tool schemas, CLI arguments,
   simulation behavior, or UI copy.

## Verification

Before opening a pull request, run the full repository check suite:

```bash
npm run check
npm run audit:runtime
```

If you modified third-party license metadata or dependencies, regenerate
attribution files first:

```bash
npm run licenses
```

If you have a WaterTAP Python environment configured, verify real flowsheet
simulation and NLP optimization against it as well:

```bash
python3 -m unittest discover -s engine/apps/hydroweaver/test-python -p "test_*.py" -v
```
