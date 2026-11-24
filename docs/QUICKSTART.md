# Quickstart

[简体中文](./zh-CN/QUICKSTART.md) | **English**

## 1. Prerequisites

- **Node.js ≥ 24.15.0** and **npm 12**
- **Python ≥ 3.10** (standard library only for the built-in scientific engine
  and AquaDesignGym)
- Optional: a separate Python environment with **WaterTAP / IDAES / Pyomo /
  IPOPT** if you plan to run `hydroweaver_simulate_train`

## 2. Install & Build

```bash
git clone https://github.com/zhaorui-bi/HydroWeaver.git
cd HydroWeaver

npm ci
npm run setup
```

`npm run setup` builds the TypeScript CLI/MCP bundle, terminal UI bundle, and
branded local Web UI.

## 3. Probe the Built-In Engine

No external repository or manual dataset download is needed:

```bash
./bin/hydroweaver doctor --probe
./bin/hydroweaver tools --json
```

If you want to pin a specific Python interpreter for `hydroweaver_cli.py`, pass
`--hydroweaver-python /path/to/python3` or export `HYDROWEAVER_PYTHON`.

## 4. Configure a Conversational Model Provider (Optional for CLI/TUI/Web Chat)

```bash
export DEEPSEEK_API_KEY="YOUR_KEY"
./bin/hydroweaver onboard --provider deepseek --api-key-env DEEPSEEK_API_KEY --yes
```

Direct backend optimization (`hydroweaver optimize`) and AquaDesignGym
benchmarking (`hydroweaver gym`) work offline with no conversational API key
needed.

## 5. Run Closed-Loop Joint Optimization

```bash
./bin/hydroweaver optimize \
  --input examples/cases/arsenic-groundwater.json \
  --top-k 3 \
  --max-rounds 4 \
  --max-sim-calls 60 \
  --wait
```

## 6. Explore AquaDesignGym

List the 12 standardized design tasks, admissible actions, perturbation regimes,
and 12 registered baselines/ablations:

```bash
./bin/hydroweaver gym tasks
```

Run a matched-budget evaluation (`max_sim_calls = 60`, reproducible seed):

```bash
./bin/hydroweaver gym eval --max-sim-calls 60 --seed 42 --wait
```

## 7. Interactive Workbench Surfaces

```bash
./bin/hydroweaver       # Full TUI
./bin/hydroweaver chat  # Plain terminal REPL
./bin/hydroweaver web   # Local Web UI (prints authenticated URL)
npm start               # Electron Desktop application
```

On Windows, replace `./bin/hydroweaver` with `npm run cli --`.
