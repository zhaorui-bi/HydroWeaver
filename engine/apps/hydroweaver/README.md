# HydroWeaver Engine Package

**Version: `0.3.0-beta.1`**

`engine/apps/hydroweaver` contains HydroWeaver’s TypeScript CLI/TUI/Web/MCP
runtime (`src/`) together with its standalone Python scientific engine
(`hydroweaver_py/`), the **AquaDesignGym** benchmark suite (`aquadesigngym/`),
and optional WaterTAP/IDAES/Pyomo/IPOPT flowsheet optimization (`sim/`).

## Commands

| Command | Purpose |
| --- | --- |
| `hydroweaver` | Launch the interactive TUI. |
| `hydroweaver run "<prompt>"` | Create one session with HydroWeaver MCP tools, stream a turn, and exit. |
| `hydroweaver chat` | Persistent REPL session. |
| `hydroweaver web [--port N]` | Start the local authenticated Web UI server. |
| `hydroweaver onboard [options]` | Configure `~/.hydroweaver`, API model provider, Python engine override, MCP, and skills. |
| `hydroweaver doctor [--probe]` | Check Node.js, workspace paths, Python engine health, MCP, and optional WaterTAP readiness. |
| `hydroweaver tools [--json]` | Inspect the 26 MCP tools and their annotations. |
| `hydroweaver optimize --input FILE` | Run closed-loop joint configuration & parameter optimization (`--top-k`, `--max-rounds`, `--max-sim-calls`, `--wait`). |
| `hydroweaver gym tasks` | Inspect AquaDesignGym tasks, admissible actions, perturbations, baselines, and ablations. |
| `hydroweaver gym eval` | Run the matched-budget AquaDesignGym evaluation protocol across baselines and ablations. |
| `hydroweaver research <action>` | Control a durable multi-stage research task (`create`, `status`, `list`, `advance`, `respond`, `cancel`). |

## Environment Variables

- `HYDROWEAVER_HOME` — User config, credentials, and `mcp.json` directory (default `~/.hydroweaver`).
- `HYDROWEAVER_PYTHON` — Optional explicit Python 3 interpreter for `backend/hydroweaver_cli.py`.
- `HYDROWEAVER_COMMAND` — Optional JSON command override for `hydroweaver_cli.py`.
- `HYDROWEAVER_SIM_PYTHON` — Optional Python environment containing `watertap`, `idaes`, `pyomo`, and `ipopt`.
- `HYDROWEAVER_WORKDIR` — Default workspace for outputs and jobs.
- `HYDROWEAVER_JOBS_DIR` — Explicit job store override.

## License

MIT — see [../../LICENSE](../../LICENSE).
