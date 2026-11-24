---
name: hydroweaver-campaign
description: Plan, pilot, compare, ablate, and report reproducible HydroWeaver closed-loop water-treatment studies and AquaDesignGym evaluations across tasks, matched simulation budgets, baselines, component ablations, and varying influent perturbations. Do not use for a single routine query or job status check.
---

# Reproducible HydroWeaver & AquaDesignGym Campaigns

Use `hydroweaver-campaign` for multi-task benchmarking, method comparisons
against conventional optimizers and baseline agents, component ablations, and
varying-influent robustness studies under matched simulation budgets.

## Experimental Protocol

1. **Declare Experimental Factors Explicitly**:
   - Task subset (`ADG-01` through `ADG-12` via `hydroweaver_gym_tasks`);
   - Perturbation regimes (`nominal`, `mild_shift`, `severe_shift`);
   - Matched simulation-call budget (`maxSimCalls`, default `60`) and seed;
   - Compared methods (`HydroWeaver`, `OneShotKnowledge`, `RuleCriticLoop`,
     `ReActBlindAgent`, `EvolutionaryMINLP`, `TemplateGridSearch`,
     `RandomSearch`, and ablations `HW-NoParamOpt`, `HW-NoStructRev`,
     `HW-NoDiagRouter`, `HW-NoKnowledge`, `HW-NoHistory`).
2. **Pilot Before Sweeping**:
   Run a small subset (for instance 1–2 methods on `nominal`) before launching a
   full multi-perturbation matrix across all 12 tasks and 12 methods.
3. **Report Matched Metrics Honestly**:
   Record Feasible-Design Rate (`FDR`), mean feasible `LCOW ($/m³)`, mean
   feasible `SEC (kWh/m³)`, Simulations-to-Feasibility (`S2F`), Area Under
   Feasibility–Budget Curve (`AUFBC`), and zero-shot perturbation retention.
4. **Preserve Provenance**:
   Inspect `hydroweaver_job_manifest` for run SHA-256 hashes, seed, `maxSimCalls`,
   and optional benchmark directory fingerprints before summarizing results.

Always state clearly that AquaDesignGym results come from HydroWeaver’s
computational process-simulation oracle and must not be represented as
field-validated plant compliance.
