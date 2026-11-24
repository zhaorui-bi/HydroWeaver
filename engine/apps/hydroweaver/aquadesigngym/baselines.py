"""Comparative baselines, conventional optimizers, and HydroWeaver component ablations."""

from __future__ import annotations

import copy
import random
from typing import Any

from hydroweaver_py.harness import run_closed_loop_optimization
from hydroweaver_py.knowledge import (
    CANONICAL_UNITS,
    TEMPLATE_PRIORS,
    UNIT_SPECS,
    canonicalize_chain,
    default_parameters_for_chain,
    knowledge_informed_candidates,
)
from .env import AquaDesignGymEnv, SimulationBudgetExhausted


def _random_params(chain: list[str], rng: random.Random) -> dict[str, dict[str, float]]:
    params: dict[str, dict[str, float]] = {}
    for unit in chain:
        spec = UNIT_SPECS.get(unit)
        if spec is None:
            continue
        params[unit] = {
            p.name: rng.uniform(p.lower, p.upper)
            for p in spec.params
        }
    return params


def _run_hydroweaver_variant(
    env: AquaDesignGymEnv,
    *,
    enable_param_opt: bool = True,
    enable_struct_rev: bool = True,
    enable_diag_router: bool = True,
    enable_knowledge_priors: bool = True,
    enable_history: bool = True,
) -> dict[str, Any]:
    """Run HydroWeaver (or an ablated variant) inside AquaDesignGymEnv under matched budget."""

    def env_oracle(chain: list[str], params: dict[str, dict[str, float]]) -> dict[str, Any]:
        return env._call_oracle(chain, params)

    try:
        res = run_closed_loop_optimization(
            env.task,
            top_k=3,
            max_rounds=12,
            max_sim_calls=env.max_sim_calls,
            enable_param_opt=enable_param_opt,
            enable_struct_rev=enable_struct_rev,
            enable_diag_router=enable_diag_router,
            enable_knowledge_priors=enable_knowledge_priors,
            enable_history=enable_history,
            sim_oracle=env_oracle,
        )
        if not enable_history:
            summary = env.episode_summary()
            best = res["best_design"]
            summary["feasible"] = bool(best["feasible"])
            summary["best_chain"] = best["chain"]
            summary["best_lcow_usd_m3"] = best["lcow_usd_m3"] if best["feasible"] else None
            summary["best_sec_kwh_m3"] = best["specific_energy_kWh_m3"] if best["feasible"] else None
            return summary
    except SimulationBudgetExhausted:
        pass
    return env.episode_summary()


def _run_one_shot_knowledge(env: AquaDesignGymEnv, seed: int = 0) -> dict[str, Any]:
    """Baseline: single-pass plausible knowledge-informed train with default parameters."""
    cands = knowledge_informed_candidates(env.task, top_k=1)
    chain = cands[0]["chain"]
    env.step({"type": "propose_train", "units": chain, "evaluate": True})
    env.step({"type": "submit"})
    return env.episode_summary()


def _run_rule_critic_loop(env: AquaDesignGymEnv, seed: int = 0) -> dict[str, Any]:
    """Baseline: static rule-based critic repairs without simulation feedback or parameter opt."""
    cands = knowledge_informed_candidates(env.task, top_k=3)
    constraints = env.task.get("constraints") or {}
    chem_allowed = constraints.get("chemical_dosing_allowed") is not False
    brine_allowed = constraints.get("brine_disposal") is not False
    use_drinking = constraints.get("use_for_drinking") is not False

    for cand in cands:
        if env.sim_calls_used >= env.max_sim_calls:
            break
        chain = list(cand["chain"])
        if not chem_allowed:
            chain = [u for u in chain if not UNIT_SPECS[u].requires_chemical_dosing]
        if not brine_allowed:
            chain = [u for u in chain if not UNIT_SPECS[u].generates_brine]
        if use_drinking and not any(UNIT_SPECS[u].provides_disinfection for u in chain):
            chain.append("Chlorination" if chem_allowed else "UV Disinfection")
        if not chain:
            chain = ["Media Filtration", "Adsorption", "UV Disinfection"]
        chain = canonicalize_chain(chain)
        try:
            env.step({"type": "propose_train", "units": chain, "evaluate": True})
        except SimulationBudgetExhausted:
            break
    return env.episode_summary()


