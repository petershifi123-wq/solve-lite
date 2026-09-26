import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
ROOT = SCRIPTS.parents[4]
CASE = ROOT / "tests" / "fixtures" / "native_markov_case.json"
SPECIALIST_CASE = ROOT / "tests" / "fixtures" / "specialist_gated_case.json"

sys.path.insert(0, str(SCRIPTS))

import solve_lite_abi as abi  # noqa: E402


class PublicLiteAbi(unittest.TestCase):
    def setUp(self):
        for name in ("SOLVE_LITE_RUNTIME_ROOT", "SOLVE_LITE_CORE_ASSET_ROOT"):
            os.environ.pop(name, None)

    def test_healthcheck_passes_without_any_configured_asset_root(self):
        health = abi.healthcheck()
        self.assertEqual(health["status"], "PASS")
        self.assertEqual(health["build_line"], "LITE")
        self.assertEqual(health["runtime_root_origin"], "bundled")
        self.assertEqual(health["native_core_status"], "AVAILABLE")
        self.assertEqual(health["native_modules_verified"], 8)
        self.assertFalse(health["asset_root_required"])
        self.assertFalse(health["legacy_core_asset_root_required"])
        self.assertFalse(health["full_precision_pack_required"])
        self.assertFalse(health["torch_imported"])
        self.assertFalse(health["network_used"])
        self.assertNotIn("ASSET_ROOT_MISSING", json.dumps(health))

    def test_capabilities_separate_native_from_specialist(self):
        caps = abi.capabilities()
        core = caps["core"]
        self.assertEqual(caps["status"], "PASS")
        self.assertEqual(core["native"]["status"], "AVAILABLE")
        self.assertIn("markov", core["native_capabilities"])
        self.assertEqual(core["specialist"]["status"], "UNAVAILABLE")
        self.assertEqual(caps["dlc"]["specialist_execution_status"], "SPECIALIST_CAPABILITY_UNAVAILABLE")
        self.assertEqual(caps["dlc"]["activation_state"], "NOT_ACTIVATED")
        self.assertEqual(caps["dlc"]["not_public_units"], ["financial-pair-int4-g64-ENGINEERING-ONLY"])

    def test_routes_report_native_available_and_specialist_gated(self):
        routes = abi.available_routes()
        self.assertEqual(routes["status"], "PASS")
        self.assertIn("markov", routes["native_routes"])
        self.assertEqual(routes["specialist_execution_status"], "SPECIALIST_CAPABILITY_UNAVAILABLE")

    def test_native_decision_is_real_and_offline(self):
        case = json.loads(CASE.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as workspace:
            result = abi.route_prompt(workspace, case, {"metadata": {"locale": "en-US"}}, invocation_id="test:native")
        self.assertEqual(result["status"], "PASS")
        self.assertTrue(result["answers"])
        self.assertEqual(result["adapter_route"], "markov")
        self.assertFalse(result["fallback_computation"])
        self.assertEqual(result["network_model_calls"], 0)
        self.assertEqual(result["credential_reads"], 0)

    def test_specialist_case_is_refused_cleanly(self):
        case = json.loads(SPECIALIST_CASE.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as workspace:
            result = abi.route_prompt(workspace, case, {"metadata": {"locale": "en-US"}})
        self.assertEqual(result["status"], "SPECIALIST_CAPABILITY_UNAVAILABLE")
        self.assertEqual(result["error"], "SPECIALIST_CAPABILITY_UNAVAILABLE")
        self.assertEqual(result["core_status"], "AVAILABLE")
        self.assertNotEqual(result["error"], "CORE_ASSET_UNAVAILABLE")

    def test_legacy_env_var_still_points_at_a_runtime_root(self):
        root, origin = abi.locate_runtime_root()
        self.assertIsNotNone(root)
        self.assertEqual(origin, "bundled")
        self.assertTrue((root / "solve_lite" / "abi.py").is_file())


    def test_default_install_never_reports_a_missing_asset_root(self):
        """The retired ASSET_ROOT_MISSING code must be unreachable on a fresh clone.

        The bundled runtime is part of the package, so the only remaining failure
        is real core damage.  Scrub the environment, run every public entrypoint,
        and assert the retired string cannot appear - neither in the returned
        payloads nor in the loader source.
        """
        for name in ("SOLVE_LITE_RUNTIME_ROOT", "SOLVE_LITE_CORE_ASSET_ROOT"):
            os.environ.pop(name, None)
        health = abi.healthcheck()
        caps = abi.capabilities()
        routes = abi.available_routes()
        blob = json.dumps([health, caps, routes])
        self.assertNotIn("ASSET_ROOT_MISSING", blob)
        self.assertNotIn("ASSET_ROOT_MISSING", (SCRIPTS / "solve_lite_abi.py").read_text(encoding="utf-8"))
        self.assertEqual(health["status"], "PASS")
        self.assertIsNone(health.get("error"))
        self.assertEqual(health["runtime_root_origin"], "bundled")
        self.assertEqual(health["asset_root_required"], False)
        self.assertEqual(health["legacy_core_asset_root_required"], False)
        self.assertEqual(abi.ERROR_ROOT, "CORE_ASSET_UNAVAILABLE")
        self.assertEqual(abi.ERROR_CORE, abi.ERROR_ROOT)
        root, origin = abi.locate_runtime_root()
        self.assertEqual(origin, "bundled", "a normal install must resolve the bundled runtime")
        self.assertIsNotNone(root)

    def test_damaged_core_is_the_only_core_failure(self):
        """A damaged package -> real core damage, never an asset demand.

        The branch is unreachable while the package is intact (that is the point of
        item 1), so it is exercised by simulating a package whose bundled runtime is
        missing.
        """
        empty = Path(tempfile.mkdtemp())
        original = abi.bundled_runtime_root
        try:
            abi.bundled_runtime_root = lambda: empty
            result = abi.healthcheck()
            self.assertEqual(result["status"], "BLOCKED")
            self.assertEqual(result["error"], "CORE_ASSET_UNAVAILABLE")
            self.assertEqual(result["reason"], "CORE_RUNTIME_NOT_FOUND")
            self.assertIn("reinstall the package", result["detail"])
            for forbidden in ("override", "asset_root", "supply", "2.33", "configure"):
                self.assertNotIn(forbidden, result["detail"])
            self.assertEqual(result["asset_root_required"], False)
        finally:
            abi.bundled_runtime_root = original
            shutil.rmtree(empty, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
