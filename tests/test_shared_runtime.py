import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "plugins/solve-lite/skills/solve-lite/scripts"
sys.path.insert(0, str(SCRIPTS))

import compact_runtime
import shared_runtime


class SharedRuntimeContract(unittest.TestCase):
    def _source(self, root: Path) -> Path:
        source = root / "source-runtime"
        (source / "solve_lite").mkdir(parents=True)
        (source / "solve_lite/abi.py").write_text("VALUE = 1\n")
        for name in shared_runtime.HEAVY_RUNTIME_DIRS:
            heavy = source / name
            heavy.mkdir()
            (heavy / "must-not-copy").write_text(name)
        return source

    def test_prepare_base_is_atomic_thin_and_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._source(root)
            destination = root / "runtime/v0.1.11"
            first = shared_runtime.prepare_base(source, destination)
            second = shared_runtime.prepare_base(source, destination)
            self.assertEqual(first["status"], "PASS")
            self.assertTrue(first["created"])
            self.assertFalse(second["created"])
            self.assertEqual(first["base_tree_sha256"], second["base_tree_sha256"])
            self.assertTrue((destination / "solve_lite/abi.py").is_file())
            for name in shared_runtime.HEAVY_RUNTIME_DIRS:
                self.assertFalse((destination / name).exists())

    def test_existing_version_conflict_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._source(root)
            destination = root / "runtime/v0.1.11"
            destination.mkdir(parents=True)
            (destination / "unexpected").write_text("different")
            result = shared_runtime.prepare_base(source, destination)
            self.assertEqual(result["status"], "FAIL")
            self.assertEqual(result["reason"], "SHARED_RUNTIME_VERSION_CONFLICT")

    def test_asset_manifest_is_immutable_and_single_copy(self):
        document = compact_runtime.manifest()
        self.assertEqual(document["current_install_target"], "v0.1.11")
        self.assertEqual(document["runtime"]["shared_encoder_copies"], 1)
        self.assertEqual(len(document["asset"]["immutable_revision"]), 40)
        self.assertNotIn(document["asset"]["immutable_revision"], {"main", "master", "latest"})


if __name__ == "__main__":
    unittest.main()
