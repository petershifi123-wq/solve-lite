import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
ASSETS = SCRIPTS.parent / "assets"
sys.path.insert(0, str(SCRIPTS))

import specialist_runtime as runtime  # noqa: E402


class SpecialistRuntimeContract(unittest.TestCase):
    def test_lock_is_exact_and_hash_verified(self):
        spec = runtime.load_lock()
        lock = ASSETS / spec["requirements"]["lock_path"]
        self.assertTrue(lock.is_file())
        self.assertEqual(hashlib.sha256(lock.read_bytes()).hexdigest(), spec["requirements"]["lock_sha256"])
        rows = [line.split(" \\", 1)[0] for line in lock.read_text(encoding="utf-8").splitlines()
                if line and not line.startswith((" ", "#", "-")) and "==" in line]
        self.assertEqual(len(rows), 24)
        self.assertIn("torch==2.8.0", rows)
        self.assertIn("transformers==4.51.3", rows)
        self.assertIn("tokenizers==0.21.4", rows)
        self.assertIn("safetensors==0.7.0", rows)

    def test_import_does_not_import_specialist_packages(self):
        code = (
            "import json,sys;sys.path.insert(0,%r);import specialist_runtime;"
            "print(json.dumps([n for n in ('torch','transformers','tokenizers','safetensors') if n in sys.modules]))"
        ) % str(SCRIPTS)
        process = subprocess.run([sys.executable, "-I", "-c", code], stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, text=True, check=False)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(json.loads(process.stdout.strip()), [])

    def test_missing_local_env_never_counts_global_packages(self):
        with tempfile.TemporaryDirectory() as root:
            result = runtime.healthcheck(root)
        self.assertEqual(result["status"], "NOT_INSTALLED")
        self.assertFalse(result["torch_imported_in_lite"])

    def test_worker_environment_is_process_scoped(self):
        with tempfile.TemporaryDirectory() as root:
            environment = runtime.worker_environment(root)
        self.assertEqual(environment["SOLVE_LITE_SPECIALIST_WORKER"], "1")
        self.assertEqual(environment["PYTHONNOUSERSITE"], "1")
        self.assertEqual(environment["SOLVE_LITE_RUNTIME_ROOT"], str(Path(root).resolve()))


if __name__ == "__main__":
    unittest.main(verbosity=2)
