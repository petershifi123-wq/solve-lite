import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "solve-lite"
SCRIPTS = PLUGIN / "skills" / "solve-lite" / "scripts"


class PublicPackageContractTest(unittest.TestCase):
    def test_required_surface(self):
        required = (
            "README.md",
            "LICENSE",
            "NOTICE.md",
            "COMPATIBILITY.md",
            "CHANGELOG.md",
            "CORE_ASSET_MANIFEST.json",
            "PUBLIC_REPO_MANIFEST.json",
            "SHA256SUMS.txt",
            ".agents/plugins/marketplace.json",
            "tools/installer.py",
            "tools/doctor.py",
            "tools/uninstall.py",
            "tools/offline_harness.py",
            "plugins/solve-lite/skills/solve-lite/scripts/agent_auto.py",
            "plugins/solve-lite/skills/solve-lite/scripts/solve_lite_abi.py",
            "plugins/solve-lite/skills/solve-lite/scripts/test_agent_auto.py",
            "plugins/solve-lite/skills/solve-lite/scripts/test_solve_lite_abi.py",
            "plugins/solve-lite/skills/solve-lite/assets/agent_registry.json",
        )
        self.assertEqual([relative for relative in required if not (ROOT / relative).is_file()], [])

    def test_public_manifest_and_checksums(self):
        manifest = json.loads((ROOT / "PUBLIC_REPO_MANIFEST.json").read_text(encoding="utf-8"))
        rows = {row["path"]: row for row in manifest["files"]}
        self.assertEqual(len(rows), manifest["payload_file_count"])
        for relative, row in rows.items():
            path = ROOT / relative
            self.assertTrue(path.is_file(), relative)
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), row["sha256"], relative)
            self.assertEqual(path.stat().st_size, row["bytes"], relative)
        sums = {}
        for line in (ROOT / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines():
            expected, relative = line.split("  ", 1)
            sums[relative] = expected
            self.assertEqual(hashlib.sha256((ROOT / relative).read_bytes()).hexdigest(), expected, relative)
        self.assertEqual(set(sums), set(rows) | {"PUBLIC_REPO_MANIFEST.json"})

    def test_closed_core_is_manifest_only(self):
        core = json.loads((ROOT / "CORE_ASSET_MANIFEST.json").read_text(encoding="utf-8"))
        self.assertFalse(core["artifacts_in_public_tree"])
        self.assertEqual(len(core["artifacts"]), 8)
        self.assertEqual(core["core_authority"], "ARCHITECTURE_A")
        self.assertFalse(core["core_rebuild"])
        self.assertFalse(core["core_binary_byte_mutation"])
        self.assertEqual(core["public_abi"]["status"], "AVAILABLE")
        self.assertEqual(core["public_abi"]["public_entry"], "route_prompt")
        self.assertEqual(core["public_abi"]["core_native_entry"], "route_session")
        self.assertFalse(core["public_self_contained_distribution"])
        runtime = core["runtime_model_assets"]
        self.assertEqual(runtime["status"], "EXTERNAL_REQUIRED")
        self.assertEqual(runtime["distribution"], "BYO_OR_OWNER_SUPPLIED")
        self.assertFalse(runtime["included_in_public_repository"])
        self.assertFalse(runtime["included_in_release"])
        self.assertFalse(runtime["auto_download"])
        self.assertFalse(runtime["fallback_computation"])
        self.assertEqual(runtime["total_files"], 109)
        self.assertEqual(runtime["total_bytes"], 2333776695)
        self.assertEqual(len(runtime["required_directories"]), 5)
        self.assertFalse(list(ROOT.rglob("*.so")))
        self.assertFalse(any(path.name == "OWNER_RUNTIME_ASSET_MANIFEST.json" for path in ROOT.rglob("*")))
        self.assertFalse((SCRIPTS / "solve_lite").exists())

    def test_registry_and_entrypoint_truth(self):
        registry = json.loads((SCRIPTS.parent / "assets" / "agent_registry.json").read_text(encoding="utf-8"))
        expected = "PASS_VERIFIED_FOUR_HOST_PUBLIC_ABI"
        passed = "PASS_VERIFIED_CLEAN_HOST_PUBLIC_ABI"
        pending = "BLOCKED_PENDING_CLEAN_HOST_AND_PUBLIC_CORE_ASSET"
        self.assertEqual(registry["public_abi_entrypoint"], "solve_lite_abi:route_prompt")
        self.assertEqual(registry["cold_fork_test"], expected)
        by_id = {host["host_id"]: host for host in registry["hosts"]}
        self.assertTrue(all(by_id[name]["cold_fork_status"] == passed for name in ("codex", "hermes", "doubao", "workbuddy")))
        self.assertTrue(all(by_id[name]["cold_fork_status"] == pending for name in ("cline", "qwen", "cursor")))

    def test_no_sensitive_paths_or_private_records(self):
        home_prefix = "/" + "Users" + "/"
        hits = []
        for path in ROOT.rglob("*"):
            if path.is_file() and path.suffix.lower() in {".py", ".md", ".json", ".txt"}:
                if home_prefix in path.read_text(encoding="utf-8", errors="replace"):
                    hits.append(path.relative_to(ROOT).as_posix())
        self.assertEqual(hits, [])
        self.assertFalse((ROOT / "evidence").exists())


if __name__ == "__main__":
    unittest.main()
