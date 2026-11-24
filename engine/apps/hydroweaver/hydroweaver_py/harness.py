"""HydroWeaver closed-loop agent harness coordinating generation, optimization, simulation, and diagnosis."""

from __future__ import annotations

from typing import Any, Callable

from .diagnosis import apply_best_structural_edit, diagnose_simulation
from .history import SharedDesignHistory
from .knowledge import (
    TEMPLATE_PRIORS,
    UNIT_SPECS,
    build_case_assessment,
    canonicalize_chain,
    default_parameters_for_chain,
    knowledge_informed_candidates,
    retrieve_evidence,
    validate_and_normalize_query,
)
from .optimizer import optimize_operating_parameters
from .simulator import simulate_train

SimOracle = Callable[[list[str], dict[str, dict[str, float]]], dict[str, Any]]


def run_closed_loop_optimization(
    raw_query: dict[str, Any],
    *,
    initial_candidates: list[dict[str, Any]] | None = None,
    top_k: int = 3,
    max_rounds: int = 4,
    max_sim_calls: int = 60,
    enable_param_opt: bool = True,
    enable_struct_rev: bool = True,
    enable_diag_router: bool = True,
    enable_knowledge_priors: bool = True,
    enable_history: bool = True,
    sim_oracle: SimOracle | None = None,
) -> dict[str, Any]:
    """Run HydroWeaver's closed-loop joint configuration & operating-parameter optimization."""
    normalized, preservation = validate_and_normalize_query(raw_query)
    assessment = build_case_assessment(normalized)
    evidence = retrieve_evidence(normalized)

    sim_calls = 0

    def tracked_oracle(chain: list[str], params: dict[str, dict[str, float]]) -> dict[str, Any]:
        nonlocal sim_calls
        sim_calls += 1
        if sim_oracle is not None:
            return sim_oracle(chain, params)
        return simulate_train(normalized, chain, params)

    # 1. Knowledge-informed (or uninformed baseline) candidate generation
    if initial_candidates:
        candidates = []
        for idx, item in enumerate(initial_candidates, start=1):
            raw_chain = item.get("chain") if isinstance(item, dict) else item
            canon = canonicalize_chain(list(raw_chain))
            candidates.append(
                {
                    "chain_id": str(item.get("chain_id") if isinstance(item, dict) and item.get("chain_id") else f"caller-{idx}"),
                    "chain": canon,
                    "parameters": item.get("parameters") if isinstance(item, dict) else None,
                    "rationale": (item.get("rationale") if isinstance(item, dict) else None) or "Caller-supplied candidate train",
                }
            )
        initial_source = "caller"
    elif enable_knowledge_priors:
        candidates = knowledge_informed_candidates(normalized, top_k=top_k)
        initial_source = "knowledge-informed-generator"
    else:
        # Uninformed minimal baseline when knowledge priors are ablated
        candidates = [
            {
                "chain_id": "uninformed-1",
                "chain": ["Media Filtration"],
                "rationale": "Minimal uninformed initial train (knowledge priors ablated)",
            }
        ]
        initial_source = "uninformed-baseline"

    history = SharedDesignHistory()
    rounds_trace: list[dict[str, Any]] = []

    # Evaluate initial shortlist with default parameters
    active_pool: list[tuple[list[str], dict[str, dict[str, float]], dict[str, Any], bool]] = []
    for cand in candidates:
        if sim_calls >= max_sim_calls:
            break
        chain = canonicalize_chain(cand["chain"])
        params = cand.get("parameters") or default_parameters_for_chain(chain, normalized)
        sim = tracked_oracle(chain, params)
        diag = diagnose_simulation(normalized, sim, params_already_optimized=False)
        history.record(
            round_index=1,
            action="initial_evaluate",
            source=initial_source,
            chain=chain,
            parameters=params,
            simulation=sim,
            diagnosis=diag,
            sim_calls_total=sim_calls,
            note=cand.get("rationale", ""),
        )
        active_pool.append((chain, params, sim, False))

    if not active_pool:
        raise ValueError("Simulation budget exhausted before evaluating initial candidate.")

    # Pick most promising initial train (feasible lowest LCOW, else parametric-only over structural blockers)
    structural_blocker_codes = {
        "RES-CHEM-001", "RES-BRINE-001", "RES-SKILL-001", "SIM-MEM-PUMP", "SIM-COAG-001", "WQ-DISINF-UNIT",
    }

    def rank_key(item: tuple[list[str], dict[str, dict[str, float]], dict[str, Any], bool]) -> tuple[int, int, int, float, float]:
        sim_res = item[2]
        blocker_cnt = sum(1 for v in sim_res.get("violations", []) if v.get("code") in structural_blocker_codes)
        return (
            0 if sim_res["feasible"] else 1,
            blocker_cnt,
            int(sim_res["hard_violation_count"]),
            float(sim_res["total_rel_violation"]),
            float(sim_res["economics"]["lcow_usd_m3"]),
        )

    active_pool.sort(key=rank_key)
    cur_chain, cur_params, cur_sim, cur_optimized = active_pool[0]

    rounds_trace.append(
        {
            "round": 1,
            "source": initial_source,
            "action": "initial_evaluate",
            "chain": cur_chain,
            "feasible": cur_sim["feasible"],
            "lcow_usd_m3": cur_sim["economics"]["lcow_usd_m3"],
            "specific_energy_kWh_m3": cur_sim["flowsheet"]["specific_energy_kWh_m3"],
            "violations": cur_sim["violations"],
            "sim_calls_used": sim_calls,
        }
    )

    # 2. Closed-loop diagnosis -> (refine_parameters vs revise_structure)
    for round_idx in range(2, max_rounds + 1):
        if sim_calls >= max_sim_calls:
            break

        diag = diagnose_simulation(normalized, cur_sim, params_already_optimized=cur_optimized)
        if cur_sim["feasible"] and cur_optimized:
            break

        chosen = diag["recommended_action"]
        if cur_sim["feasible"] and not cur_optimized and enable_param_opt:
            # Polish cost/energy even after initial feasibility
            chosen = "refine_parameters"
        elif not enable_diag_router:
            # Blind alternation ablation when simulation-feedback routing is disabled
            chosen = "refine_parameters" if (round_idx % 2 == 0 and not cur_optimized) else "revise_structure"

        if chosen == "refine_parameters" and not enable_param_opt:
            chosen = "revise_structure"
        if chosen == "revise_structure" and not enable_struct_rev:
            chosen = "refine_parameters" if not cur_optimized and enable_param_opt else "stop"

        if chosen == "stop":
            break

        if chosen == "refine_parameters":
            remaining = max_sim_calls - sim_calls
            if remaining <= 1:
                break
            budget_here = min(remaining, max(10, min(18, remaining // 2)))
            opt_res = optimize_operating_parameters(
                normalized,
                cur_chain,
                cur_params,
                max_evals=budget_here,
                sim_oracle=tracked_oracle,
            )
            cur_params = opt_res["best_params"]
            cur_sim = opt_res["best_simulation"]
            cur_optimized = True
            next_diag = diagnose_simulation(normalized, cur_sim, params_already_optimized=True)
            history.record(
                round_index=round_idx,
                action="refine_parameters",
                source="numerical-parameter-optimizer",
                chain=cur_chain,
                parameters=cur_params,
                simulation=cur_sim,
                diagnosis=next_diag,
                sim_calls_total=sim_calls,
                note=f"Optimized parameters in {opt_res['evals_used']} evaluations (LCOW=${cur_sim['economics']['lcow_usd_m3']:.3f}/m3).",
            )
            rounds_trace.append(
                {
                    "round": round_idx,
                    "source": "numerical-parameter-optimizer",
                    "action": "refine_parameters",
                    "chain": cur_chain,
                    "feasible": cur_sim["feasible"],
                    "lcow_usd_m3": cur_sim["economics"]["lcow_usd_m3"],
                    "specific_energy_kWh_m3": cur_sim["flowsheet"]["specific_energy_kWh_m3"],
                    "violations": cur_sim["violations"],
                    "evals_in_round": opt_res["evals_used"],
                    "sim_calls_used": sim_calls,
                    "diagnosis_rationale": diag["rationale"],
                }
            )
            if cur_sim["feasible"]:
                break

        elif chosen == "revise_structure":
            seen = history.exhausted_topologies if enable_history else set()
            applied = apply_best_structural_edit(normalized, diag, seen)
            if applied is None:
                # Fallback: first try un-exhausted initial pool candidates, then unexplored KB templates
                fallback_chain = None
                for cand_c, _, _, _ in active_pool:
                    if tuple(cand_c) not in seen:
                        fallback_chain = cand_c
                        break
                if fallback_chain is None:
                    for tpl in TEMPLATE_PRIORS:
                        cand = tuple(canonicalize_chain(list(tpl.chain)))
                        if cand not in seen:
                            fallback_chain = list(cand)
                            break
                if fallback_chain is None:
                    break
                cur_chain = fallback_chain
                cur_params = default_parameters_for_chain(cur_chain, normalized)
                edit_meta = {"op": "template_switch", "reason": "Explored alternative KB template after exhausting local structural edits."}
            else:
                cur_chain, cur_params, edit_meta = applied

            if sim_calls >= max_sim_calls:
                break
            cur_sim = tracked_oracle(cur_chain, cur_params)
            cur_optimized = False
            next_diag = diagnose_simulation(normalized, cur_sim, params_already_optimized=False)
            history.record(
                round_index=round_idx,
                action="revise_structure",
                source="structural-revision",
                chain=cur_chain,
                parameters=cur_params,
                simulation=cur_sim,
                diagnosis=next_diag,
                sim_calls_total=sim_calls,
                note=str(edit_meta.get("reason") or ""),
            )
            rounds_trace.append(
                {
                    "round": round_idx,
                    "source": "structural-revision",
                    "action": "revise_structure",
                    "chain": cur_chain,
                    "edit": edit_meta,
                    "feasible": cur_sim["feasible"],
                    "lcow_usd_m3": cur_sim["economics"]["lcow_usd_m3"],
                    "specific_energy_kWh_m3": cur_sim["flowsheet"]["specific_energy_kWh_m3"],
                    "violations": cur_sim["violations"],
                    "sim_calls_used": sim_calls,
                    "diagnosis_rationale": diag["rationale"],
                }
            )
            # If newly revised structure still has parametric-only violations and budget remains, immediately let next round or inline optimize
            if cur_sim["feasible"] and enable_param_opt and sim_calls + 6 <= max_sim_calls and round_idx == max_rounds:
                opt_res = optimize_operating_parameters(
                    normalized,
                    cur_chain,
                    cur_params,
                    max_evals=min(10, max_sim_calls - sim_calls),
                    sim_oracle=tracked_oracle,
                )
                cur_params = opt_res["best_params"]
                cur_sim = opt_res["best_simulation"]
                history.record(
                    round_index=round_idx,
                    action="polish_parameters",
                    source="numerical-parameter-optimizer",
                    chain=cur_chain,
                    parameters=cur_params,
                    simulation=cur_sim,
                    diagnosis=diagnose_simulation(normalized, cur_sim, params_already_optimized=True),
                    sim_calls_total=sim_calls,
                    note="Cost-minimization polish after feasible structural revision.",
                )

    best = (history.best_feasible or history.best_overall) if enable_history else history.records[-1]
    assert best is not None
    feasible_records = [r for r in (history.records if enable_history else [history.records[-1]]) if r["feasible"]]
    unique_feasible: list[dict[str, Any]] = []
    seen_feasible_chains: set[tuple[str, ...]] = set()
    for rec in sorted(feasible_records, key=lambda r: r["lcow_usd_m3"]):
        sig = tuple(rec["chain"])
        if sig in seen_feasible_chains:
            continue
        seen_feasible_chains.add(sig)
        unique_feasible.append(
            {
                "chain_id": f"feasible-{len(unique_feasible) + 1}",
                "chain": rec["chain"],
                "parameters": rec["parameters"],
                "lcow_usd_m3": rec["lcow_usd_m3"],
                "specific_energy_kWh_m3": rec["specific_energy_kWh_m3"],
                "recovery_fraction": rec["recovery_fraction"],
                "economics": rec["simulation"]["economics"],
                "effluent": rec["simulation"]["effluent"],
                "flowsheet": rec["simulation"]["flowsheet"],
                "constraint_report": {
                    "overall_status": "PASS",
                    "violations": [],
                },
            }
        )

    opt_status = (
        "feasible"
        if unique_feasible
        else "budget_exhausted"
        if (len(rounds_trace) >= max_rounds or sim_calls >= max_sim_calls)
        else "stalled"
    )

    unresolved = [] if unique_feasible else best["violations"]

    return {
        "kind": "hydroweaver.closed-loop-optimization",
        "query_id": normalized.get("query_id"),
        "normalized_query": normalized,
        "context_preservation": preservation,
        "case_assessment": assessment,
        "evidence": evidence,
        "optimization": {
            "status": opt_status,
            "rounds_used": len(rounds_trace),
            "max_rounds": max_rounds,
            "sim_calls_used": sim_calls,
            "max_sim_calls": max_sim_calls,
            "top_k": top_k,
            "initial_source": initial_source,
            "feasible_chains": len(unique_feasible),
            "best_lcow_usd_m3": best["lcow_usd_m3"],
            "best_sec_kwh_m3": best["specific_energy_kWh_m3"],
            "unresolved_count": len(unresolved),
            "unresolved": unresolved,
        },
        "rounds": rounds_trace,
        "design_history": history.summary_records(),
        "final_trains": unique_feasible[:top_k],
        "best_design": {
            "chain": best["chain"],
            "parameters": best["parameters"],
            "feasible": best["feasible"],
            "lcow_usd_m3": best["lcow_usd_m3"],
            "specific_energy_kWh_m3": best["specific_energy_kWh_m3"],
            "effluent": best["simulation"]["effluent"],
            "flowsheet": best["simulation"]["flowsheet"],
            "economics": best["simulation"]["economics"],
            "violations": best["violations"],
        },
        "limitations": [
            "HydroWeaver optimizes treatment-train configurations and operating parameters against steady-state mechanistic correlations and declared water-quality, resource, and cost constraints.",
            "Feasible designs remain early-stage conceptual solutions; pilot treatability testing, detailed hydraulic design, and regulatory review are required before implementation.",
        ],
    }


def build_recommendation_report(
    raw_query: dict[str, Any],
    *,
    top_k: int = 3,
    max_rounds: int = 3,
) -> dict[str, Any]:
    """Generate a structured, evidence-bound recommendation report using HydroWeaver's KB + simulation."""
    opt = run_closed_loop_optimization(raw_query, top_k=top_k, max_rounds=max_rounds)
    normalized = opt["normalized_query"]
    evidence_bundle = opt["evidence"]
    unit_ev_map = {item["unit"]: item for item in evidence_bundle.get("kb_unit", []) if "unit" in item}

    recommendations: list[dict[str, Any]] = []
    source_records = opt["final_trains"] or [
        {
            "chain_id": "best-candidate-1",
            "chain": opt["best_design"]["chain"],
            "parameters": opt["best_design"]["parameters"],
            "lcow_usd_m3": opt["best_design"]["lcow_usd_m3"],
            "specific_energy_kWh_m3": opt["best_design"]["specific_energy_kWh_m3"],
            "economics": opt["best_design"]["economics"],
            "effluent": opt["best_design"]["effluent"],
            "flowsheet": opt["best_design"]["flowsheet"],
            "constraint_report": {
                "overall_status": "PASS" if opt["best_design"]["feasible"] else "FAIL",
                "violations": opt["best_design"]["violations"],
            },
        }
    ]

    for idx, train in enumerate(source_records[:top_k], start=1):
        chain = train["chain"]
        citations = []
        for unit in chain:
            spec = UNIT_SPECS.get(unit)
            if spec is not None:
                ev = unit_ev_map.get(unit)
                citations.append(
                    {
                        "support_type": "evidence_backed",
                        "claim": f"{unit} contributes {', '.join(spec.mechanisms)} for {', '.join(spec.target_contaminants) or 'hydraulic support'}.",
                        "source_id": spec.evidence_id,
                        "chunk_id": (ev or {}).get("chunk_id") or f"{spec.evidence_id}:unit",
                        "text_excerpt": spec.evidence_summary,
                    }
                )
        citations.append(
            {
                "support_type": "system_inference",
                "claim": f"Simulated steady-state LCOW is ${train['lcow_usd_m3']:.3f}/m³ with specific energy {train['specific_energy_kWh_m3']:.2f} kWh/m³.",
                "source_id": "hydroweaver-simulator",
                "chunk_id": "sim-eval",
                "text_excerpt": "Calculated from steady-state mass balance, hydraulic head, and annualized CAPEX/OPEX equations.",
            }
        )
        recommendations.append(
            {
                "chain_id": train.get("chain_id") or f"train-{idx}",
                "chain": chain,
                "key_units": chain[:3],
                "parameters": train.get("parameters"),
                "economics": train.get("economics"),
                "flowsheet": train.get("flowsheet"),
                "effluent": train.get("effluent"),
                "why_it_works": f"Selected train {' -> '.join(chain)} achieves simulated LCOW ${train['lcow_usd_m3']:.3f}/m³ and SEC {train['specific_energy_kWh_m3']:.2f} kWh/m³ under declared case constraints.",
                "evidence": citations,
                "assumptions": normalized.get("assumptions") or ["Steady-state nominal influent conditions assumed unless perturbed."],
                "constraint_report": train.get("constraint_report") or {"overall_status": "PASS", "violations": []},
                "uncertainty": "low" if train.get("constraint_report", {}).get("overall_status") == "PASS" and not normalized.get("missing_fields") else "medium",
            }
        )

    return {
        "kind": "hydroweaver.recommendation-report",
        "query_id": normalized.get("query_id"),
        "pipeline_version": "0.3.0-beta.1",
        "normalized_query": normalized,
        "context_preservation": opt["context_preservation"],
        "case_assessment": opt["case_assessment"],
        "retrieval": evidence_bundle,
        "recommendations": recommendations,
        "optimization_summary": opt["optimization"],
    }
