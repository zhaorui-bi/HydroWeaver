# Troubleshooting

[简体中文](./zh-CN/TROUBLESHOOTING.md) | **English**

Start with:

```bash
./bin/hydroweaver doctor --probe
./bin/hydroweaver tools --json
```

On Windows, use `npm run cli --` instead of `./bin/hydroweaver`.

## Installation & Build

### Node.js is older than 24.15

Upgrade Node.js to 24.15.0 or newer, then run:

```bash
npm ci
npm run setup
```

### CLI says engine or Web UI assets are missing

Run `npm run setup` from the repository root to build
`engine/apps/hydroweaver/dist/` and `engine/apps/hydroweaver/web-ui/`.

## Python Engine & Simulation Backend

### `hydroweaver_backend` is not found or uses the wrong Python

Ensure `python3` (≥ 3.10) is on `PATH`, or configure an explicit interpreter:

```bash
export HYDROWEAVER_PYTHON=/path/to/python3
# or record persistently:
./bin/hydroweaver onboard --hydroweaver-python /path/to/python3 --yes
./bin/hydroweaver doctor --probe
```

### `hydroweaver_simulate_train` says simulation backend is not configured

WaterTAP simulation is opt-in and runs in an isolated Python environment
containing `watertap`, `idaes-pse`, `pyomo`, and `ipopt`:

```bash
export HYDROWEAVER_SIM_PYTHON="$HOME/mamba/envs/watertap/bin/python"
./bin/hydroweaver doctor --probe
```

### Knowledge indexes are missing or empty

Rebuild the local knowledge corpus under `HYDROWEAVER_HOME`:

```bash
./bin/hydroweaver run "Check status and run hydroweaver_build_indexes if needed."
```

Or stage new `kb_unit` / `kb_case` records via `hydroweaver_ingest_knowledge`.

## Closed-Loop Optimization & Constraints

### Contaminants disappear during normalization

Verify canonical contaminant keys and recognized aliases via `hydroweaver_catalog`.

### Optimization stops with `stalled` or `budget_exhausted`

Inspect the final round diagnostics in the output JSON:
- `unresolved`: remaining `water_quality`, `resource`, `cost`, or `integrity`
  violations on best trains;
- `routing_decision`: whether structural edits (`add`/`remove`/`replace`/`reorder`)
  or parameter refinements exhausted admissible options under `max_sim_calls`.

Try increasing `--max-sim-calls` (up to `500`) or relaxing conflicting site
constraints (for example, `brine_disposal: false` combined with an infeasible
high-recovery brine-producing target without a Brine Concentrator allowance).

## Jobs, Web & Desktop

- **Jobs**: Check `hydroweaver_job_list`, `hydroweaver_job_status`, and
  `hydroweaver_job_manifest`. Set `HYDROWEAVER_JOBS_DIR` if reading an alternate
  job directory.
- **Web UI**: Copy the full `Local:` URL including the authentication fragment.
- **Desktop startup issues**: Run `npm start` from a terminal or rebuild with
  `npm run setup`.

## Reporting Bugs

File an issue at <https://github.com/zhaorui-bi/HydroWeaver/issues> with
redacted `hydroweaver doctor --json`, OS/Node/Python versions, minimal query JSON,
and bounded error logs.
