"""Shared design history maintaining provenance across topology and parameter iterations."""

from __future__ import annotations

import copy
from typing import Any


class SharedDesignHistory:
    """Tracks every evaluated configuration, operating state, diagnosis, and action."""

    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []
        self.seen_topologies: set[tuple[str, ...]] = set()
        self.exhausted_topologies: set[tuple[str, ...]] = set()
        self.best_feasible: dict[str, Any] | None = None
        self.best_overall: dict[str, Any] | None = None

    def record(
        self,
        *,
        round_index: int,
        action: str,
        source: str,
        chain: list[str],
        parameters: dict[str, dict[str, float]],
        simulation: dict[str, Any],
        diagnosis: dict[str, Any],
        sim_calls_total: int,
        note: str = "",
    ) -> dict[str, Any]:
        sig = tuple(simulation.get("chain") or chain)
        self.seen_topologies.add(sig)
        if action in ("refine_parameters", "revise_structure") or diagnosis.get("recommended_action") == "revise_structure":
            self.exhausted_topologies.add(sig)
        feasible = bool(simulation.get("feasible"))
        lcow = float(simulation["economics"]["lcow_usd_m3"])
        sec = float(simulation["flowsheet"]["specific_energy_kWh_m3"])
        rel_viol = float(simulation["total_rel_violation"])

        entry = {
            "round": round_index,
            "action": action,
            "source": source,
            "chain": list(sig),
            "parameters": copy.deepcopy(parameters),
            "feasible": feasible,
            "hard_violation_count": int(simulation["hard_violation_count"]),
            "total_rel_violation": rel_viol,
            "lcow_usd_m3": lcow,
            "specific_energy_kWh_m3": sec,
            "recovery_fraction": float(simulation["flowsheet"]["recovery_fraction"]),
            "violations": copy.deepcopy(simulation.get("violations") or []),
            "diagnosis": {
                "recommended_action": diagnosis.get("recommended_action"),
                "rationale": diagnosis.get("rationale"),
            },
            "sim_calls_total": sim_calls_total,
            "note": note,
            "simulation": simulation,
        }
        self.records.append(entry)

        if feasible:
            if self.best_feasible is None or lcow < self.best_feasible["lcow_usd_m3"]:
                self.best_feasible = entry
        if self.best_overall is None:
            self.best_overall = entry
        else:
            if feasible and not self.best_overall["feasible"]:
                self.best_overall = entry
            elif feasible and self.best_overall["feasible"] and lcow < self.best_overall["lcow_usd_m3"]:
                self.best_overall = entry
            elif not feasible and not self.best_overall["feasible"]:
                cur_key = (entry["hard_violation_count"], rel_viol, lcow)
                best_key = (self.best_overall["hard_violation_count"], self.best_overall["total_rel_violation"], self.best_overall["lcow_usd_m3"])
                if cur_key < best_key:
                    self.best_overall = entry
        return entry

    def summary_records(self) -> list[dict[str, Any]]:
        """Compact design history without duplicating full per-unit simulation payload per round."""
        compact: list[dict[str, Any]] = []
        for rec in self.records:
            compact.append(
                {
                    "round": rec["round"],
                    "action": rec["action"],
                    "source": rec["source"],
                    "chain": rec["chain"],
                    "feasible": rec["feasible"],
                    "hard_violation_count": rec["hard_violation_count"],
                    "total_rel_violation": rec["total_rel_violation"],
                    "lcow_usd_m3": rec["lcow_usd_m3"],
                    "specific_energy_kWh_m3": rec["specific_energy_kWh_m3"],
                    "recovery_fraction": rec["recovery_fraction"],
                    "diagnosis": rec["diagnosis"],
                    "sim_calls_total": rec["sim_calls_total"],
                    "note": rec["note"],
                }
            )
        return compact
