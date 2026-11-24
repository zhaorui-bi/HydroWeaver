"""Numerical operating-parameter optimizer under matched simulation budgets."""

from __future__ import annotations

import copy
from typing import Any, Callable

from .knowledge import UNIT_SPECS, default_parameters_for_chain
from .simulator import simulate_train

SimOracle = Callable[[list[str], dict[str, dict[str, float]]], dict[str, Any]]


def _flatten_decision_space(chain: list[str]) -> list[tuple[str, str, float, float]]:
    dims: list[tuple[str, str, float, float]] = []
    for unit in chain:
        spec = UNIT_SPECS.get(unit)
        if spec is None:
            continue
        for pspec in spec.params:
            dims.append((unit, pspec.name, pspec.lower, pspec.upper))
    return dims


def _pack_vector(dims: list[tuple[str, str, float, float]], params: dict[str, dict[str, float]]) -> list[float]:
    vec: list[float] = []
    for unit, pname, lo, hi in dims:
        val = float(params.get(unit, {}).get(pname, 0.5 * (lo + hi)))
        span = max(1e-9, hi - lo)
        vec.append(max(0.0, min(1.0, (val - lo) / span)))
    return vec


def _unpack_vector(dims: list[tuple[str, str, float, float]], vec: list[float]) -> dict[str, dict[str, float]]:
    params: dict[str, dict[str, float]] = {}
    for (unit, pname, lo, hi), u in zip(dims, vec):
        clamped = max(0.0, min(1.0, float(u)))
        params.setdefault(unit, {})[pname] = lo + clamped * (hi - lo)
    return params


def _objective(sim: dict[str, Any]) -> float:
    """Augmented feasibility-first + minimum-LCOW objective."""
    lcow = float(sim["economics"]["lcow_usd_m3"])
    rel_viol = float(sim["total_rel_violation"])
    hard_count = int(sim["hard_violation_count"])
    if hard_count == 0:
        return lcow
    return 100.0 + 40.0 * hard_count + 80.0 * rel_viol + 0.1 * lcow


def optimize_operating_parameters(
    case: dict[str, Any],
    chain: list[str],
    initial_params: dict[str, dict[str, float]] | None = None,
    *,
    max_evals: int = 24,
    sim_oracle: SimOracle | None = None,
) -> dict[str, Any]:
    """Optimize continuous operating parameters for a fixed treatment train within max_evals.

    Uses a pure-Python bounded coordinate-pattern + adaptive step-size search so it runs
    deterministically on any Python >= 3.10 environment and accounts for every single
    oracle simulation call against max_evals.
    """
    oracle: SimOracle = sim_oracle or (lambda c, p: simulate_train(case, c, p))
    base_params = copy.deepcopy(initial_params) if initial_params is not None else default_parameters_for_chain(chain, case)
    dims = _flatten_decision_space(chain)

    evals_used = 0
    best_params = base_params
    best_sim = oracle(chain, best_params)
    evals_used += 1
    best_obj = _objective(best_sim)

    if not dims or max_evals <= 1:
        return {
            "chain": list(chain),
            "best_params": best_params,
            "best_simulation": best_sim,
            "best_objective": round(best_obj, 5),
            "evals_used": evals_used,
            "converged": best_sim["feasible"],
            "improved": False,
        }

    x = _pack_vector(dims, best_params)
    n = len(x)
    step = 0.24
    improved_any = False

    # Synchronize Pumping pressure with RO/NF pressure dimension indices if both exist
    pump_idx = next((i for i, (u, p, _, _) in enumerate(dims) if u == "Pumping" and p == "feed_pressure_bar"), None)
    mem_p_idx = [i for i, (u, p, _, _) in enumerate(dims) if u in ("Reverse Osmosis", "Nanofiltration") and p == "feed_pressure_bar"]

    while evals_used < max_evals and step >= 0.025:
        x_start = list(x)
        round_improved = False
        for i in range(n):
            if evals_used >= max_evals:
                break
            unit_i, param_i, _, _ = dims[i]
            # Skip redundant membrane feed_pressure_bar when Pumping controls feed pressure
            if param_i == "feed_pressure_bar" and unit_i in ("Reverse Osmosis", "Nanofiltration") and pump_idx is not None:
                continue

            for direction in (1.0, -1.0):
                if evals_used >= max_evals:
                    break
                cand = list(x)
                cand[i] = max(0.0, min(1.0, x[i] + direction * step))
                if cand[i] == x[i]:
                    continue
                if i == pump_idx and mem_p_idx:
                    for mi in mem_p_idx:
                        cand[mi] = cand[i]
                cand_params = _unpack_vector(dims, cand)
                cand_sim = oracle(chain, cand_params)
                evals_used += 1
                cand_obj = _objective(cand_sim)
                if cand_obj < best_obj - 1e-6:
                    x = cand
                    best_params = cand_params
                    best_sim = cand_sim
                    best_obj = cand_obj
                    round_improved = True
                    improved_any = True
                    break

        # Hooke-Jeeves pattern extrapolation along improving joint direction
        if round_improved and evals_used < max_evals:
            pat = [max(0.0, min(1.0, x[k] + (x[k] - x_start[k]))) for k in range(n)]
            if pat != x:
                pat_params = _unpack_vector(dims, pat)
                pat_sim = oracle(chain, pat_params)
                evals_used += 1
                pat_obj = _objective(pat_sim)
                if pat_obj < best_obj - 1e-6:
                    x = pat
                    best_params = pat_params
                    best_sim = pat_sim
                    best_obj = pat_obj

        if not round_improved:
            step *= 0.5

    return {
        "chain": list(chain),
        "best_params": best_params,
        "best_simulation": best_sim,
        "best_objective": round(best_obj, 5),
        "evals_used": evals_used,
        "converged": bool(best_sim["feasible"]),
        "improved": improved_any,
        "final_step_norm": round(step, 4),
    }
