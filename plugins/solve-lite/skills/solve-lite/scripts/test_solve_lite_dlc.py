import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

import solve_lite_dlc as dlc  # noqa: E402


class DlcContract(unittest.TestCase):
    def test_public_release_units_are_pinned(self):
        units = {spec["unit_id"]: spec for spec in dlc.DLC_UNITS}
        self.assertEqual(len(units), 4)
        public = [spec for spec in dlc.DLC_UNITS if spec["public"]]
        self.assertEqual(len(public), 3)
        blocked = [spec for spec in dlc.DLC_UNITS if not spec["public"]]
        self.assertEqual([spec["route"] for spec in blocked], ["financial"])
        self.assertEqual(blocked[0]["license_class"], dlc.LICENSE_ENGINEERING_ONLY)
        for spec in dlc.DLC_UNITS:
            self.assertTrue(spec["package_sha256"] is None or len(spec["package_sha256"]) == 64)
            self.assertTrue(spec["route_dirs"])
        for spec in public:
            self.assertEqual(len(spec["package_sha256"]), 64)
            self.assertGreater(spec["package_bytes"], 1_000_000)

    def test_only_github_release_is_used(self):
        self.assertTrue(dlc.RELEASE_BASE_URL.startswith("https://github.com/"))
        self.assertIn("/releases/download/", dlc.RELEASE_BASE_URL)
        self.assertNotIn("huggingface", dlc.RELEASE_BASE_URL.lower())

    def test_import_does_not_pull_network_or_torch(self):
        code = (
            "import sys;sys.path.insert(0, %r);import solve_lite_dlc;"
            "print(sorted(m for m in ('urllib.request','ssl','torch','transformers') if m in sys.modules))"
        ) % str(SCRIPTS)
        out = subprocess.run([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True, check=True)
        self.assertEqual(json.loads(out.stdout.strip().splitlines()[-1]), [])

    def test_capability_view_is_honest_without_dlc(self):
        with tempfile.TemporaryDirectory() as workspace:
            view = dlc.capability_view(workspace)
        self.assertEqual(view["specialist_execution_status"], "SPECIALIST_CAPABILITY_UNAVAILABLE")
        self.assertEqual(view["specialist_execution_reason"], "DLC_NOT_INSTALLED")
        self.assertEqual(view["activation_state"], "NOT_ACTIVATED")
        self.assertTrue(view["installed_means_called"])
        self.assertFalse(view["preloaded"])
        self.assertFalse(view["network_used"])
        self.assertFalse(view["torch_imported"])
        self.assertEqual(view["resident_model_limit"], 1)
        self.assertEqual(list(view["not_public_units"]), ["financial-pair-int4-g64-ENGINEERING-ONLY"])

    def test_not_public_unit_refuses_install(self):
        with tempfile.TemporaryDirectory() as workspace:
            result = dlc.install_unit("financial-pair-int4-g64-ENGINEERING-ONLY", runtime_root=workspace)
        self.assertEqual(result["status"], dlc.STATUS_NOT_PUBLIC)
        self.assertEqual(result["reason"], "ENGINEERING_ONLY_NOT_EXPORTED")

    def test_uninstall_removes_registry_and_assets(self):
        with tempfile.TemporaryDirectory() as workspace:
            root = Path(workspace)
            addon = dlc.addon_root(root)
            unit = dlc.public_units()[0]
            planted = addon / "installed" / unit["unit_id"] / unit["route_dirs"][0]
            planted.mkdir(parents=True)
            (planted / "config.json").write_text("{}\n", encoding="utf-8")
            link = addon / dlc.ASSET_ROOT_DIRNAME / unit["route_dirs"][0]
            link.parent.mkdir(parents=True)
            link.symlink_to(os.path.relpath(planted, link.parent))
            document = dlc.load_registry(root)
            document["units"][unit["unit_id"]] = {"unit_id": unit["unit_id"], "status": dlc.STATUS_INSTALLED}
            dlc._write_registry(root, document)
            self.assertEqual(dlc.capability_view(root)["installed_units"], 1)
            dlc.uninstall_unit(unit["unit_id"], runtime_root=root)
            self.assertFalse(planted.exists())
            self.assertFalse(link.exists() or link.is_symlink())
            self.assertEqual(dlc.load_registry(root)["units"], {})


class DownloadResilience(unittest.TestCase):
    """Item 2: a flaky CDN must never break the install."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.once = dlc._download_once
        self.get = dlc._download
        self.backoff = dlc.DOWNLOAD_BACKOFF_SECONDS
        dlc.DOWNLOAD_BACKOFF_SECONDS = 0.0
        os.environ[dlc.ATTEMPTS_ENV] = "3"

    def tearDown(self):
        dlc._download_once = self.once
        dlc._download = self.get
        dlc.DOWNLOAD_BACKOFF_SECONDS = self.backoff
        os.environ.pop(dlc.ATTEMPTS_ENV, None)
        os.environ.pop(dlc.OFFLINE_ENV, None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_retry_then_success(self):
        payload = b"x" * 4096
        calls = {"n": 0}

        def flaky(url, part, *, offset):
            calls["n"] += 1
            if calls["n"] < 3:
                raise OSError("connection reset")
            with part.open("ab") as handle:
                handle.write(payload[offset:])
            return {"resumed": bool(offset), "offset": offset}

        dlc._download_once = flaky
        target = self.tmp / "pkg.tar.gz"
        out = dlc._download("https://example.invalid/pkg.tar.gz", target,
                            expect_sha256=hashlib.sha256(payload).hexdigest())
        self.assertEqual(out["status"], "OK")
        self.assertEqual(out["attempts"], 3)
        self.assertEqual(calls["n"], 3)
        self.assertEqual(target.read_bytes(), payload)

    def test_resume_from_partial_file(self):
        payload = b"abcdefghij" * 500
        target = self.tmp / "pkg.tar.gz"
        part = target.with_suffix(target.suffix + ".part")
        part.write_bytes(payload[:1000])
        seen = {}

        def resuming(url, part_path, *, offset):
            seen["offset"] = offset
            with part_path.open("ab") as handle:
                handle.write(payload[offset:])
            return {"resumed": True, "offset": offset}

        dlc._download_once = resuming
        out = dlc._download("https://example.invalid/pkg.tar.gz", target,
                            expect_sha256=hashlib.sha256(payload).hexdigest())
        self.assertEqual(out["status"], "OK")
        self.assertEqual(seen["offset"], 1000)
        self.assertTrue(out["resumed"])
        self.assertEqual(target.read_bytes(), payload)

    def test_checksum_mismatch_is_retried_then_reported(self):
        def bad(url, part, *, offset):
            part.write_bytes(b"not-the-expected-bytes")
            return {"resumed": False, "offset": 0}

        dlc._download_once = bad
        target = self.tmp / "pkg.tar.gz"
        out = dlc._download("https://example.invalid/pkg.tar.gz", target, expect_sha256="0" * 64)
        self.assertEqual(out["status"], "DOWNLOAD_FAILED")
        self.assertIn("SHA256_MISMATCH", out["reason"])
        self.assertEqual(out["attempts"], 3)
        self.assertFalse(target.exists())

    def test_offline_env_skips_the_network_stage(self):
        os.environ[dlc.OFFLINE_ENV] = "1"
        out = dlc._download("https://example.invalid/pkg.tar.gz", self.tmp / "pkg.tar.gz")
        self.assertEqual(out["status"], "DOWNLOAD_SKIPPED")
        self.assertEqual(out["attempts"], 0)

    def test_failed_downloads_leave_the_install_successful(self):
        def dead(url, destination, *, expect_sha256=None, log=None):
            return {"status": "DOWNLOAD_FAILED", "reason": "ATTEMPTS_EXHAUSTED", "attempts": 3,
                    "bytes": 0, "history": []}

        dlc._download = dead
        runtime = self.tmp / "runtime"
        (runtime / "solve_lite").mkdir(parents=True)
        wanted = [spec["unit_id"] for spec in dlc.public_units()]
        results = dlc.install_units(wanted, runtime_root=runtime)
        self.assertTrue(all(item["status"] == dlc.STATUS_NOT_INSTALLED for item in results))
        summary = dlc.summarise(results)
        self.assertEqual(summary["status"], "BASE_ONLY")
        self.assertTrue(summary["base_lite_unaffected"])
        self.assertEqual(summary["message"], "No specialist add-on installed; base Lite is unaffected")


class AssetRootAndRouteGating(unittest.TestCase):
    """Round 3: the asset-root view and per-route specialist gating."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.rt = self.tmp / "runtime"
        self.addon = self.rt / "addons" / "solve-lite-int4-dlc"
        (self.addon / "installed").mkdir(parents=True)
        (self.rt / "solve_lite").mkdir(parents=True)
        self.spec = dlc.public_units()[0]

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _plant(self, unit):
        installed = self.addon / "installed" / unit["unit_id"]
        for relative in unit["route_dirs"]:
            (installed / relative).mkdir(parents=True)
            (installed / relative / "config.json").write_text("{}\n", encoding="utf-8")
        document = dlc.load_registry(self.rt)
        document["units"][unit["unit_id"]] = {"unit_id": unit["unit_id"], "status": dlc.STATUS_INSTALLED}
        dlc._write_registry(self.rt, document)
        return installed



    def _capability(self):
        runtime = Path(__file__).resolve().parents[1] / "runtime"
        sys.path.insert(0, str(runtime))
        import solve_lite.lite_runtime.capability as capability
        return capability

    def test_assemble_asset_root_is_idempotent_and_self_healing(self):
        installed = self._plant(self.spec)
        first = dlc.assemble_asset_root(self.rt)
        self.assertEqual(first["status"], "PASS")
        self.assertEqual(len(first["created"]), len(self.spec["route_dirs"]))
        target = self.addon / "asset-root" / self.spec["route_dirs"][0]
        self.assertTrue(target.is_dir(), "the asset-root view must resolve")
        self.assertTrue(os.path.realpath(target).startswith(os.path.realpath(installed)))
        second = dlc.assemble_asset_root(self.rt)
        self.assertTrue(second["idempotent"])
        target.unlink()
        third = dlc.assemble_asset_root(self.rt)
        self.assertIn(self.spec["route_dirs"][0], third["created"])
        self.assertTrue(target.is_dir())

    def test_per_route_capability_reasons(self):
        capability = self._capability()
        root = self.tmp / "asset-root"
        (root / "model-cache" / "cross-encoder--nli-deberta-v3-base").mkdir(parents=True)
        nli = capability.specialist_route_status(root, "nli")
        self.assertEqual(nli["status"], "UNAVAILABLE")
        self.assertIn(nli["reason"], {"INT4_BACKEND_NOT_ACTIVATED", "PYTHON_DEPENDENCIES_MISSING"})
        os.environ[capability.INT4_BACKEND_ENV] = "1"
        try:
            activated = capability.specialist_route_status(root, "nli")
        finally:
            os.environ.pop(capability.INT4_BACKEND_ENV, None)
        if activated["missing_python_modules"]:
            self.assertEqual(activated["reason"], "PYTHON_DEPENDENCIES_MISSING")
        else:
            self.assertEqual(activated["status"], "AVAILABLE")
            self.assertEqual(activated["reason"], "INT4_BACKEND_ACTIVE")
        review = capability.specialist_route_status(root, "review")
        self.assertEqual(review["reason"], "MODEL_PACK_MISSING")
        self.assertEqual(review["missing_model_directories"], list(capability.SPECIALIST_ROUTE_DIRS["review"])
                         )
if __name__ == "__main__":
    unittest.main(verbosity=2)
