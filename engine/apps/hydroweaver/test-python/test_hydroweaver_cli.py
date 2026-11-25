from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
ENGINE_CLI = PACKAGE_ROOT / "backend" / "hydroweaver_cli.py"
PRODUCT_VERSION = json.loads(
    (PACKAGE_ROOT / "package.json").read_text(encoding="utf-8")
)["version"]


class StandaloneEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="hydroweaver-engine-test-")
        self.root = Path(self.temporary.name)
        self.home = self.root / "home"
        self.home.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _run(self, *args: str) -> subprocess.CompletedProcess[str]:
        env = {**os.environ, "HYDROWEAVER_HOME": str(self.home), "PYTHONDONTWRITEBYTECODE": "1"}
        return subprocess.run(
            [sys.executable, str(ENGINE_CLI), *args],
            cwd=self.root,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    def _complete_case(self) -> dict[str, object]:
        return {
            "query_id": "arsenic-gw-test",
            "source_water": "groundwater",
            "water_quality": {
                "pH": 7.2,
                "arsenic_ug_L": 150.0,
                "iron_mg_L": 0.8,
                "turbidity_NTU": 1.2,
                "extra": {"arsenic_speciation": "As(III) dominant"},
            },
            "contaminants": ["arsenic", "iron"],
            "treatment_targets": {"arsenic_ug_L": 10.0, "iron_mg_L": 0.3},
            "constraints": {
                "budget": "low",
                "energy": "low",
                "brine_disposal": False,
                "operator_skill": "low",
                "use_for_drinking": True,
                "chemical_dosing_allowed": True,
                "extra": {"design_flow_m3_day": 150.0},
            },
        }

    def _assess(self, case: dict[str, object]) -> dict[str, object]:
        result = self._run("assess-case", "--query-json", json.dumps(case))
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_version_and_health_require_no_external_repo(self) -> None:
        ver = self._run("--version")
        self.assertEqual(ver.returncode, 0, ver.stderr)
        self.assertTrue(ver.stdout.startswith(f"hydroweaver-engine {PRODUCT_VERSION} "), ver.stdout)
        self.assertIn("hydroweaver-engine", ver.stdout)

        health = self._run("health", "--json")
        self.assertEqual(health.returncode, 0, health.stderr)
        payload = json.loads(health.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["engine_mode"], "standalone-hydroweaver")
        self.assertGreaterEqual(payload["knowledge_base"]["units"], 15)
        self.assertGreaterEqual(payload["aquadesigngym"]["tasks"], 10)

    def test_identity_reports_standalone_configuration(self) -> None:
        result = self._run("identity")
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["engine_mode"], "standalone-hydroweaver")
        self.assertTrue(payload["optimization"]["joint_config_and_params"])
        self.assertTrue(payload["optimization"]["shared_design_history"])

    def test_catalog_lists_units_and_contaminants(self) -> None:
        result = self._run("catalog", "--kind", "all", "--search", "Osmosis")
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertIn("Reverse Osmosis", payload["treatment_units"])
        self.assertTrue(payload["unit_details"])

    def test_case_assessment_blocks_invalid_values_and_checks_nitrate_bases(self) -> None:
        for section, field, value in (
            ("water_quality", "arsenic_ug_L", -1),
            ("treatment_targets", "arsenic_ug_L", -1),
            ("water_quality", "arsenic_ug_L", "not measured"),
            ("water_quality", "arsenic_ug_L", float("nan")),
            ("water_quality", "arsenic_ug_L", float("inf")),
        ):
            with self.subTest(section=section, field=field, value=value):
                case = self._complete_case()
                case[section][field] = value
                payload = self._assess(case)
                self.assertEqual(payload["decision_readiness"]["status"], "blocked")

        nitrate_case = self._complete_case()
        nitrate_case["contaminants"] = ["nitrate"]
        nitrate_case["water_quality"] = {"nitrate_mg_L": 60, "pH": 7.2, "extra": {}}
        nitrate_case["treatment_targets"] = {"nitrate_mg_L": 10, "extra": {}}
        self.assertEqual(self._assess(nitrate_case)["decision_readiness"]["status"], "needs_information")
        nitrate_case["water_quality"]["extra"]["nitrate_basis"] = "as N"
        nitrate_case["treatment_targets"]["extra"]["nitrate_basis"] = "as N"
        self.assertEqual(self._assess(nitrate_case)["decision_readiness"]["status"], "ready_for_screening")

    def test_query_rejects_boolean_measurements(self) -> None:
        case = self._complete_case()
        case["water_quality"]["arsenic_ug_L"] = True
        result = self._run("assess-case", "--query-json", json.dumps(case))
        self.assertEqual(result.returncode, 1)
        self.assertIn("not a boolean", result.stderr)

    def test_documented_example_cases_pass_assessment_gates(self) -> None:
        examples = PACKAGE_ROOT.parents[2] / "examples" / "cases"
        for name, expected_status in (
            ("arsenic-groundwater", "ready_for_screening"),
            ("municipal-bsm2", "ready_for_screening"),
            ("nitrate-basis-unknown", "needs_information"),
            ("lead-source-unknown", "blocked"),
        ):
            case = json.loads((examples / f"{name}.json").read_text(encoding="utf-8"))
            payload = self._assess(case)
            self.assertEqual(payload["decision_readiness"]["status"], expected_status)

    def test_municipal_asm1_bsm2_closed_loop_optimization(self) -> None:
        examples = PACKAGE_ROOT.parents[2] / "examples" / "cases"
        case = json.loads((examples / "municipal-bsm2.json").read_text(encoding="utf-8"))
        result = self._run(
            "optimize",
            "--query-json",
            json.dumps(case),
            "--candidates-json",
            json.dumps([["Aerobic Reactor"]]),
            "--max-rounds",
            "6",
            "--max-sim-calls",
            "40",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["optimization"]["status"], "feasible")
        best = payload["best_design"]
        self.assertTrue(best["feasible"])
        self.assertIn("Secondary Clarifier", best["chain"])

    def test_closed_loop_optimization_revises_structure_and_optimizes_parameters(self) -> None:
        # Caller supplies an intentionally flawed initial chain: RO without pumping + violates no-brine constraint!
        case = self._complete_case()
        result = self._run(
            "optimize",
            "--query-json",
            json.dumps(case),
            "--candidates-json",
            json.dumps([["Reverse Osmosis"]]),
            "--max-rounds",
            "8",
            "--max-sim-calls",
            "50",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["kind"], "hydroweaver.closed-loop-optimization")
        self.assertEqual(payload["optimization"]["status"], "feasible")
        self.assertGreaterEqual(len(payload["final_trains"]), 1)
        self.assertGreater(len(payload["design_history"]), 1)
        best = payload["best_design"]
        self.assertTrue(best["feasible"])
        self.assertNotIn("Reverse Osmosis", best["chain"])

    def test_recommend_and_audit_report_roundtrip(self) -> None:
        case = self._complete_case()
        rec_out = self.root / "recommend.json"
        rec_res = self._run("recommend", "--query-json", json.dumps(case), "--output", str(rec_out))
        self.assertEqual(rec_res.returncode, 0, rec_res.stderr)
        rec_payload = json.loads(rec_out.read_text(encoding="utf-8"))
        self.assertTrue(rec_payload["recommendations"])

        audit_out = self.root / "audit.json"
        audit_res = self._run("audit-report", "--report-file", str(rec_out), "--output", str(audit_out))
        self.assertEqual(audit_res.returncode, 0, audit_res.stderr)
        audit_payload = json.loads(audit_out.read_text(encoding="utf-8"))
        self.assertEqual(audit_payload["status"], "pass")

    def test_ingest_and_build_indexes_work_locally(self) -> None:
        record = self.root / "local_unit.json"
        record.write_text(json.dumps({"id": "CUSTOM-UNIT-1", "title": "Electrocoagulation", "text": "Removes arsenic and turbidity."}), encoding="utf-8")
        res = self._run("ingest", "--kb-type", "kb-unit", "--data-file", str(record))
        self.assertEqual(res.returncode, 0, res.stderr)
        payload = json.loads(res.stdout)
        self.assertTrue(payload["index_rebuilt"])
        self.assertGreater(payload["index_report"]["staged_chunks"], 0)


if __name__ == "__main__":
    unittest.main()
