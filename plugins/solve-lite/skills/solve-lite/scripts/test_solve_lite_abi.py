#!/usr/bin/env python3
from __future__ import annotations

import ast
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import solve_lite_abi


EXPECTED_BLOCK = {
    "status": "BLOCKED",
    "error": "CORE_ASSET_UNAVAILABLE",
    "reason": "ASSET_ROOT_MISSING",
    "entrypoint": "solve_lite_abi:route_prompt",
    "offline": True,
    "telemetry": False,
}


class PublicAbiLoaderTest(unittest.TestCase):
    def test_healthcheck_missing_asset_is_deterministic_and_fail_closed(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(solve_lite_abi.healthcheck(), EXPECTED_BLOCK)

    def test_route_prompt_missing_asset_has_no_fallback(self):
        with patch.dict(os.environ, {}, clear=True):
            actual = solve_lite_abi.route_prompt("workspace", {"kind": "choice"}, None)
        self.assertEqual(actual, EXPECTED_BLOCK)
        self.assertNotIn("decision", actual)
        self.assertNotIn("probabilities", actual)
        self.assertNotIn("reward", actual)

    def test_empty_asset_root_fails_before_import(self):
        with tempfile.TemporaryDirectory() as temporary:
            actual = solve_lite_abi.load_core(temporary)
        self.assertEqual(actual["status"], "BLOCKED")
        self.assertEqual(actual["error"], "CORE_ASSET_UNAVAILABLE")
        self.assertEqual(actual["reason"], "ASSET_FILE_MISSING")

    def test_external_runtime_assets_are_required_and_fail_closed(self):
        manifest = {
            "runtime_model_assets": {
                "status": "EXTERNAL_REQUIRED",
                "distribution": "BYO_OR_OWNER_SUPPLIED",
                "auto_download": False,
                "fallback_computation": False,
                "owner_manifest": "OWNER_RUNTIME_ASSET_MANIFEST.json",
                "owner_manifest_schema": "solve-lite.owner-runtime-assets.v1",
                "total_files": 1,
                "total_bytes": 2,
                "tree_sha256": "abc",
                "required_directories": [
                    {
                        "relative_path": "model-cache/example",
                        "files": 1,
                        "bytes": 2,
                        "tree_sha256": "def",
                    }
                ],
            }
        }
        with tempfile.TemporaryDirectory() as temporary:
            actual = solve_lite_abi._verify_runtime_assets(Path(temporary), manifest)
        self.assertEqual(actual["status"], "BLOCKED")
        self.assertEqual(actual["error"], "CORE_ASSET_UNAVAILABLE")
        self.assertEqual(actual["reason"], "RUNTIME_MODEL_ASSET_MANIFEST_MISSING")

    def test_external_runtime_asset_manifest_and_directories_are_accepted(self):
        required = [
            {
                "relative_path": "model-cache/example",
                "files": 1,
                "bytes": 2,
                "tree_sha256": "def",
            }
        ]
        contract = {
            "status": "EXTERNAL_REQUIRED",
            "distribution": "BYO_OR_OWNER_SUPPLIED",
            "auto_download": False,
            "fallback_computation": False,
            "owner_manifest": "OWNER_RUNTIME_ASSET_MANIFEST.json",
            "owner_manifest_schema": "solve-lite.owner-runtime-assets.v1",
            "total_files": 1,
            "total_bytes": 2,
            "tree_sha256": "abc",
            "required_directories": required,
        }
        owner = {
            "schema": "solve-lite.owner-runtime-assets.v1",
            "total_files": 1,
            "total_bytes": 2,
            "tree_sha256": "abc",
            "required_directories": required,
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "model-cache" / "example").mkdir(parents=True)
            (root / "OWNER_RUNTIME_ASSET_MANIFEST.json").write_text(
                json.dumps(owner), encoding="utf-8"
            )
            self.assertIsNone(
                solve_lite_abi._verify_runtime_assets(root, {"runtime_model_assets": contract})
            )

    def test_loader_accepts_only_manifest_declared_route_session_capability(self):
        manifest = {
            "artifacts": [{"name": "unused", "sha256": "0", "bytes": 0}],
            "public_abi": {
                "status": "AVAILABLE",
                "module": "solve_lite.abi",
                "public_entry": "route_prompt",
                "core_native_entry": "route_session",
                "healthcheck": "healthcheck",
            },
        }
        with tempfile.TemporaryDirectory() as temporary:
            module_path = Path(temporary) / "solve_lite" / "abi.py"
            module_path.parent.mkdir()
            module_path.write_text("# test module path\n", encoding="utf-8")
            core = SimpleNamespace(
                __file__=str(module_path),
                route_session=lambda *args, **kwargs: {},
                healthcheck=lambda: {"status": "PASS"},
            )
            with (
                patch.object(solve_lite_abi, "_manifest", return_value=manifest),
                patch.object(solve_lite_abi, "_verify", return_value=None),
                patch.object(solve_lite_abi, "_verify_runtime_assets", return_value=None),
                patch.object(solve_lite_abi.importlib, "import_module", return_value=core),
            ):
                self.assertIs(solve_lite_abi.load_core(temporary), core)

    def test_route_prompt_is_a_lossless_route_session_name_bridge(self):
        captured = {}
        result = {
            "status": "PASS",
            "decision": "keep",
            "probabilities": {"keep": 0.75, "drop": 0.25},
            "presentation_locale": "zh-CN",
            "reward": {"delta": 5, "ledger_total": 10},
        }

        class FrozenCore:
            def route_session(self, workspace, case, session, **kwargs):
                captured.update(
                    workspace=workspace,
                    case=case,
                    session=session,
                    kwargs=kwargs,
                )
                return result

        case = {"case_id": "parity", "family": "choice"}
        session = {"locale": "zh-CN"}
        root = Path("/verified/core-asset")
        with (
            patch.object(solve_lite_abi, "locate_core", return_value=root),
            patch.object(solve_lite_abi, "load_core", return_value=FrozenCore()),
        ):
            actual = solve_lite_abi.route_prompt(
                "workspace",
                case,
                session,
                asset_root="configured-root",
                namespace="parity",
                invocation_id="invoke-1",
            )
        self.assertIs(actual, result)
        self.assertEqual(captured["workspace"], "workspace")
        self.assertIs(captured["case"], case)
        self.assertIs(captured["session"], session)
        self.assertEqual(
            captured["kwargs"],
            {
                "asset_root": root,
                "namespace": "parity",
                "invocation_id": "invoke-1",
            },
        )

    def test_route_prompt_preserves_core_error_semantics(self):
        class FrozenCore:
            def route_session(self, *args, **kwargs):
                raise ValueError("frozen-core-error")

        with (
            patch.object(solve_lite_abi, "locate_core", return_value=Path("/verified/core-asset")),
            patch.object(solve_lite_abi, "load_core", return_value=FrozenCore()),
        ):
            with self.assertRaisesRegex(ValueError, "frozen-core-error"):
                solve_lite_abi.route_prompt("workspace", {}, None)

    def test_loader_contains_no_decision_math_or_network_dependency(self):
        source = Path(solve_lite_abi.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        imports = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imports.update(
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        )
        self.assertFalse(imports.intersection({"math", "numpy", "scipy", "requests", "urllib"}))
        function_names = {
            node.name.lower()
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        self.assertFalse(function_names.intersection({"decide", "score", "calibrate", "threshold"}))


if __name__ == "__main__":
    unittest.main()
