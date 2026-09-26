import hashlib
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "solve-lite"
SKILL = PLUGIN / "skills" / "solve-lite"
SCRIPTS = SKILL / "scripts"


class PublicPackageContractTest(unittest.TestCase):
    def test_required_surface(self):
        required = (
            "README.md",
            "LICENSE",
            "NOTICE.md",
            "COMPATIBILITY.md",
            "CHANGELOG.md",
            "CORE_ASSET_MANIFEST.json",
            "CORE_ASSET_MANIFEST_FULL_FP_REFERENCE.json",
            "PUBLIC_REPO_MANIFEST.json",
            "SHA256SUMS.txt",
            ".agents/plugins/marketplace.json",
            "tools/startup_check.py",
            "tools/installer.py",
            "tools/doctor.py",
            "tools/uninstall.py",
            "tools/adapter.py",
            "tools/offline_harness.py",
            "plugins/solve-lite/skills/solve-lite/SKILL.md",
            "plugins/solve-lite/skills/solve-lite/runtime/solve_lite/abi.py",
            "plugins/solve-lite/skills/solve-lite/scripts/agent_auto.py",
            "plugins/solve-lite/skills/solve-lite/scripts/solve_lite_abi.py",
            "plugins/solve-lite/skills/solve-lite/scripts/solve_lite_dlc.py",
            "plugins/solve-lite/skills/solve-lite/scripts/test_agent_auto.py",
            "plugins/solve-lite/skills/solve-lite/scripts/test_solve_lite_abi.py",
            "plugins/solve-lite/skills/solve-lite/scripts/test_solve_lite_dlc.py",
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

    def test_lite_core_is_bundled_and_byte_verified(self):
        core = json.loads((ROOT / "CORE_ASSET_MANIFEST.json").read_text(encoding="utf-8"))
        self.assertEqual(core["build_line"], "LITE")
        self.assertEqual(core["public_self_contained_distribution"], True)
        self.assertEqual(core["artifacts_in_public_tree"], True)
        self.assertTrue(core["distribution"])
        self.assertEqual(len(core["artifacts"]), 8)
        self.assertEqual(core["public_abi"]["status"], "AVAILABLE")
        self.assertEqual(core["public_abi"]["public_entry"], "route_prompt")
        self.assertEqual(core["public_abi"]["core_native_entry"], "route_session")
        runtime_root = ROOT / core["runtime_root"]
        self.assertTrue((runtime_root / "solve_lite" / "abi.py").is_file())
        total = 0
        for artifact in core["artifacts"]:
            path = runtime_root / artifact["relative_path"]
            self.assertTrue(path.is_file(), artifact["relative_path"])
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), artifact["sha256"], artifact["relative_path"])
            self.assertEqual(path.stat().st_size, artifact["bytes"], artifact["relative_path"])
            total += artifact["bytes"]
        self.assertEqual(total, core["artifact_bytes"])
        self.assertEqual(core["runtime_root_env_required"], False)
        self.assertEqual(core["legacy_core_asset_root_env_required"], False)
        self.assertEqual(core["runtime_root_env"], "SOLVE_LITE_RUNTIME_ROOT")
        self.assertEqual(core["legacy_core_asset_root_env"], "SOLVE_LITE_CORE_ASSET_ROOT")
        assets = core["runtime_model_assets"]
        self.assertEqual(assets["status"], "OPTIONAL_DLC_COMPONENTS")
        self.assertEqual(assets["auto_download"], False)
        self.assertEqual(assets["specialist_model_assets_required_at_startup"], False)
        self.assertEqual(assets["missing_pack_status"], "SPECIALIST_CAPABILITY_UNAVAILABLE")
        self.assertEqual([item["unit_id"] for item in assets["not_published"]], ["financial-pair-int4-g64-ENGINEERING-ONLY"])
        self.assertEqual(len([item for item in assets["dlc_units"] if item["public"]]), 3)
        self.assertFalse(any(path.name == "OWNER_RUNTIME_ASSET_MANIFEST.json" for path in ROOT.rglob("*")))

    def test_full_precision_reference_is_historical(self):
        reference = json.loads((ROOT / "CORE_ASSET_MANIFEST_FULL_FP_REFERENCE.json").read_text(encoding="utf-8"))
        self.assertEqual(reference["status"], "HISTORICAL_FULL_PRECISION_REFERENCE")
        self.assertEqual(reference["historical_reference"], True)
        self.assertEqual(reference["not_an_install_requirement"], True)
        self.assertEqual(reference["superseded_by"], "CORE_ASSET_MANIFEST.json")

    def test_healthcheck_works_without_any_asset_root(self):
        environment = dict(os.environ)
        for name in ("SOLVE_LITE_RUNTIME_ROOT", "SOLVE_LITE_CORE_ASSET_ROOT"):
            environment.pop(name, None)
        script = (
            "import json,sys;"
            f"sys.path.insert(0,{str(SCRIPTS)!r});"
            "from solve_lite_abi import healthcheck, capabilities;"
            "print(json.dumps({'h': healthcheck(), 'c': capabilities()}))"
        )
        process = subprocess.run([sys.executable, "-c", script], cwd=str(ROOT), env=environment,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
        self.assertEqual(process.returncode, 0, process.stderr)
        payload = json.loads(process.stdout.strip().splitlines()[-1])
        self.assertEqual(payload["h"]["status"], "PASS")
        self.assertEqual(payload["h"]["runtime_root_origin"], "bundled")
        self.assertEqual(payload["h"]["asset_root_required"], False)
        self.assertEqual(payload["h"]["torch_imported"], False)
        self.assertEqual(payload["h"]["network_used"], False)
        self.assertEqual(payload["c"]["status"], "PASS")
        self.assertIn("markov", payload["c"]["core"]["native_capabilities"])
        self.assertEqual(payload["c"]["dlc"]["activation_state"], "NOT_ACTIVATED")

    def test_registry_and_entrypoint_truth(self):
        registry = json.loads((SKILL / "assets" / "agent_registry.json").read_text(encoding="utf-8"))
        self.assertEqual(registry["public_abi_entrypoint"], "solve_lite_abi:route_prompt")
        self.assertTrue(registry["cold_fork_test"].startswith("PASS_VERIFIED"))
        self.assertEqual(registry["cold_fork_evidence"]["scope"], "PUBLIC_REPOSITORY_ONLY")
        by_id = {host["host_id"]: host for host in registry["hosts"]}
        for host in ("doubao", "workbuddy"):
            self.assertEqual(by_id[host]["cold_fork_status"], "PASS_VERIFIED_FRESH_INSTALL_PUBLIC_ABI")
        for host in ("cline", "qwen", "cursor"):
            self.assertNotEqual(by_id[host]["cold_fork_status"], "BLOCKED_PENDING_CLEAN_HOST_AND_PUBLIC_CORE_ASSET")

    def test_retired_missing_asset_root_code_is_gone(self):
        source = (SCRIPTS / "solve_lite_abi.py").read_text(encoding="utf-8")
        self.assertNotIn("ASSET_ROOT_MISSING", source)
        sys.path.insert(0, str(SCRIPTS))
        import solve_lite_abi as abi
        self.assertEqual(abi.ERROR_ROOT, "CORE_ASSET_UNAVAILABLE")
        self.assertEqual(abi.ERROR_ROOT, abi.ERROR_CORE)

    def test_no_sensitive_paths_or_private_records(self):
        home_prefix = "/" + "Users" + "/"
        hits = []
        for path in ROOT.rglob("*"):
            if path.is_file() and path.suffix.lower() in {".py", ".md", ".json", ".txt"}:
                if home_prefix in path.read_text(encoding="utf-8", errors="replace"):
                    hits.append(path.relative_to(ROOT).as_posix())
        self.assertEqual(hits, [])
        self.assertFalse((ROOT / "evidence").exists())
        addon = SKILL / "runtime" / "addons"
        self.assertFalse(addon.exists(), "local DLC install state must not ship in the package")
        self.assertFalse(any(path.name == "OWNER_RUNTIME_ASSET_MANIFEST.json" for path in ROOT.rglob("*")))


if __name__ == "__main__":
    unittest.main()

