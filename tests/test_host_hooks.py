#!/usr/bin/env python3
"""Fresh-isolated contract tests for host hook installation."""

from __future__ import annotations

import importlib.util
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "solve-lite"
SPEC = importlib.util.spec_from_file_location("host_hooks", ROOT / "tools" / "host_hooks.py")
HOST_HOOKS = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = HOST_HOOKS
SPEC.loader.exec_module(HOST_HOOKS)
INSTALLER_SPEC = importlib.util.spec_from_file_location("solve_lite_installer", ROOT / "tools" / "installer.py")
INSTALLER = importlib.util.module_from_spec(INSTALLER_SPEC)
sys.modules[INSTALLER_SPEC.name] = INSTALLER
INSTALLER_SPEC.loader.exec_module(INSTALLER)


class WorkBuddyHookContract(unittest.TestCase):
    def _legacy_settings(self, config: Path) -> None:
        command = HOST_HOOKS.hook_command(PLUGIN)
        document = {
            "hooks": {
                "UserPromptSubmit": [
                    {"hooks": [{"type": "command", "command": command}]},
                    {"hooks": [{"type": "command", "command": "echo keep-me"}]},
                ]
            }
        }
        config.mkdir(parents=True)
        (config / "settings.json").write_text(json.dumps(document), encoding="utf-8")

    def test_fresh_registration_has_one_nonblocking_plugin_hook(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / ".workbuddy-ai"
            self._legacy_settings(config)

            report = HOST_HOOKS.register("workbuddy", PLUGIN, override=config)
            detected = HOST_HOOKS.detect("workbuddy", config)["config_dirs"][0]

            self.assertEqual("PASS", report["status"])
            self.assertEqual("HOOK_ACTIVE", detected["hook_state"])
            self.assertEqual(1, detected["active_solve_lite_sources"])
            self.assertEqual(0, detected["settings_solve_lite_entries"])
            self.assertEqual(1, len(detected["plugin_hook_commands"]))
            self.assertTrue(detected["plugin_script_exists"])

            command = detected["plugin_hook_commands"][0]
            self.assertIn("CODEBUDDY_PLUGIN_ROOT", command)
            self.assertIn("CLAUDE_PLUGIN_ROOT", command)
            self.assertIn("specialist-env/bin/python3", command)
            self.assertNotIn("D=${PLUGIN_ROOT", command)

            environment = dict(os.environ)
            environment.pop("CODEBUDDY_PLUGIN_ROOT", None)
            environment.pop("CLAUDE_PLUGIN_ROOT", None)
            process = subprocess.run(
                ["bash", "-c", command],
                input="{}",
                text=True,
                capture_output=True,
                env=environment,
                check=False,
            )
            self.assertEqual(0, process.returncode, process.stderr)

    def test_reinstall_is_idempotent_and_preserves_foreign_hook(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / ".workbuddy-ai"
            self._legacy_settings(config)
            HOST_HOOKS.register("workbuddy", PLUGIN, override=config)
            HOST_HOOKS.register("workbuddy", PLUGIN, override=config)

            detected = HOST_HOOKS.detect("workbuddy", config)["config_dirs"][0]
            settings = json.loads((config / "settings.json").read_text(encoding="utf-8"))
            commands = [
                hook["command"]
                for group in settings["hooks"]["UserPromptSubmit"]
                for hook in group.get("hooks", [])
            ]
            self.assertEqual(["echo keep-me"], commands)
            self.assertEqual(1, detected["active_solve_lite_sources"])
            self.assertEqual(1, len(detected["plugin_hook_commands"]))

    def test_plugin_copy_preserves_and_relocates_runtime_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source-plugin"
            shutil.copytree(PLUGIN, source, symlinks=True)
            runtime = source / "skills" / "solve-lite" / "runtime"
            bootstrap = runtime / "specialist-python" / "python" / "bin" / "python3"
            bootstrap.parent.mkdir(parents=True)
            bootstrap.write_text("stub\n", encoding="utf-8")
            bootstrap.chmod(0o755)
            venv = runtime / "specialist-env"
            (venv / "bin").mkdir(parents=True)
            (venv / "bin" / "python3").symlink_to(bootstrap)
            (venv / "pyvenv.cfg").write_text("home = %s\n" % bootstrap.parent, encoding="utf-8")

            config = root / ".workbuddy-ai"
            HOST_HOOKS.register("workbuddy", source, override=config)
            copied_runtime = config / "plugins/marketplaces/solve-lite-local/plugins/solve-lite/skills/solve-lite/runtime"
            copied_python = copied_runtime / "specialist-env/bin/python3"
            self.assertTrue(copied_python.is_symlink())
            self.assertEqual(
                copied_python.resolve(),
                (copied_runtime / "specialist-python/python/bin/python3").resolve(),
            )
            self.assertNotIn(str(runtime), (copied_runtime / "specialist-env/pyvenv.cfg").read_text())

    def test_doubao_no_hook_requires_every_fallback_proof(self) -> None:
        detected = {"skill_installed": True, "mandatory_first_step_present": True}
        selftest = {
            "HOOK_FIRED": "PASS",
            "checks": {"ENVELOPE_INJECTED": True, "NO_MODEL_DISCRETION": True},
        }
        accepted = INSTALLER.no_native_hook_acceptance(
            PLUGIN, "doubao", detected, selftest, "none"
        )
        self.assertTrue(all(accepted.values()), accepted)

        missing_banner = dict(detected, mandatory_first_step_present=False)
        rejected = INSTALLER.no_native_hook_acceptance(
            PLUGIN, "doubao", missing_banner, selftest, "none"
        )
        self.assertFalse(all(rejected.values()), rejected)

    def test_doubao_registration_reports_expected_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spec = HOST_HOOKS.HostSpec(
                host_id="doubao",
                display="Doubao test",
                hook_api="none",
                hook_api_evidence="test fixture",
                skill_dest=Path(tmp) / "solve-lite",
                skill_locator="fixture",
            )
            with mock.patch.object(HOST_HOOKS, "_hosts", return_value={"doubao": spec}):
                report = HOST_HOOKS.register("doubao", PLUGIN)
                detected = HOST_HOOKS.detect("doubao")
            self.assertEqual("UNAVAILABLE_EXPECTED", report["status"])
            self.assertEqual("UNAVAILABLE_EXPECTED", report["native_hook_api"])
            self.assertTrue(detected["skill_installed"])
            self.assertTrue(detected["mandatory_first_step_present"])


class InstalledCopyTruthRegressions(unittest.TestCase):
    class FakeDlc:
        DLC_UNITS = ()

    def _destination(self, root: Path) -> tuple[Path, object]:
        destination = root / "installed-solve-lite"
        runtime = destination / "runtime"
        addon = runtime / "addons" / "solve-lite-int4-dlc"
        python = runtime / "specialist-env" / "bin" / "python3"
        python.parent.mkdir(parents=True)
        python.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        python.chmod(0o755)
        (destination / "SKILL.md").write_text("current installed skill\n", encoding="utf-8")
        (runtime / "CORE_ASSET_MANIFEST_LITE.json").write_text("{}\n", encoding="utf-8")
        units = []
        registry_units = {}
        for route in ("review", "topic", "nli"):
            payload = (route + "-weights").encode("utf-8")
            weights_sha = hashlib.sha256(payload).hexdigest()
            unit_id = route + "-fixture"
            installed = addon / "installed" / unit_id
            route_dir = installed / "model-cache" / (route + "-model")
            route_dir.mkdir(parents=True)
            (route_dir / "model.slint4.safetensors").write_bytes(payload)
            package_sha = hashlib.sha256((route + "-package").encode("utf-8")).hexdigest()
            (installed / "dlc.json").write_text(json.dumps({
                "source_package_sha256": package_sha,
                "weights_sha256": weights_sha,
            }), encoding="utf-8")
            units.append({
                "unit_id": unit_id,
                "public": True,
                "package_sha256": package_sha,
                "weights_sha256": weights_sha,
                "container_name": "model.slint4.safetensors",
                "route_dirs": ("model-cache/" + route + "-model",),
            })
            registry_units[unit_id] = {
                "package_sha256": package_sha,
                "observed_package_sha256": package_sha,
            }
        units.append({
            "unit_id": "financial-fixture", "public": False,
            "package_sha256": None, "weights_sha256": None,
            "container_name": "model.slint4.safetensors", "route_dirs": (),
        })
        addon.mkdir(parents=True, exist_ok=True)
        (addon / "dlc-registry.json").write_text(json.dumps({
            "runtime_root": str(runtime.resolve()), "units": registry_units,
        }), encoding="utf-8")
        dlc = self.FakeDlc()
        dlc.DLC_UNITS = tuple(units)
        return destination, dlc

    def test_false_source_pass_regression(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "missing-installed-copy"
            report = INSTALLER.installed_destination_readback(destination, self.FakeDlc())
            self.assertEqual("FAIL", report["status"])
            self.assertFalse(report["checks"]["DESTINATION_EXISTS"])

    def test_old_skill_hash_regression(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            destination, dlc = self._destination(Path(tmp))
            expected = INSTALLER.installed_destination_readback(destination, dlc)
            (destination / "SKILL.md").write_text("old baseline\n", encoding="utf-8")
            report = INSTALLER.installed_destination_readback(destination, dlc, expected)
            self.assertEqual("FAIL", report["status"])
            self.assertFalse(report["destination_hash_match"])

    def test_missing_dlc_regression(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            destination, dlc = self._destination(Path(tmp))
            shutil.rmtree(destination / "runtime/addons/solve-lite-int4-dlc/installed/topic-fixture")
            report = INSTALLER.installed_destination_readback(destination, dlc)
            self.assertEqual("FAIL", report["status"])
            self.assertFalse(report["checks"]["DEST_PUBLIC_DLC_COMPLETE"])

    def test_missing_venv_regression(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            destination, dlc = self._destination(Path(tmp))
            (destination / INSTALLER.INSTALLED_VENV_PYTHON_REL).unlink()
            report = INSTALLER.installed_destination_readback(destination, dlc)
            self.assertEqual("FAIL", report["status"])
            self.assertFalse(report["checks"]["DEST_SPECIALIST_PYTHON_EXISTS"])

    def test_destination_mutation_regression(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            destination, dlc = self._destination(Path(tmp))
            expected = INSTALLER.installed_destination_readback(destination, dlc)
            (destination / "unexpected-after-copy.txt").write_text("mutated\n", encoding="utf-8")
            report = INSTALLER.installed_destination_readback(destination, dlc, expected)
            self.assertEqual("FAIL", report["status"])
            self.assertFalse(report["checks"]["DESTINATION_HASH_MATCH"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
