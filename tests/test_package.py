import hashlib
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "plugins/solve-lite/skills/solve-lite"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class PublicPackageContractTest(unittest.TestCase):
    def test_current_version_and_single_asset(self):
        for path in (
            ROOT / "plugins/solve-lite/.codex-plugin/plugin.json",
            ROOT / "plugins/solve-lite/.codebuddy-plugin/plugin.json",
        ):
            self.assertEqual(json.loads(path.read_text())["version"], "0.1.10")
        manifest = json.loads((SKILL / "assets/specialist-assets.json").read_text())
        self.assertEqual(manifest["current_install_target"], "v0.1.10")
        self.assertEqual(manifest["runtime"]["shared_encoder_copies"], 1)
        self.assertFalse(manifest["runtime"]["torch_runtime"])
        self.assertFalse(manifest["runtime"]["transformers_runtime"])
        self.assertEqual(manifest["asset"]["sha256"], "a7359f8581bdae0c850def19bf776e540806b960c1751b0512a3002a7cf11f7e")
        self.assertEqual(len(manifest["asset"]["immutable_revision"]), 40)

    def test_public_manifest_and_checksums(self):
        manifest = json.loads((ROOT / "PUBLIC_REPO_MANIFEST.json").read_text())
        rows = {row["path"]: row for row in manifest["files"]}
        self.assertEqual(len(rows), manifest["payload_file_count"])
        for relative, row in rows.items():
            path = ROOT / relative
            self.assertTrue(path.is_file(), relative)
            self.assertEqual(path.stat().st_size, row["bytes"], relative)
            self.assertEqual(sha256(path), row["sha256"], relative)
        sums = {}
        for line in (ROOT / "SHA256SUMS.txt").read_text().splitlines():
            expected, relative = line.split("  ", 1)
            sums[relative] = expected
            self.assertEqual(sha256(ROOT / relative), expected, relative)
        self.assertEqual(set(sums), set(rows) | {"PUBLIC_REPO_MANIFEST.json"})
        self.assertFalse(any("dlc_runtime" in path or "specialist-requirements" in path for path in rows))

    def test_active_docs_have_one_current_target(self):
        text = "\n".join((ROOT / name).read_text() for name in ("README.md", "COMPATIBILITY.md", "CHANGELOG.md"))
        self.assertIn("v0.1.10", text)
        self.assertIn("82.28%", text)
        self.assertIn("50.93", text)
        self.assertIn("CoreML", text)
        self.assertNotIn("2.33 GB", text)
        self.assertNotIn("678 MB", text)
        self.assertNotIn("solve-lite-review-compact", text)
        self.assertNotIn("solve-lite-topic-compact", text)
        self.assertNotIn("solve-lite-nli-compact", text)
        self.assertFalse((ROOT / "CORE_ASSET_MANIFEST_FULL_FP_REFERENCE.json").exists())
        for name in (
            "specialist-requirements.in",
            "specialist-requirements-macos-arm64-py39.lock",
            "specialist-runtime-lock.json",
        ):
            self.assertFalse((SKILL / "assets" / name).exists(), name)
        for relative in (
            "runtime/dlc_runtime",
            "scripts/solve_lite_dlc.py",
            "scripts/test_solve_lite_dlc.py",
            "scripts/specialist_runtime.py",
            "scripts/specialist_worker.py",
            "scripts/test_specialist_runtime.py",
        ):
            self.assertFalse((SKILL / relative).exists(), relative)
        self.assertFalse((ROOT / "tools/specialist_clean_host_harness.py").exists())

    def test_host_registry_is_thin_four_host(self):
        registry = json.loads((SKILL / "assets/agent_registry.json").read_text())
        self.assertEqual({item["host_id"] for item in registry["hosts"]}, {"doubao", "workbuddy", "codex", "hermes"})
        self.assertEqual(registry["runtime_model"], "ONE_SHARED_COREML_RUNTIME")
        self.assertEqual(registry["acceptance"]["host_heavy_copy_count"], 0)


if __name__ == "__main__":
    unittest.main()
