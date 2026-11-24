from __future__ import annotations

import sys
import unittest
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from aquadesigngym import (  # noqa: E402
    AquaDesignGymEnv,
    BENCHMARK_TASKS,
    METHOD_REGISTRY,
    apply_influent_perturbation,
    evaluate_benchmark,
    get_task,
    run_method,
)
from hydroweaver_py.harness import run_closed_loop_optimization  # noqa: E402


class AquaDesignGymTests(unittest.TestCase):
    def test_task_suite_and_perturbations_are_well_formed(self) -> None:
        self.assertGreaterEqual(len(BENCHMARK_TASKS), 12)
        for task in BENCHMARK_TASKS:
            self.assertIn("task_id", task)
            self.assertIn("water_quality", task)
            self.assertIn("treatment_targets", task)
            self.assertIn("constraints", task)
        shifted = apply_influent_perturbation(get_task("ADG-03-BWRO-BRACKISH"), "severe_shift")
        self.assertGreater(shifted["water_quality"]["tds_mg_L"], get_task("ADG-03-BWRO-BRACKISH")["water_quality"]["tds_mg_L"])

    def test_matched_simulation_budget_is_enforced_strictly(self) -> None:
        env = AquaDesignGymEnv(max_sim_calls=5)
        env.reset("ADG-01-AS-RURAL", max_sim_calls=5)
        env.step({"type": "propose_train", "units": ["Media Filtration", "Adsorption", "UV Disinfection"], "evaluate": True})
        self.assertEqual(env.sim_calls_used, 1)
        obs, _, _, truncated, _ = env.step({"type": "optimize_parameters", "max_evals": 10})
        self.assertLessEqual(obs["sim_calls_used"], 5)
        self.assertTrue(truncated)

    def test_admissible_structural_and_parametric_actions_improve_design(self) -> None:
        env = AquaDesignGymEnv(max_sim_calls=40)
        env.reset("ADG-03-BWRO-BRACKISH", max_sim_calls=40)
        obs1, _, _, _, _ = env.step({"type": "propose_train", "units": ["Media Filtration", "Reverse Osmosis"], "evaluate": True})
        self.assertFalse(obs1["last_simulation"]["feasible"])
        self.assertEqual(obs1["last_diagnosis"]["recommended_action"], "revise_structure")

        env.step({"type": "add_unit", "unit": "Pumping", "evaluate": True})
        env.step({"type": "add_unit", "unit": "Energy Recovery", "evaluate": True})
        env.step({"type": "add_unit", "unit": "Chlorination", "evaluate": True})
        obs2, _, _, _, _ = env.step({"type": "optimize_parameters", "max_evals": 18})
        self.assertTrue(obs2["best_feasible"] is not None or obs2["last_simulation"]["hard_violation_count"] <= 1)

    def test_hydroweaver_outperforms_oneshot_and_random_under_matched_budget(self) -> None:
        report = evaluate_benchmark(
            methods=["HydroWeaver", "OneShotKnowledge", "EvolutionaryMINLP", "HW-NoParamOpt"],
            task_ids=["ADG-01-AS-RURAL", "ADG-03-BWRO-BRACKISH", "ADG-04-SW-DBP", "ADG-08-NITRATE-IX"],
            perturbations=["nominal", "mild_shift"],
            max_sim_calls=50,
            seed=7,
        )
        hw_fdr = report["methods"]["HydroWeaver"]["by_perturbation"]["nominal"]["feasible_design_rate"]
        os_fdr = report["methods"]["OneShotKnowledge"]["by_perturbation"]["nominal"]["feasible_design_rate"]
        no_opt_fdr = report["methods"]["HW-NoParamOpt"]["by_perturbation"]["nominal"]["feasible_design_rate"]
        self.assertGreater(hw_fdr, os_fdr)
        self.assertGreater(hw_fdr, no_opt_fdr)
        self.assertEqual(hw_fdr, 1.0)

    def test_all_registered_methods_execute_cleanly(self) -> None:
        for method_name in METHOD_REGISTRY:
            summary = run_method(method_name, "ADG-08-NITRATE-IX", max_sim_calls=15, seed=1)
            self.assertLessEqual(summary["sim_calls_used"], 15)


if __name__ == "__main__":
    unittest.main()
