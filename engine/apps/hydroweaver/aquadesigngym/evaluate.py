"""AquaDesignGym matched-budget evaluation protocol: baselines, ablations, and robustness."""

from __future__ import annotations

import statistics
from typing import Any

from hydroweaver_py.simulator import simulate_train
from .baselines import METHOD_REGISTRY, run_method
from .tasks import BENCHMARK_TASKS, apply_influent_perturbation, get_task


def _compute_aufbc(curve: list[dict[str, Any]], max_budget: int) -> float:
    """Area Under the Feasibility-vs-Budget Curve normalized to [0, 1]."""
    if not curve or max_budget <= 0:
        return 0.0
    feasible_at_budget = [0.0] * max_budget
    last_val = 0.0
    curve_by_call = {int(pt["sim_call"]): 1.0 if pt.get("best_feasible") else 0.0 for pt in curve}
    for step in range(1, max_budget + 1):
        if step in curve_by_call:
            last_val = curve_by_call[step]
        feasible_at_budget[step - 1] = last_val
    return round(sum(feasible_at_budget) / float(max_budget), 4)


def _aggregate_episodes(episodes: list[dict[str, Any]], max_sim_calls: int) -> dict[str, Any]:
    n = len(episodes)
    if n == 0:
        return {"tasks": 0}
    feasible_eps = [ep for ep in episodes if ep["feasible"]]
    fdr = len(feasible_eps) / float(n)
    lcows = [ep["best_lcow_usd_m3"] for ep in feasible_eps if ep["best_lcow_usd_m3"] is not None]
    secs = [ep["best_sec_kwh_m3"] for ep in feasible_eps if ep["best_sec_kwh_m3"] is not None]
    s2fs = [ep["first_feasible_sim_call"] for ep in feasible_eps if ep["first_feasible_sim_call"] is not None]
    aufbcs = [_compute_aufbc(ep.get("feasibility_curve") or [], max_sim_calls) for ep in episodes]

    # Feasibility at checkpoints
    checkpoints = [b for b in (5, 15, 30, max_sim_calls) if b <= max_sim_calls]
    fdr_at_b: dict[str, float] = {}
    for b in checkpoints:
        solved_b = sum(
            1
            for ep in episodes
            if ep["first_feasible_sim_call"] is not None and ep["first_feasible_sim_call"] <= b
        )
        fdr_at_b[f"FDR@{b}"] = round(solved_b / float(n), 4)

    return {
        "tasks": n,
        "feasible_count": len(feasible_eps),
        "feasible_design_rate": round(fdr, 4),
        "mean_feasible_lcow_usd_m3": round(statistics.mean(lcows), 4) if lcows else None,
        "mean_feasible_sec_kwh_m3": round(statistics.mean(secs), 4) if secs else None,
        "mean_sim_to_first_feasible": round(statistics.mean(s2fs), 2) if s2fs else None,
        "mean_sim_calls_used": round(statistics.mean(ep["sim_calls_used"] for ep in episodes), 2),
        "aufbc": round(statistics.mean(aufbcs), 4),
        **fdr_at_b,
    }


def evaluate_benchmark(
    *,
    methods: list[str] | None = None,
    task_ids: list[str] | None = None,
    perturbations: list[str] | None = None,
    max_sim_calls: int = 60,
    seed: int = 42,
    include_zero_shot_transfer: bool = True,
) -> dict[str, Any]:
    """Run the AquaDesignGym matched-budget evaluation protocol across methods and influent shifts."""
    selected_methods = methods or list(METHOD_REGISTRY.keys())
    selected_tasks = task_ids or [t["task_id"] for t in BENCHMARK_TASKS]
    selected_perturbations = perturbations or ["nominal", "mild_shift", "severe_shift"]

    for m in selected_methods:
        if m not in METHOD_REGISTRY:
            raise ValueError(f"Unknown method: {m}")

    results_by_method: dict[str, Any] = {}
    raw_episodes: list[dict[str, Any]] = []

    for method in selected_methods:
        per_profile: dict[str, list[dict[str, Any]]] = {p: [] for p in selected_perturbations}
        zero_shot_retention: dict[str, dict[str, Any]] = {}

        for profile in selected_perturbations:
            for tid in selected_tasks:
                ep = run_method(
                    method,
                    tid,
                    perturbation=profile,
                    max_sim_calls=max_sim_calls,
                    seed=seed,
                )
                ep["method"] = method
                per_profile[profile].append(ep)
                raw_episodes.append(ep)

        # Zero-shot robustness: take nominal design for each task and evaluate directly on perturbed influents
        if include_zero_shot_transfer and "nominal" in per_profile:
            nominal_by_task = {ep["task_id"]: ep for ep in per_profile["nominal"]}
            for profile in selected_perturbations:
                if profile == "nominal":
                    continue
                retained = 0
                eligible = 0
                worst_viol = 0.0
                for tid in selected_tasks:
                    nom = nominal_by_task[tid]
                    if not nom["feasible"] or not nom["best_chain"]:
                        continue
                    eligible += 1
                    perturbed_task = apply_influent_perturbation(get_task(tid), profile)
                    transfer_sim = simulate_train(perturbed_task, nom["best_chain"], nom["best_parameters"])
                    if transfer_sim["feasible"]:
                        retained += 1
                    worst_viol = max(worst_viol, float(transfer_sim["total_rel_violation"]))
                zero_shot_retention[profile] = {
                    "nominal_feasible_count": eligible,
                    "zero_shot_feasible_count": retained,
                    "zero_shot_retention_rate": round(retained / float(eligible), 4) if eligible else 0.0,
                    "worst_case_rel_violation": round(worst_viol, 4),
                }

        profile_summaries = {
            profile: _aggregate_episodes(eps, max_sim_calls)
            for profile, eps in per_profile.items()
        }
        results_by_method[method] = {
            "family": METHOD_REGISTRY[method]["family"],
            "description": METHOD_REGISTRY[method]["description"],
            "by_perturbation": profile_summaries,
            "zero_shot_robustness": zero_shot_retention,
        }

    return {
        "kind": "hydroweaver.aquadesigngym-evaluation",
        "schema_version": 1,
        "protocol": {
            "matched_max_sim_calls": max_sim_calls,
            "task_count": len(selected_tasks),
            "task_ids": selected_tasks,
            "perturbations": selected_perturbations,
            "seed": seed,
        },
        "methods": results_by_method,
        "episodes": raw_episodes,
    }