def _run_react_blind_agent(env: AquaDesignGymEnv, seed: int = 0) -> dict[str, Any]:
    """Baseline: iterative ReAct-style trial mutations without diagnosis router or numerical optimizer."""
    rng = random.Random(seed)
    cands = knowledge_informed_candidates(env.task, top_k=1)
    chain = list(cands[0]["chain"])
    try:
        env.step({"type": "propose_train", "units": chain, "evaluate": True})
        while not env.done and env.sim_calls_used < env.max_sim_calls:
            if env.best_feasible is not None:
                break
            op = rng.choice(["add", "replace", "params"])
            if op == "add" and len(chain) < 7:
                unit = rng.choice(CANONICAL_UNITS)
                env.step({"type": "add_unit", "unit": unit, "evaluate": True})
                chain = list(env.current_chain)
            elif op == "replace" and chain:
                old_u = rng.choice(chain)
                new_u = rng.choice(CANONICAL_UNITS)
                env.step({"type": "replace_unit", "old_unit": old_u, "new_unit": new_u, "evaluate": True})
                chain = list(env.current_chain)
            else:
                env.step({"type": "set_parameters", "params": _random_params(chain, rng), "evaluate": True})
    except SimulationBudgetExhausted:
        pass
    return env.episode_summary()


def _run_random_search(env: AquaDesignGymEnv, seed: int = 0) -> dict[str, Any]:
    """Conventional baseline: random valid topologies and uniform random parameters."""
    rng = random.Random(seed)
    try:
        while not env.done and env.sim_calls_used < env.max_sim_calls:
            length = rng.randint(2, 6)
            units = canonicalize_chain(rng.sample(CANONICAL_UNITS, k=length))
            params = _random_params(units, rng)
            env.step({"type": "propose_train", "units": units, "params": params, "evaluate": True})
    except SimulationBudgetExhausted:
        pass
    return env.episode_summary()


def _run_template_grid_search(env: AquaDesignGymEnv, seed: int = 0) -> dict[str, Any]:
    """Conventional baseline: cycles through template priors and samples operating parameters."""
    rng = random.Random(seed)
    templates = [canonicalize_chain(list(t.chain)) for t in TEMPLATE_PRIORS]
    idx = 0
    try:
        while not env.done and env.sim_calls_used < env.max_sim_calls:
            chain = templates[idx % len(templates)]
            params = default_parameters_for_chain(chain, env.task) if idx < len(templates) else _random_params(chain, rng)
            env.step({"type": "propose_train", "units": chain, "params": params, "evaluate": True})
            idx += 1
    except SimulationBudgetExhausted:
        pass
    return env.episode_summary()


