from __future__ import annotations

import json
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fake_modules  # noqa: E402

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
SIM_ROOT = PACKAGE_ROOT / "sim"
sys.path.insert(0, str(SIM_ROOT))

import runner  # noqa: E402
from unit_map import classify, normalize_unit  # noqa: E402

CASE = {
    "source_water": "groundwater",
    "contaminants": ["arsenic"],
    "water_quality": {"tds_mg_L": 2500},
    "constraints": {"extra": {"design_flow_m3_day": 250}},
}


class UnitMapTests(unittest.TestCase):
    def test_normalizes_known_units_and_aliases(self) -> None:
        self.assertEqual(normalize_unit("Reverse Osmosis"), "Reverse Osmosis")
        self.assertEqual(normalize_unit(" reverse_osmosis "), "Reverse Osmosis")
        self.assertEqual(normalize_unit("Membrane Separation"), "Reverse Osmosis")
        self.assertEqual(normalize_unit("nf"), "Nanofiltration")
        self.assertIsNone(normalize_unit("Adsorption"))
        self.assertIsNone(normalize_unit("Chlorination"))
        self.assertIsNone(normalize_unit(""))

    def test_classify_preserves_order_and_flags_unsupported(self) -> None:
        coverage = classify(["Pumping", "Adsorption", "Reverse Osmosis", "Chlorination"])
        self.assertEqual(coverage["modeled"], ["Pumping", "Reverse Osmosis"])
        self.assertEqual(coverage["unsupported"], ["Adsorption", "Chlorination"])
        self.assertEqual(len(coverage["specs"]), 2)
        self.assertEqual(coverage["specs"][1].model, "watertap.unit_models.reverse_osmosis_0D.ReverseOsmosis0D")


class SelfCheckTests(unittest.TestCase):
    def test_self_check_reports_contract_without_watertap(self) -> None:
        report = runner.self_check()
        self.assertEqual(report["kind"], "hydroweaver.simulation-selfcheck")
        self.assertEqual(report["schema_version"], 1)
        self.assertIn(report["available"], (True, False))
        self.assertIn("watertap", report["environment"]["versions"])
        self.assertIn("solver", report)
        names = [unit["unit"] for unit in report["supported_units"]]
        self.assertEqual(names, ["Nanofiltration", "Pumping", "Reverse Osmosis"])
        self.assertTrue(report["limitations"])
        self.assertIn("Chlorination", report["unsupported_examples"])


class SimulateContractTests(unittest.TestCase):
    def test_rejects_wrong_schema_and_shape(self) -> None:
        with self.assertRaises(ValueError):
            runner.simulate({"schema_version": 2})
        with self.assertRaises(ValueError):
            runner.simulate({"schema_version": 1, "case": {}, "train": {"chain": []}})
        with self.assertRaises(ValueError):
            runner.simulate({"schema_version": 1, "case": {}, "train": {"chain": [1, 2]}})

    def test_reports_unsupported_when_no_unit_is_modeled(self) -> None:
        record = runner.simulate({
            "schema_version": 1,
            "case": CASE,
            "train": {"chain_id": "chain-1", "chain": ["Adsorption", "Coagulation"]},
        })
        self.assertEqual(record["status"], "unsupported")
        self.assertEqual(record["coverage"]["modeled"], [])
        self.assertEqual(record["coverage"]["unsupported"], ["Adsorption", "Coagulation"])
        self.assertEqual(record["solver"]["status"], "not_run")

    def test_reports_error_when_backend_is_missing(self) -> None:
        if runner.environment_report()["available"]:
            self.skipTest("a real simulation backend is installed in this interpreter")
        record = runner.simulate({
            "schema_version": 1,
            "case": CASE,
            "train": {"chain_id": "chain-1", "chain": ["Pumping", "Reverse Osmosis"]},
        })
        self.assertEqual(record["status"], "error")
        self.assertIn("not installed", record["error"])

    def test_declared_basis_is_reported_and_never_invented(self) -> None:
        salinity, source = runner.feed_salinity_g_l({"case": {"water_quality": {"tds_mg_L": 2500}}, "options": {}})
        self.assertAlmostEqual(salinity, 2.5)
        self.assertIn("TDS", source)
        salinity, _ = runner.feed_salinity_g_l({"case": {"water_quality": {}}, "options": {"feed_salinity_g_L": 1.25}})
        self.assertAlmostEqual(salinity, 1.25)
        salinity, _ = runner.feed_salinity_g_l({"case": {}, "options": {}})
        self.assertIsNone(salinity)
        flow, _ = runner.design_flow_m3_day({"case": CASE, "options": {}})
        self.assertAlmostEqual(flow, 250.0)
        flow, _ = runner.design_flow_m3_day({"case": {}, "options": {}})
        self.assertIsNone(flow)


class FakeSimulationBackendTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="hydroweaver-sim-test-")
        self.root = Path(self.temporary.name)
        self._write_fakes()

    def tearDown(self) -> None:
        for name in [m for m in sys.modules if m.startswith(("pyomo", "idaes", "watertap"))]:
            del sys.modules[name]
        self.temporary.cleanup()

    def _write(self, relative: str, content: str) -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(content).lstrip(), encoding="utf-8")

    def _write_fakes(self) -> None:
        self._write("pyomo/__init__.py", "")
        self._write("pyomo/environ.py", fake_modules.FAKE_PYOMO)
        self._write("pyomo/network.py", "from pyomo.environ import Arc\n\n__all__ = ['Arc']\n")
        self._write("idaes/__init__.py", "")
        self._write("idaes/core/__init__.py", "from idaes.core.flowsheet import FlowsheetBlock\n\n__all__ = ['FlowsheetBlock']\n")
        self._write("idaes/core/flowsheet.py", fake_modules.FAKE_IDAES)
        self._write("idaes/core/solvers/__init__.py", "from idaes.core.solvers.config import get_solver\n\n__all__ = ['get_solver']\n")
        self._write("idaes/core/solvers/config.py", fake_modules.FAKE_IDAES)
        self._write("idaes/core/util/__init__.py", "")
        self._write("idaes/core/util/scaling.py", fake_modules.FAKE_IDAES_UTIL)
        self._write("idaes/core/util/model_statistics.py", fake_modules.FAKE_IDAES_UTIL)
        self._write("idaes/core/util/initialization.py", fake_modules.FAKE_IDAES_UTIL)
        self._write("idaes/models/__init__.py", "")
        self._write("idaes/models/unit_models/__init__.py", fake_modules.FAKE_IDAES_MODELS)
        self._write("watertap/__init__.py", "")
        self._write("watertap/core/__init__.py", "")
        self._write("watertap/core/solvers/__init__.py", fake_modules.FAKE_WATERTAP_SOLVERS)
        self._write("watertap/core/util/__init__.py", "")
        self._write("watertap/core/util/unit_models.py", fake_modules.FAKE_WATERTAP_UNIT_MODELS)
        self._write("watertap/property_models/__init__.py", "")
        self._write("watertap/property_models/NaCl_prop_pack.py", fake_modules.FAKE_PROPERTY)
        self._write("watertap/unit_models/__init__.py", "")
        self._write("watertap/unit_models/pressure_changer.py", fake_modules.FAKE_PRESSURE_CHANGER)
        self._write("watertap/unit_models/reverse_osmosis_0D.py", fake_modules.FAKE_RO_0D)
        # Extend the fake pyomo environ with the unit-model block structure.
        path = self.root / "pyomo" / "environ.py"
        path.write_text(path.read_text(encoding="utf-8") + textwrap.dedent(fake_modules.PYOMO_BLOCK_EXTENSION), encoding="utf-8")

    def _events(self):
        import pyomo.environ as pyomo_environ

        return pyomo_environ.EVENTS

    def test_builds_seeds_initializes_and_solves_the_declared_train(self) -> None:
        sys.path.insert(0, str(self.root))
        try:
            coverage = classify(["Pumping", "Reverse Osmosis"])
            outcome = runner.build_and_solve(
                coverage["modeled"],
                coverage["specs"],
                {"case": CASE, "options": {}},
            )
        finally:
            sys.path.remove(str(self.root))

        events = self._events()
        self.assertEqual(outcome["status"], "optimal")
        self.assertEqual([unit["unit"] for unit in outcome["units"]], ["Pumping", "Reverse Osmosis"])
        # feed boundary + one arc per consecutive pair
        units = [event for event in events if event[0] == "unit"]
        self.assertEqual([event[1] for event in units], ["Feed", "Pump", "ReverseOsmosis0D"])
        self.assertEqual(len([event for event in events if event[0] == "arc"]), 2)
        # relaxed initialization: area released, objective added, DOF 1, objective removed
        initializations = [event for event in events if event[0] == "initialize"]
        self.assertEqual(initializations[0][2]["dof"], 1)
        self.assertTrue(any(event[0] == "objective" for event in events))
        self.assertTrue(any(event[0] == "del_component" for event in events))
        # operating pressure carries the atmospheric and pressure-drop floors
        self.assertAlmostEqual(outcome["basis"]["feed_salinity_g_L"], 2.5)
        self.assertAlmostEqual(outcome["basis"]["design_flow_m3_day"], 250.0)
        # declared basis is reported, and results come from the fake unit
        self.assertEqual(outcome["units"][1]["results"]["recovery_fraction"], 0.5)
        self.assertEqual(outcome["units"][1]["results"]["membrane_area_m2"], 42.0)
        self.assertAlmostEqual(outcome["flowsheet"]["product_water_flow_kg_s"], 0.25)

    def test_reports_a_build_failure_as_an_error(self) -> None:
        sys.path.insert(0, str(self.root))
        try:
            self._write("watertap/unit_models/reverse_osmosis_0D.py", fake_modules.FAKE_RO_0D + """

                def _boom(self, *args, **kwargs):
                    raise RuntimeError('upstream API changed')


                ReverseOsmosis0D.initialize = _boom
            """)
            for name in [m for m in sys.modules if m.startswith("watertap")]:
                del sys.modules[name]
            coverage = classify(["Pumping", "Reverse Osmosis"])
            with self.assertRaises(runner.FlowsheetError):
                runner.build_and_solve(coverage["modeled"], coverage["specs"], {"case": CASE, "options": {}})
        finally:
            sys.path.remove(str(self.root))


class CliTests(unittest.TestCase):
    def test_self_check_command_writes_json_output(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "selfcheck.json"
            argv = sys.argv
            sys.argv = ["runner.py", "self-check", "--output", str(output)]
            try:
                self.assertEqual(runner.main(), 0)
            finally:
                sys.argv = argv
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload["kind"], "hydroweaver.simulation-selfcheck")


if __name__ == "__main__":
    unittest.main()
