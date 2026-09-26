#!/usr/bin/env python3
from __future__ import annotations

import ast
import json
import tempfile
import unittest
from pathlib import Path

import agent_auto


class AgentAutoTest(unittest.TestCase):
    def setUp(self):
        self.modes, self.hosts = agent_auto.load_registry()
        self.by_id = {host.host_id: host for host in self.hosts}

    def test_registry_schema_and_truth(self):
        self.assertEqual(self.modes, agent_auto.SUPPORTED_MODES)
        self.assertEqual(len(self.hosts), 7)
        self.assertEqual([host.priority for host in self.hosts], sorted(host.priority for host in self.hosts))
        self.assertEqual(len({host.priority for host in self.hosts}), 7)
        self.assertTrue(all(
            host.cold_fork_status == "BLOCKED_PENDING_CLEAN_HOST_AND_PUBLIC_CORE_ASSET"
            for host in self.hosts
        ))
        self.assertEqual(self.by_id["hermes"].compatibility_status, "PASS_ACCEPTED")
        self.assertEqual(self.by_id["doubao"].compatibility_status, "UNSUPPORTED")
        self.assertEqual(self.by_id["cursor"].compatibility_status, "NOT_RUN")

    def test_deterministic_supported_mode_priority(self):
        selected = agent_auto.detect({
            "host_id": "qwen-code",
            "environment": {"CODEX_HOME": "present"},
            "executables": ["hermes"],
        })
        self.assertEqual(selected.host_id, "qwen")
        self.assertEqual(agent_auto.detect({"executables": ["/opt/bin/codex"]}).host_id, "codex")
        self.assertEqual(agent_auto.detect({"filesystem_markers": [".workbuddy-ai"]}).host_id, "workbuddy")

    def test_unknown_and_ambiguous_fail_closed(self):
        with self.assertRaises(agent_auto.UnknownHostError):
            agent_auto.detect({"host_id": "unknown-host"})
        with self.assertRaises(agent_auto.UnknownHostError):
            agent_auto.detect({})
        with self.assertRaises(agent_auto.AmbiguousHostError):
            agent_auto.detect({"environment": {"CODEX_HOME": "x", "HERMES_HOME": "y"}})

    def test_path_escape_fail_closed(self):
        with self.assertRaises(agent_auto.UnsafePathError):
            agent_auto.detect({"filesystem_markers": ["../.codex"]})
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            (source / "SKILL.md").write_text("# test\n", encoding="utf-8")
            with self.assertRaises(agent_auto.UnsafePathError):
                agent_auto.plan_skill_install(
                    self.by_id["codex"], source, root / "target", "../escape", root / "backup"
                )

    def test_mcp_translation_is_data_only(self):
        source = {
            "$schema": "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json",
            "mcpServers": {
                "solve_lite_local": {
                    "type": "stdio",
                    "command": "/usr/bin/python3",
                    "args": ["server/solve_lite_mcp.py"],
                    "cwd": ".",
                    "env_vars": ["SOLVE_LITE_WORKSPACE"],
                }
            },
        }
        translated = agent_auto.translate_mcp_config(self.by_id["codex"], source)
        server = translated["mcpServers"]["solve_lite_local"]
        self.assertEqual(server["cwd"], "${PLUGIN_ROOT}")
        self.assertEqual(server["command"], "/usr/bin/python3")
        self.assertEqual(source["mcpServers"]["solve_lite_local"]["cwd"], ".")
        with self.assertRaises(agent_auto.UnsafePathError):
            agent_auto.translate_mcp_config(self.by_id["codex"], {
                "mcpServers": {"bad": {"command": "python3", "args": ["../escape.py"]}}
            })
        with self.assertRaises(agent_auto.AgentAutoError):
            agent_auto.translate_mcp_config(self.by_id["hermes"], source)

    def test_skill_install_verify_and_rollback_are_dry_run(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            destination_root = root / "destination"
            backup_root = root / "backup"
            source.mkdir()
            (source / "SKILL.md").write_text("# test\n", encoding="utf-8")
            (source / "asset.txt").write_text("stable\n", encoding="utf-8")
            plan = agent_auto.plan_skill_install(
                self.by_id["codex"], source, destination_root, "solve-lite", backup_root
            )
            self.assertEqual(agent_auto.install(plan)["status"], "DRY_RUN")
            self.assertEqual(agent_auto.verify(plan)["status"], "NOT_INSTALLED")
            self.assertEqual(agent_auto.rollback(plan)["status"], "DRY_RUN")
            self.assertFalse(Path(plan.destination).exists())
            self.assertFalse(Path(plan.backup).exists())
            with self.assertRaises(agent_auto.ApplyNotAuthorizedError):
                agent_auto.install(plan, apply=True)

    def test_public_abi_request_response_parity(self):
        calls = []
        response = {"status": "PASS", "opaque": [1, 2, 3]}

        def recorder(workspace, case, session, **kwargs):
            calls.append((workspace, case, session, kwargs))
            return response

        original = agent_auto._route_prompt
        agent_auto._route_prompt = recorder
        try:
            request = {
                "workspace": "workspace",
                "case": {"kind": "bool", "question": "bounded"},
                "session": {"locale": "en-US"},
                "asset_root": "assets",
                "namespace": "test",
                "invocation_id": "invocation",
            }
            actual = agent_auto.invoke({"host_id": "codex"}, request)
        finally:
            agent_auto._route_prompt = original
        self.assertIs(actual, response)
        self.assertEqual(calls, [(
            "workspace",
            request["case"],
            request["session"],
            {"asset_root": "assets", "namespace": "test", "invocation_id": "invocation"},
        )])

    def test_no_decision_math_or_private_imports(self):
        source_path = Path(agent_auto.__file__)
        source = source_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module)
            elif isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
        self.assertEqual(imports.intersection({"solve_lite_abi"}), {"solve_lite_abi"})
        self.assertFalse(any(name.startswith("solve_lite.") for name in imports))
        function_names = {
            node.name.lower() for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        self.assertFalse(function_names.intersection({"decide", "score", "calibrate", "threshold"}))
        self.assertNotIn("/" + "Users" + "/", source)
        self.assertNotIn("PRIVATE" + "_AUDIT_DO_NOT_PUBLISH", source)

    def test_registry_has_no_absolute_or_private_paths(self):
        text = agent_auto.REGISTRY_PATH.read_text(encoding="utf-8")
        payload = json.loads(text)
        self.assertEqual(
            payload["cold_fork_test"],
            "BLOCKED_PENDING_CLEAN_HOST_AND_PUBLIC_CORE_ASSET",
        )
        self.assertNotIn("/" + "Users" + "/", text)
        self.assertNotIn("PRIVATE" + "_AUDIT_DO_NOT_PUBLISH", text)


if __name__ == "__main__":
    unittest.main()