def _run_evolutionary_minlp(env: AquaDesignGymEnv, seed: int = 0) -> dict[str, Any]:
    """Conventional optimizer: evolutionary mixed-integer topology + parameter search."""
    rng = random.Random(seed)
    pop_size = min(10, max(4, env.max_sim_calls // 4))
    population: list[tuple[float, list[str], dict[str, dict[str, float]]]] = []

    def fitness(sim: dict[str, Any]) -> float:
        if sim["feasible"]:
            return float(sim["economics"]["lcow_usd_m3"])
        return 100.0 + 40.0 * float(sim["hard_violation_count"]) + 80.0 * float(sim["total_rel_violation"])

    try:
        # Seed population from templates + random topologies
        for i in range(pop_size):
            if env.sim_calls_used >= env.max_sim_calls:
                break
            if i < len(TEMPLATE_PRIORS) // 2:
                chain = canonicalize_chain(list(TEMPLATE_PRIORS[(i * 2) % len(TEMPLATE_PRIORS)].chain))
                params = default_parameters_for_chain(chain, env.task)
            else:
                chain = canonicalize_chain(rng.sample(CANONICAL_UNITS, k=rng.randint(3, 6)))
                params = _random_params(chain, rng)
            sim = env._call_oracle(chain, params)
            population.append((fitness(sim), chain, params))

        while env.sim_calls_used < env.max_sim_calls and population:
            population.sort(key=lambda item: item[0])
            elites = population[: max(2, pop_size // 2)]
            _, p_chain, p_params = rng.choice(elites)
            child_chain = list(p_chain)
            child_params = copy.deepcopy(p_params)

            # Topology mutation (35%) or continuous parameter mutation (65%)
            if rng.random() < 0.35:
                mut = rng.choice(["add", "remove", "replace"])
                if mut == "add" and len(child_chain) < 7:
                    u = rng.choice(CANONICAL_UNITS)
                    if u not in child_chain:
                        child_chain = canonicalize_chain([*child_chain, u])
                        child_params[u] = default_parameters_for_chain([u], env.task)[u]
                elif mut == "remove" and len(child_chain) > 2:
                    rem = rng.choice(child_chain)
                    child_chain.remove(rem)
                    child_params.pop(rem, None)
                elif mut == "replace" and child_chain:
                    old_u = rng.choice(child_chain)
                    new_u = rng.choice(CANONICAL_UNITS)
                    if new_u not in child_chain:
                        child_chain = canonicalize_chain([new_u if u == old_u else u for u in child_chain])
                        child_params.pop(old_u, None)
                        child_params[new_u] = default_parameters_for_chain([new_u], env.task)[new_u]
            else:
                if child_chain:
                    u = rng.choice(child_chain)
                    spec = UNIT_SPECS[u]
                    if spec.params:
                        pspec = rng.choice(spec.params)
                        cur = float(child_params.get(u, {}).get(pspec.name, pspec.default))
                        delta = rng.gauss(0.0, 0.20 * (pspec.upper - pspec.lower))
                        child_params.setdefault(u, {})[pspec.name] = max(pspec.lower, min(pspec.upper, cur + delta))

            sim = env._call_oracle(child_chain, child_params)
            population.append((fitness(sim), child_chain, child_params))
            population.sort(key=lambda item: item[0])
            population = population[:pop_size]
    except SimulationBudgetExhausted:
        pass
    return env.episode_summary()


METHOD_REGISTRY: dict[str, dict[str, Any]] = {
    "HydroWeaver": {
        "family": "agentic_closed_loop",
        "description": "Full HydroWeaver: knowledge-informed generator + numerical param optimizer + simulation diagnosis router + shared history",
        "runner": lambda env, seed: _run_hydroweaver_variant(env),
    },
    "OneShotKnowledge": {
        "family": "agent_baseline",
        "description": "Single-pass plausible knowledge-informed train with default operating parameters",
        "runner": _run_one_shot_knowledge,
    },
    "RuleCriticLoop": {
        "family": "agent_baseline",
        "description": "Static rule-based critic repair loop without simulation feedback diagnosis or parameter optimization",
        "runner": _run_rule_critic_loop,
    },
    "ReActBlindAgent": {
        "family": "agent_baseline",
        "description": "Iterative trial-mutation agent without violation-guided routing or numerical optimizer",
        "runner": _run_react_blind_agent,
    },
    "EvolutionaryMINLP": {
        "family": "conventional_optimizer",
        "description": "Evolutionary mixed-integer optimizer over unit topology and continuous parameters",
        "runner": _run_evolutionary_minlp,
    },
    "TemplateGridSearch": {
        "family": "conventional_optimizer",
        "description": "Template enumeration with random operating-parameter sweeps",
        "runner": _run_template_grid_search,
    },
    "RandomSearch": {
        "family": "conventional_optimizer",
        "description": "Uniform random topology and parameter sampling under matched budget",
        "runner": _run_random_search,
    },
    "HW-NoParamOpt": {
        "family": "ablation",
        "description": "Ablation: HydroWeaver without numerical operating-parameter optimization",
        "runner": lambda env, seed: _run_hydroweaver_variant(env, enable_param_opt=False),
    },
    "HW-NoStructRev": {
        "family": "ablation",
        "description": "Ablation: HydroWeaver without structural train revision (param optimization only)",
        "runner": lambda env, seed: _run_hydroweaver_variant(env, enable_struct_rev=False),
    },
    "HW-NoDiagRouter": {
        "family": "ablation",
        "description": "Ablation: HydroWeaver with blind alternation instead of simulation-feedback diagnosis router",
        "runner": lambda env, seed: _run_hydroweaver_variant(env, enable_diag_router=False),
    },
    "HW-NoKnowledge": {
        "family": "ablation",
        "description": "Ablation: HydroWeaver starting from uninformed initial train without knowledge priors",
        "runner": lambda env, seed: _run_hydroweaver_variant(env, enable_knowledge_priors=False),
    },
    "HW-NoHistory": {
        "family": "ablation",
        "description": "Ablation: HydroWeaver without shared design history",
        "runner": lambda env, seed: _run_hydroweaver_variant(env, enable_history=False),
    },
}


def run_method(
    method_name: str,
    task_id: str,
    *,
    perturbation: str = "nominal",
    max_sim_calls: int = 60,
    seed: int = 0,
) -> dict[str, Any]:
    if method_name not in METHOD_REGISTRY:
        raise ValueError(f"Unknown AquaDesignGym method: {method_name}")
    env = AquaDesignGymEnv(max_sim_calls=max_sim_calls)
    env.reset(task_id, perturbation=perturbation, max_sim_calls=max_sim_calls)
    return METHOD_REGISTRY[method_name]["runner"](env, seed)
