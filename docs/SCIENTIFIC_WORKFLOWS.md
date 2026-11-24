# Scientific Workflows & AquaDesignGym Protocol

[简体中文](./zh-CN/DOMAIN_WORKFLOW.md) | **English**

HydroWeaver treats water-treatment process synthesis as a closed-loop joint
optimization problem over **discrete unit topologies** and **continuous
operating parameters**, audited for semantic fidelity and reproducibility.

## 1. End-to-End Case Workflow

1. **Ready & Taxonomy Check**: Inspect engine health and verify canonical unit
   and contaminant identifiers via `hydroweaver_status` and `hydroweaver_catalog`.
2. **Case Assessment & Semantic Preservation (`hydroweaver_assess_case`)**:
   Preserve explicit measurement bases (`nitrate_basis: as NO3 vs. as N`,
   `hardness_basis: as CaCO3`, `arsenic_speciation: As(III) vs. As(V)`), design
   flow, and site resource limits (`brine_disposal`, `max_sec_kwh_m3`,
   `max_lcow_usd_m3`). Flag `blocked` or `needs_information` items clearly.
3. **Evidence Retrieval (`hydroweaver_retrieve_evidence`)**: Retrieve hybrid
   lexical + structured evidence chunks from HydroWeaver’s unit/template
   knowledge corpus and any locally staged `kb_unit` / `kb_case` records under
   `HYDROWEAVER_HOME/ingest`.
4. **Joint Closed-Loop Optimization (`hydroweaver_optimize_trains`)**:
   Coordinates:
   - knowledge-informed configuration priors,
   - bounded coordinate + Hooke–Jeeves parameter refinement (`refine_parameters`),
   - mechanistic + LCOW process simulation,
   - simulation-feedback violation diagnosis (`revise_structure` via add,
     remove, replace, reorder when structural blockers exist),
   - `SharedDesignHistory` cycle avoidance within `maxSimCalls`.
5. **Optional Flowsheet NLP (`hydroweaver_simulate_train`)**: When
   `HYDROWEAVER_SIM_PYTHON` is configured, validate hydraulics/costing or solve
   an IPOPT NLP minimizing LCOW (`optimizeDesign=true`).
6. **Audit & Research Handoff (`hydroweaver_audit_report`, `hydroweaver_job_manifest`)**:
   Audit evidence bindings, constraint feasibility, and SHA-256 run provenance.

## 2. AquaDesignGym Benchmark Environment

AquaDesignGym (`engine/apps/hydroweaver/aquadesigngym/`) couples 12 standardized
design tasks with an interactive transition API (`AquaDesignGymEnv`) and a
strict simulation-call budget (`max_sim_calls`):

### Tasks (`ADG-01` through `ADG-12`)

- **Groundwater & Trace Contaminants**: `ADG-01-AS-RURAL` (As(III), rural
  constraints, no brine), `ADG-02-AS-NO3-ZERO-BRINE`, `ADG-03-NITRATE-SMALL`,
  `ADG-07-PFAS-TRACE` (PFAS/trace organics), `ADG-11-VOC-AIR`.
- **High-Salinity, Reuse & Scaling**: `ADG-04-BWRO-SCALING` (brackish RO with
  high hardness/silica scaling), `ADG-05-INDUSTRIAL-REUSE` (RO/NF cooling makeup,
  zero-brine/concentrator constraint), `ADG-06-HIGH-FOULING-SW` (high-turbidity
  surface water), `ADG-10-SEAWATER-RO` (high-salinity SWRO + energy cap).
- **Disinfection & Multi-Contaminant Surface Water**: `ADG-08-DBP-SURFACE`
  (NOM/DBP risk), `ADG-09-PATHOGEN-CHEMFREE` (chemical-free disinfection),
  `ADG-12-MULTI-CONTAM` (As(III) + hardness + NOM + PFAS + pathogen).

### Admissible Action Space (9 Actions)

| Action | Category | Semantics |
| --- | --- | --- |
| `set_chain` | Structural | Replace the unit sequence with a canonicalized train. |
| `add_unit` | Structural | Insert a treatment unit at stage order or specified index. |
| `remove_unit` | Structural | Remove a redundant or mismatched unit. |
| `replace_unit` | Structural | Swap a conflicting unit for an admissible alternative. |
| `reorder_chain` | Structural | Reorder units according to physical stage order. |
| `set_parameters` | Parametric | Assign operating variables on specific units. |
| `refine_parameters` | Optimization | Invoke bounded Hooke–Jeeves parameter search under a sub-budget. |
| `step_simulate` | Evaluation | Evaluate the active train and parameters (consumes 1 oracle call). |
| `stop` | Termination | Terminate the episode and lock final episode metrics. |

### Comparative Protocol

Under a matched `max_sim_calls` oracle budget and seed, `evaluate_benchmark`:

- evaluates **HydroWeaver** against **3 agent baselines** (`OneShotKnowledge`,
  `RuleCriticLoop`, `ReActBlindAgent`), **3 conventional optimizers**
  (`EvolutionaryMINLP`, `TemplateGridSearch`, `RandomSearch`), and **5 component
  ablations** (`HW-NoParamOpt`, `HW-NoStructRev`, `HW-NoDiagRouter`,
  `HW-NoKnowledge`, `HW-NoHistory`);
- evaluates robustness across **nominal**, **mild_shift**, and **severe_shift**
  influent perturbations (re-simulating synthesized policies zero-shot on drifted
  feed water);
- reports Feasible-Design Rate (`FDR`), mean feasible `LCOW ($/m³)`, mean
  feasible `SEC (kWh/m³)`, Simulations-to-Feasibility (`S2F`), Area Under the
  Feasibility–Budget Curve (`AUFBC`), and perturbation feasible retention.

## 3. Interpretive Boundaries

- A `feasible` status inside HydroWeaver’s mechanistic engine or AquaDesignGym
  means every modeled quality, resource, and cost constraint is satisfied in
  simulation; it is **not** a substitute for laboratory treatability studies,
  piloting, or regulatory permitting.
- See [cases README](../examples/cases/arsenic-groundwater.json) and
  [WaterTAP simulation docs](./SIMULATION.md) for scope limits.
