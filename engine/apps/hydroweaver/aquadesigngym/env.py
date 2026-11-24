"""AquaDesignGym interactive environment with admissible actions and matched simulation budget oracle."""

from __future__ import annotations

import copy
from typing import Any

from hydroweaver_py.diagnosis import diagnose_simulation
from hydroweaver_py.knowledge import (
    CANONICAL_UNITS,
    UNIT_SPECS,
    canonicalize_chain,
    default_parameters_for_chain,
    normalize_unit_name,
)
from hydroweaver_py.optimizer import optimize_operating_parameters
from hydroweaver_py.simulator import simulate_train
from .tasks import apply_influent_perturbation, get_task


class SimulationBudgetExhausted(RuntimeError):
    """Raised internally when an episode attempts to exceed its matched simulation budget."""


class AquaDesignGymEnv:
    """Interactive Gym-style environment for closed-loop water-treatment train design."""

    ADMISSIBLE_ACTIONS = (
        "propose_train",
        "add_unit",
        "remove_unit",
        "replace_unit",
        "reorder_units",
        "set_parameters",
        "optimize_parameters",
        "evaluate",
        "submit",
    )

    def __init__(self, *, max_sim_calls: int = 60) -> None:
        if max_sim_calls < 1:
            raise ValueError("max_sim_calls must be >= 1")
        self.default_max_sim_calls = max_sim_calls
        self.max_sim_calls = max_sim_calls
        self.task: dict[str, Any] = {}
        self.perturbation: str = "nominal"
        self.current_chain: list[str] = []
        self.current_params: dict[str, dict[str, float]] = {}
        self.last_simulation: dict[str, Any] | None = None
        self.last_diagnosis: dict[str, Any] | None = None
        self.sim_calls_used: int = 0
        self.first_feasible_sim_call: int | None = None
        self.best_feasible: dict[str, Any] | None = None
        self.best_overall: dict[str, Any] | None = None
        self.feasibility_curve: list[dict[str, Any]] = []
        self.history: list[dict[str, Any]] = []
        self.done: bool = False
        self.truncated: bool = False

    def reset(
        self,
        task_id: str,
        *,
        perturbation: str = "nominal",
        max_sim_calls: int | None = None,
    ) -> dict[str, Any]:
        """Reset environment to a standardized design task and influent profile."""
        base_task = get_task(task_id)
        self.perturbation = perturbation
        self.task = apply_influent_perturbation(base_task, perturbation)
        self.max_sim_calls = max_sim_calls if max_sim_calls is not None else self.default_max_sim_calls
        self.current_chain = []
        self.current_params = {}
        self.last_simulation = None
        self.last_diagnosis = None
        self.sim_calls_used = 0
        self.first_feasible_sim_call = None
        self.best_feasible = None
        self.best_overall = None
        self.feasibility_curve = []
        self.history = []
        self.done = False
        self.truncated = False
        return self.observation()

    def _call_oracle(self, chain: list[str], params: dict[str, dict[str, float]]) -> dict[str, Any]:
        if self.sim_calls_used >= self.max_sim_calls:
            self.truncated = True
            self.done = True
            raise SimulationBudgetExhausted("Simulation oracle budget exhausted.")
        self.sim_calls_used += 1
        sim = simulate_train(self.task, chain, params)
        feasible = bool(sim["feasible"])
        lcow = float(sim["economics"]["lcow_usd_m3"])
        sec = float(sim["flowsheet"]["specific_energy_kWh_m3"])
        rel_viol = float(sim["total_rel_violation"])
        hard_cnt = int(sim["hard_violation_count"])

        if feasible and self.first_feasible_sim_call is None:
            self.first_feasible_sim_call = self.sim_calls_used

        snapshot = {
            "sim_call": self.sim_calls_used,
            "chain": list(sim["chain"]),
            "parameters": copy.deepcopy(sim["parameters"]),
            "feasible": feasible,
            "hard_violation_count": hard_cnt,
            "total_rel_violation": rel_viol,
            "lcow_usd_m3": lcow,
            "specific_energy_kWh_m3": sec,
            "simulation": sim,
        }
        if feasible:
            if self.best_feasible is None or lcow < self.best_feasible["lcow_usd_m3"]:
                self.best_feasible = snapshot
        if self.best_overall is None:
            self.best_overall = snapshot
        else:
            if feasible and not self.best_overall["feasible"]:
                self.best_overall = snapshot
            elif feasible and self.best_overall["feasible"] and lcow < self.best_overall["lcow_usd_m3"]:
                self.best_overall = snapshot
            elif not feasible and not self.best_overall["feasible"]:
                if (hard_cnt, rel_viol, lcow) < (
                    self.best_overall["hard_violation_count"],
                    self.best_overall["total_rel_violation"],
                    self.best_overall["lcow_usd_m3"],
                ):
                    self.best_overall = snapshot

        self.feasibility_curve.append(
            {
                "sim_call": self.sim_calls_used,
                "best_feasible": self.best_feasible is not None,
                "best_lcow_usd_m3": self.best_feasible["lcow_usd_m3"] if self.best_feasible else None,
                "current_feasible": feasible,
                "current_rel_violation": rel_viol,
            }
        )
        return sim

    def step(self, action: dict[str, Any]) -> tuple[dict[str, Any], float, bool, bool, dict[str, Any]]:
        """Execute one admissible action and return (obs, reward, terminated, truncated, info)."""
        if self.done:
            return self.observation(), 0.0, True, self.truncated, {"message": "Episode already finished."}

        act_type = str(action.get("type") or "").strip()
        if act_type not in self.ADMISSIBLE_ACTIONS:
            raise ValueError(f"Inadmissible action type: {act_type}. Must be one of {self.ADMISSIBLE_ACTIONS}")

        info: dict[str, Any] = {"action": act_type}
        eval_triggered = False

        if act_type == "propose_train":
            raw_units = action.get("units")
            if not isinstance(raw_units, list) or not raw_units:
                raise ValueError("propose_train requires a non-empty units list")
            self.current_chain = canonicalize_chain([str(u) for u in raw_units])
            self.current_params = default_parameters_for_chain(self.current_chain, self.task)
            if isinstance(action.get("params"), dict):
                self._merge_params(action["params"])
            eval_triggered = bool(action.get("evaluate", True))

        elif act_type == "add_unit":
            unit = normalize_unit_name(str(action.get("unit") or ""))
            if unit is None or unit not in UNIT_SPECS:
                raise ValueError(f"Unknown unit for add_unit: {action.get('unit')}")
            if unit not in self.current_chain:
                self.current_chain = canonicalize_chain([*self.current_chain, unit])
                defaults = default_parameters_for_chain([unit], self.task)
                self.current_params[unit] = defaults[unit]
            eval_triggered = bool(action.get("evaluate", True))

        elif act_type == "remove_unit":
            target = action.get("unit")
            if isinstance(target, int) and 0 <= target < len(self.current_chain):
                removed = self.current_chain.pop(target)
                self.current_params.pop(removed, None)
            else:
                unit = normalize_unit_name(str(target or ""))
                if unit in self.current_chain:
                    self.current_chain.remove(unit)
                    self.current_params.pop(unit, None)
            eval_triggered = bool(action.get("evaluate", True)) and bool(self.current_chain)

        elif act_type == "replace_unit":
            old_u = normalize_unit_name(str(action.get("old_unit") or ""))
            new_u = normalize_unit_name(str(action.get("new_unit") or ""))
            if new_u is None or new_u not in UNIT_SPECS:
                raise ValueError(f"Unknown replacement unit: {action.get('new_unit')}")
            if old_u in self.current_chain:
                self.current_chain = canonicalize_chain([new_u if u == old_u else u for u in self.current_chain])
                self.current_params.pop(old_u, None)
                self.current_params[new_u] = default_parameters_for_chain([new_u], self.task)[new_u]
            eval_triggered = bool(action.get("evaluate", True))

        elif act_type == "reorder_units":
            if self.current_chain:
                self.current_chain = canonicalize_chain(self.current_chain)
            eval_triggered = bool(action.get("evaluate", False))

        elif act_type == "set_parameters":
            if not isinstance(action.get("params"), dict):
                raise ValueError("set_parameters requires a params object")
            self._merge_params(action["params"])
            eval_triggered = bool(action.get("evaluate", True))

        elif act_type == "optimize_parameters":
            if not self.current_chain:
                raise ValueError("optimize_parameters requires a non-empty current_chain")
            remaining = self.max_sim_calls - self.sim_calls_used
            requested = int(action.get("max_evals") or 16)
            budget = max(1, min(remaining, requested))
            try:
                opt = optimize_operating_parameters(
                    self.task,
                    self.current_chain,
                    self.current_params,
                    max_evals=budget,
                    sim_oracle=self._call_oracle,
                )
                self.current_params = opt["best_params"]
                self.last_simulation = opt["best_simulation"]
                self.last_diagnosis = diagnose_simulation(self.task, self.last_simulation, params_already_optimized=True)
                info["optimize_evals"] = opt["evals_used"]
            except SimulationBudgetExhausted:
                self.truncated = True
                self.done = True
            self.history.append({"step": len(self.history) + 1, "action": act_type, "sim_calls": self.sim_calls_used, "chain": list(self.current_chain)})
            if self.sim_calls_used >= self.max_sim_calls:
                self.truncated = True
                self.done = True
            reward = self._compute_reward()
            return self.observation(), reward, self.done and not self.truncated, self.truncated, info

        elif act_type == "evaluate":
            eval_triggered = True

        elif act_type == "submit":
            if self.last_simulation is None and self.current_chain and self.sim_calls_used < self.max_sim_calls:
                try:
                    self.last_simulation = self._call_oracle(self.current_chain, self.current_params)
                    self.last_diagnosis = diagnose_simulation(self.task, self.last_simulation)
                except SimulationBudgetExhausted:
                    self.truncated = True
            self.done = True
            reward = self._compute_reward()
            return self.observation(), reward, True, self.truncated, info

        if eval_triggered and self.current_chain:
            try:
                self.last_simulation = self._call_oracle(self.current_chain, self.current_params)
                self.last_diagnosis = diagnose_simulation(self.task, self.last_simulation)
            except SimulationBudgetExhausted:
                self.truncated = True
                self.done = True

        self.history.append({"step": len(self.history) + 1, "action": act_type, "sim_calls": self.sim_calls_used, "chain": list(self.current_chain)})
        if self.sim_calls_used >= self.max_sim_calls:
            self.truncated = True
            self.done = True

        reward = self._compute_reward()
        return self.observation(), reward, self.done and not self.truncated, self.truncated, info

    def _merge_params(self, supplied: dict[str, Any]) -> None:
        for unit_raw, pmap in supplied.items():
            unit = normalize_unit_name(str(unit_raw)) or str(unit_raw)
            if unit not in self.current_chain or not isinstance(pmap, dict):
                continue
            self.current_params.setdefault(unit, {})
            for k, v in pmap.items():
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    self.current_params[unit][str(k)] = float(v)

    def _compute_reward(self) -> float:
        if self.last_simulation is None:
            return -1.0
        if self.last_simulation["feasible"]:
            lcow = float(self.last_simulation["economics"]["lcow_usd_m3"])
            return round(10.0 - lcow, 4)
        return round(-float(self.last_simulation["hard_violation_count"]) - float(self.last_simulation["total_rel_violation"]), 4)

    def observation(self) -> dict[str, Any]:
        return {
            "task_id": self.task.get("task_id"),
            "perturbation": self.perturbation,
            "current_chain": list(self.current_chain),
            "current_params": copy.deepcopy(self.current_params),
            "sim_calls_used": self.sim_calls_used,
            "max_sim_calls": self.max_sim_calls,
            "budget_remaining": max(0, self.max_sim_calls - self.sim_calls_used),
            "admissible_units": list(CANONICAL_UNITS),
            "admissible_actions": list(self.ADMISSIBLE_ACTIONS),
            "last_simulation": self.last_simulation,
            "last_diagnosis": self.last_diagnosis,
            "best_feasible": self.best_feasible,
            "best_overall": self.best_overall,
            "first_feasible_sim_call": self.first_feasible_sim_call,
        }

    def episode_summary(self) -> dict[str, Any]:
        best = self.best_feasible or self.best_overall
        return {
            "task_id": self.task.get("task_id"),
            "difficulty": self.task.get("difficulty"),
            "perturbation": self.perturbation,
            "feasible": self.best_feasible is not None,
            "sim_calls_used": self.sim_calls_used,
            "max_sim_calls": self.max_sim_calls,
            "first_feasible_sim_call": self.first_feasible_sim_call,
            "best_chain": best["chain"] if best else [],
            "best_parameters": best["parameters"] if best else {},
            "best_lcow_usd_m3": best["lcow_usd_m3"] if best else None,
            "best_sec_kwh_m3": best["specific_energy_kWh_m3"] if best else None,
            "best_rel_violation": best["total_rel_violation"] if best else None,
            "feasibility_curve": self.feasibility_curve,
        }
