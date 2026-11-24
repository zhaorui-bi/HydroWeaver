# Frequently Asked Questions

[简体中文](./zh-CN/FAQ.md) | **English**

### What is HydroWeaver?

HydroWeaver is a standalone agentic workbench for jointly designing
water-treatment train configurations and continuous operating parameters under
water-quality, resource, and cost constraints, paired with the **AquaDesignGym**
benchmarking environment and optional **WaterTAP** process simulation.

### Does HydroWeaver require any external repository or dataset?

No. HydroWeaver includes its own complete Python scientific engine
(`hydroweaver_py`), local knowledge corpus & staging indexes, and the
AquaDesignGym benchmark (`aquadesigngym`), all runnable using Python 3.10+
standard library alone.

### How does the closed-loop optimizer differ from one-shot prompting?

One-shot generation picks plausible unit names without verifying quantitative
mass balances, osmotic pressure, scaling (`hardness × CF`), fouling, CT
disinfection, brine limits, SEC, or LCOW. HydroWeaver couples:

1. knowledge-informed candidate generation,
2. bounded coordinate + Hooke–Jeeves numerical operating-parameter optimization,
3. mechanistic simulation & violation diagnosis,
4. routing between `refine_parameters` and `revise_structure`, and
5. a `SharedDesignHistory` preventing cyclic structural edits.

### What is AquaDesignGym?

AquaDesignGym evaluates competing synthesis methods (HydroWeaver, conventional
optimizers, agent baselines, and component ablations) under matched simulation
call budgets (`max_sim_calls`) across 12 standardized tasks and 3 influent
perturbation regimes (`nominal`, `mild_shift`, `severe_shift`).

### What is the role of `HYDROWEAVER_SIM_PYTHON`?

By default, HydroWeaver runs its fast pure-Python mechanistic & costing engine
(`hydroweaver_optimize_trains`, `hydroweaver_check_constraints`). When
`HYDROWEAVER_SIM_PYTHON` points to an environment containing `watertap`,
`idaes-pse`, `pyomo`, and `ipopt`, `hydroweaver_simulate_train` builds real
WaterTAP flowsheets with `WaterTAPCosting` and supports `optimizeDesign=true`
NLP solving.

### Are designs ready for direct plant construction?

No. Simulation feasibility within HydroWeaver’s mechanistic models verifies
declared numerical constraints for early-stage engineering screening and
benchmarking only. Real deployment requires expert engineering review,
treatability/pilot testing, and regulatory compliance verification.

### Where are jobs and outputs stored?

By default under `<workdir>/hydroweaver-jobs/` and `<workdir>/hydroweaver-output/`.
Inspect them with `hydroweaver_job_list`, `hydroweaver_job_manifest`, and
`hydroweaver_job_artifacts`.

### Does HydroWeaver require an API login or OAuth?

No. Offline optimization (`hydroweaver optimize`, `hydroweaver gym`) needs no
LLM key at all. Interactive chat surfaces (`hydroweaver`, `chat`, `web`) use
standard API-key providers configured via `hydroweaver onboard` or `/provider`.

### How do I report issues?

Open an issue at <https://github.com/zhaorui-bi/HydroWeaver/issues> with
redacted `hydroweaver doctor --json`, OS/Node/Python versions, and a minimal
reproduction case. See [SECURITY.md](../SECURITY.md) for vulnerabilities.
