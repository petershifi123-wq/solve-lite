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

import compact_runtime  # noqa: E402
import solve_lite_abi as abi  # noqa: E402


class PublicLiteAbi(unittest.TestCase):
    def setUp(self):
        self._shared_tmp = tempfile.TemporaryDirectory()
        os.environ["SOLVE_LITE_SHARED_RUNTIME_ROOT"] = str(Path(self._shared_tmp.name) / "not-installed")

    def tearDown(self):
        os.environ.pop("SOLVE_LITE_SHARED_RUNTIME_ROOT", None)
        self._shared_tmp.cleanup()

    def test_current_asset_contract_is_pinned(self):
        document = compact_runtime.manifest()
        self.assertEqual(document["current_install_target"], "v0.1.11")
        self.assertEqual(document["runtime"]["shared_encoder_copies"], 1)
        self.assertEqual(document["runtime"]["network_calls_at_runtime"], 0)
        self.assertFalse(document["runtime"]["torch_runtime"])
        self.assertFalse(document["runtime"]["transformers_runtime"])
        self.assertEqual(len(document["asset"]["immutable_revision"]), 40)

    def test_native_health_and_route_are_available_without_model_setup(self):
        health = abi.healthcheck()
        self.assertEqual(health["status"], "PASS")
        self.assertEqual(health["native_core_status"], "AVAILABLE")
        case = json.loads(CASE.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as workspace:
            result = abi.route_prompt(workspace, case, {"metadata": {"locale": "en-US"}})
        self.assertEqual(result["status"], "PASS")
        self.assertTrue(result["answers"])
        self.assertEqual(result["network_model_calls"], 0)

    def test_specialist_route_fails_structurally_when_shared_asset_is_absent(self):
        case = json.loads(SPECIALIST_CASE.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as workspace:
            result = abi.route_prompt(workspace, case, {"metadata": {"locale": "en-US"}})
        self.assertEqual(result["status"], "SPECIALIST_CAPABILITY_UNAVAILABLE")
        self.assertEqual(result["reason"], "COMPACT_RUNTIME_NOT_INSTALLED")
        self.assertEqual(result["network_model_calls"], 0)

    def test_damaged_core_is_reported_without_requesting_user_configuration(self):
        empty = Path(tempfile.mkdtemp())
        original = abi.bundled_runtime_root
        try:
            abi.bundled_runtime_root = lambda: empty
            result = abi.healthcheck()
            self.assertEqual(result["status"], "BLOCKED")
            self.assertEqual(result["error"], "CORE_ASSET_UNAVAILABLE")
            for forbidden in ("override", "supply", "configure", "2.33"):
                self.assertNotIn(forbidden, result.get("detail", ""))
        finally:
            abi.bundled_runtime_root = original
            shutil.rmtree(empty, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
