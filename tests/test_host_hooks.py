import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins/solve-lite"

spec = importlib.util.spec_from_file_location("host_hooks", ROOT / "tools/host_hooks.py")
host_hooks = importlib.util.module_from_spec(spec)
assert spec.loader
sys.modules[spec.name] = host_hooks
spec.loader.exec_module(host_hooks)


class ThinHostAdapterTest(unittest.TestCase):
    def test_portable_command_uses_explicit_message_not_implicit_clipboard(self):
        command = host_hooks.one_step_command(PLUGIN)
        self.assertIn('--text "<EXACT_USER_MESSAGE>"', command)
        self.assertNotIn("--clipboard", command)

    def test_eighteen_registry_driven_hosts_declared(self):
        registry = json.loads((PLUGIN / "skills/solve-lite/assets/agent_registry.json").read_text())
        host_ids = {row["host_id"] for row in registry["hosts"]}
        self.assertEqual(len(host_ids), 18)
        self.assertEqual(set(host_hooks.supported_host_ids()), host_ids)
        self.assertEqual(registry["declared_host_profiles"], 18)

    def test_unverified_profiles_are_not_promoted_to_pass(self):
        registry = json.loads((PLUGIN / "skills/solve-lite/assets/agent_registry.json").read_text())
        by_id = {row["host_id"]: row for row in registry["hosts"]}
        for host_id in set(by_id) - {"workbuddy", "doubao", "codex", "hermes"}:
            self.assertNotIn("PASS_VERIFIED", by_id[host_id]["compatibility_status"])

    def test_registry_aliases_resolve_without_hardcoded_argparse_choices(self):
        self.assertEqual(host_hooks.host_spec("claude").host_id, "claude-code")
        self.assertEqual(host_hooks.host_spec("copilot").host_id, "github-copilot")
        self.assertEqual(host_hooks.host_spec("qwen").host_id, "qwen-code")

    def test_each_adapter_has_pointer_and_no_heavy_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime = root / "runtime/v0.1.11"
            runtime.mkdir(parents=True)
            for host in ("workbuddy", "doubao", "codex", "hermes"):
                destination = root / "hosts" / host
                report = host_hooks.register(host, PLUGIN, override=destination, shared_runtime_root=runtime)
                self.assertEqual(report["status"], "PASS", host)
                if host == "workbuddy":
                    adapter = destination / "plugins/marketplaces/solve-lite-local/plugins/solve-lite"
                else:
                    adapter = destination
                pointer = json.loads((adapter / ".solve-lite-runtime.json").read_text())
                self.assertEqual(Path(pointer["runtime_root"]), runtime.resolve())
                self.assertEqual(host_hooks._shared_runtime_module(adapter).adapter_heavy_paths(adapter), [])

    def test_all_declared_profiles_build_thin_installs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime = root / "runtime/v0.1.11"
            runtime.mkdir(parents=True)
            for host_id in host_hooks.supported_host_ids():
                if host_id in {"workbuddy", "doubao", "codex", "hermes"}:
                    continue
                destination = root / "hosts" / host_id
                report = host_hooks.register(
                    host_id, PLUGIN, override=destination, shared_runtime_root=runtime
                )
                self.assertEqual(report["status"], "PASS", host_id)
                self.assertTrue((destination / "SKILL.md").is_file(), host_id)
                self.assertIn("<EXACT_USER_MESSAGE>", report["one_step_command"])

    def test_auto_detects_codex_from_default_config_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".codex").mkdir()
            original = host_hooks._home
            try:
                host_hooks._home = lambda: root
                with mock.patch.dict(os.environ, {}, clear=True), \
                        mock.patch.object(host_hooks.shutil, "which", return_value=None):
                    self.assertEqual(host_hooks.resolve_auto(), "codex")
            finally:
                host_hooks._home = original

    def test_auto_detects_hermes_from_default_config_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".hermes").mkdir()
            original = host_hooks._home
            try:
                host_hooks._home = lambda: root
                with mock.patch.dict(os.environ, {}, clear=True), \
                        mock.patch.object(host_hooks.shutil, "which", return_value=None):
                    self.assertEqual(host_hooks.resolve_auto(), "hermes")
            finally:
                host_hooks._home = original

    def test_auto_explicit_alias_resolves_and_unknown_fails_closed(self):
        with mock.patch.dict(os.environ, {"SOLVE_LITE_HOST": "claude"}, clear=True):
            self.assertEqual(host_hooks.resolve_auto(), "claude-code")
        with mock.patch.dict(os.environ, {"SOLVE_LITE_HOST": "unknown-host"}, clear=True):
            self.assertEqual(host_hooks.resolve_auto(), "generic")

    def test_auto_ambiguous_filesystem_fails_closed_to_generic(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".codex").mkdir()
            (root / ".hermes").mkdir()
            original = host_hooks._home
            try:
                host_hooks._home = lambda: root
                with mock.patch.dict(os.environ, {}, clear=True), \
                        mock.patch.object(host_hooks.shutil, "which", return_value=None):
                    self.assertEqual(host_hooks.resolve_auto(), "generic")
            finally:
                host_hooks._home = original


if __name__ == "__main__":
    unittest.main()
