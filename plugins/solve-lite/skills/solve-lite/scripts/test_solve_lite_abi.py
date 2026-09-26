#!/usr/bin/env python3
from __future__ import annotations

import ast
import os
import tempfile
import unittest
from pathlib import Path
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
