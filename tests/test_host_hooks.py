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
    def test_four_hosts_registered(self):
        registry = json.loads((PLUGIN / "skills/solve-lite/assets/agent_registry.json").read_text())
        self.assertEqual({row["host_id"] for row in registry["hosts"]}, {"workbuddy", "doubao", "codex", "hermes"})

    def test_each_adapter_has_pointer_and_no_heavy_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime = root / "runtime/v0.1.10"
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

    def test_auto_detects_codex_from_default_config_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".codex").mkdir()
            original = host_hooks._home
            try:
                host_hooks._home = lambda: root
                with mock.patch.dict(os.environ, {}, clear=True):
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
                with mock.patch.dict(os.environ, {}, clear=True):
                    self.assertEqual(host_hooks.resolve_auto(), "hermes")
            finally:
                host_hooks._home = original


if __name__ == "__main__":
    unittest.main()
