---
name: hydroweaver
description: Create or resume a persistent, gated water-treatment case-to-report research task, or run standalone HydroWeaver operations such as readiness checks, taxonomy lookup, query normalization, case assessment, local evidence retrieval, closed-loop joint optimization, constraint simulation and diagnosis, report auditing, indexing, knowledge staging, AquaDesignGym evaluation, or durable-job inspection. For multi-method benchmark suites or repeated comparisons, use hydroweaver-campaign.
---

# HydroWeaver Closed-Loop Water-Treatment Operations

HydroWeaver is a standalone agentic framework for **jointly designing water
treatment train configurations and continuous operating parameters** under
water-quality, resource, and cost constraints (`hydroweaver_py` + optional
WaterTAP/IPOPT flowsheet simulation + `aquadesigngym`).

## Core Operating Discipline

1. Check readiness and canonical names with `hydroweaver_status` and
   `hydroweaver_catalog`.
2. Call `hydroweaver_assess_case` before synthesis when influent quality,
   speciation, reporting bases (`as NO3` vs `as N`, `as CaCO3`), targets,
   flow, or resource caps may have critical gaps. Never invent missing inputs.
3. Preserve exact `extra` measurement-basis fields across queries.
4. Distinguish between:
   - retrieved evidence chunks (`hydroweaver_retrieve_evidence`),
   - standalone mechanistic simulation & constraint checks
     (`hydroweaver_check_constraints`),
   - closed-loop joint configuration + parameter optimization
     (`hydroweaver_optimize_trains`), and
   - optional WaterTAP/IPOPT NaCl flowsheet optimization
     (`hydroweaver_simulate_train`).
5. When using `hydroweaver_research_create` / `hydroweaver_research_advance` for
   durable end-to-end tasks, inspect controller job artifacts and
   `hydroweaver_audit_report` scientific status rather than re-launching stage
   jobs manually.

## Tool Groups

- **Readiness & Taxonomy**: `hydroweaver_status`, `hydroweaver_catalog`,
  `hydroweaver_normalize_query`, `hydroweaver_assess_case`.
- **Evidence & Knowledge Staging**: `hydroweaver_retrieve_evidence`,
  `hydroweaver_build_indexes`, `hydroweaver_ingest_knowledge`.
- **Joint Design & Simulation**:
  - `hydroweaver_check_constraints`: simulate candidates and diagnose
    `water_quality`, `resource`, `cost`, and `integrity` violations.
  - `hydroweaver_optimize_trains`: run closed-loop configuration generation,
    bounded coordinate + Hooke–Jeeves parameter refinement, mechanistic
    simulation, violation-driven `refine_parameters` / `revise_structure`
    routing, and `SharedDesignHistory` within a declared `maxSimCalls` budget.
  - `hydroweaver_simulate_train`: optional WaterTAP/IDAES/Pyomo/IPOPT NaCl
    flowsheet solve (`optimizeDesign=true` minimizes `WaterTAPCosting.LCOW`).
- **Audit & AquaDesignGym**:
  - `hydroweaver_audit_report`: audit claim citations and feasibility.
  - `hydroweaver_gym_tasks` & `hydroweaver_evaluate_gym`: inspect and run the
    matched-budget AquaDesignGym benchmark protocol.
- **Durable Control**: `hydroweaver_research_*` and `hydroweaver_job_*`.
