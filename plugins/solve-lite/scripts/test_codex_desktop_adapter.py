#!/usr/bin/env python3
"""Offline self-check for the Codex Desktop adapter's ordinary-session gate.

    /usr/bin/python3 scripts/test_codex_desktop_adapter.py

No network, no Codex calls, no production state: the checks run against temporary
ledgers, baselines and session rollouts. The load-bearing rule under test is that
the *hook's injected developer context* is never mistaken for the user-visible
assistant answer.
"""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "codex_desktop_adapter", Path(__file__).resolve().with_name("codex_desktop_adapter.py")
)
ADAPTER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ADAPTER)

VISIBLE_ANSWER = (
    "热狗通常被视作单独一类食物。\n\n"
    "选择 | 不符合 33.3% · 符合 33.3% · 不确定 33.3%  \n"
    "Token：0（无可压缩上下文）  \n"
    "⚡ 本地推理 8303.0 ms · +5 分 | 累计 5 · 🔒 本地"
)
INJECTED_CONTRACT = (
    "[Solve Lite 本地自动路由…] 选择 | 不符合 33.3% · 符合 33.3% · 不确定 33.3%。"
    "Token：0（无可压缩上下文）⚡ 本地推理 1.0 ms · +5 分 | 累计 5"
)
RETIRED_STATIC_TOKEN_LINE = (
    "选择 | 不符合 33.3% · 符合 33.3% · 不确定 33.3%  \n"
    "Token：本轮未触发压缩。  \n"
    "⚡ 本地推理 12.0 ms · +5 分 | 累计 5"
)


def write_rollout(root: Path, session_id: str, originator: str, roles: list[tuple[str, str]]) -> Path:
    target = root / "2026" / "09" / "26" / f"rollout-2026-09-26T10-00-00-{session_id}.jsonl"
    target.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        json.dumps(
            {
                "type": "session_meta",
                "payload": {"session_id": session_id, "originator": originator, "cwd": "/tmp/demo"},
            }
        ),
        json.dumps(
            {
                "type": "response_item",
                "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "热狗是否属于三明治？"}]},
            }
        ),
    ]
    for role, text in roles:
        lines.append(
            json.dumps(
                {
                    "type": "response_item",
                    "payload": {"type": "message", "role": role, "content": [{"type": "input_text", "text": text}]},
                }
            )
        )
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target


class VisibleObligations(unittest.TestCase):
    def test_full_answer_passes(self) -> None:
        obligations = ADAPTER.visible_obligations(VISIBLE_ANSWER)
        for key in (
            "router_footer",
            "percent_labels_chinese",
            "token_status",
            "reward_delta_plus5",
            "cumulative_reward",
        ):
            self.assertTrue(obligations[key], key)
        self.assertFalse(obligations["percent_labels_english"])
        self.assertEqual(1, obligations["latency_mentions"])
        self.assertEqual(1, obligations["reward_lines"])

    def test_injected_contract_is_textually_complete(self) -> None:
        """Why the rollout role filter is load-bearing: the injected contract passes every text check."""
        obligations = ADAPTER.visible_obligations(INJECTED_CONTRACT)
        self.assertTrue(obligations["percent_labels_chinese"])
        self.assertTrue(obligations["token_status"])
        self.assertTrue(obligations["reward_delta_plus5"])

    def test_english_labels_are_rejected(self) -> None:
        text = "选择 | No 33.3% · Yes 33.3%  \nToken：0（无可压缩上下文）  \n⚡ 本地推理 1 ms · +5 分 | 累计 5"
        self.assertTrue(ADAPTER.visible_obligations(text)["percent_labels_english"])

    def test_retired_static_token_line_is_rejected(self) -> None:
        """The hard-coded token sentence must no longer satisfy the gate."""
        obligations = ADAPTER.visible_obligations(RETIRED_STATIC_TOKEN_LINE)
        self.assertFalse(obligations["token_status_measured"])
        self.assertTrue(obligations["token_status_retired_literal"])

    def test_measured_pack_token_line_is_accepted(self) -> None:
        text = (
            "选择 | 不符合 33.3% · 符合 33.3% · 不确定 33.3%  \n"
            "Token：输入 4200 · 输出 900 · 压缩 3300 · 凭据 evt_0123456789abcdef  \n"
            "⚡ 本地推理 41.0 ms · +5 分 | 累计 5"
        )
        obligations = ADAPTER.visible_obligations(text)
        self.assertTrue(obligations["token_status_measured"])
        self.assertFalse(obligations["token_status_retired_literal"])

    def test_duplicate_footers_are_rejected(self) -> None:
        text = VISIBLE_ANSWER + "\n⚡ 本地推理 1.0 ms · +5 分 | 累计 5"
        obligations = ADAPTER.visible_obligations(text)
        self.assertEqual(2, obligations["latency_mentions"])
        self.assertEqual(2, obligations["reward_lines"])


class RolloutEvidence(unittest.TestCase):
    def test_developer_injection_is_not_visible(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = write_rollout(
                Path(tmp), "01a0dead-0000-0000-0000-000000000001", "Codex Desktop", [("developer", INJECTED_CONTRACT)]
            )
            self.assertEqual("", ADAPTER.rollout_evidence(path)["assistant_message"])

    def test_assistant_message_is_visible(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = write_rollout(
                Path(tmp),
                "01a0dead-0000-0000-0000-000000000002",
                "Codex Desktop",
                [("developer", INJECTED_CONTRACT), ("assistant", VISIBLE_ANSWER)],
            )
            self.assertEqual(VISIBLE_ANSWER, ADAPTER.rollout_evidence(path)["assistant_message"])


class OrdinarySessionGate(unittest.TestCase):
    SESSION_ID = "01a0beef-1111-2222-3333-444444444444"

    def setUp(self) -> None:
        # Keep the check offline: project trust is Codex state, not the subject here.
        self._trusted_project = ADAPTER.trusted_project
        ADAPTER.trusted_project = lambda cwd, config=None: True

    def tearDown(self) -> None:
        ADAPTER.trusted_project = self._trusted_project

    def _fixture(
        self, tmp: str, originator: str, roles: list[tuple[str, str]], extra_records: int = 0
    ) -> tuple[Path, Path, Path]:
        workspace = Path(tmp) / "workspace"
        workspace.mkdir()
        sessions = Path(tmp) / "sessions"
        write_rollout(sessions, self.SESSION_ID, originator, roles)
        ledger = ADAPTER.ledger_path(workspace)
        ledger.write_text(
            json.dumps({"invocation_id": "codex:01a0old0-0000-0000-0000-000000000000:aaaa", "status": "PASS"}) + "\n",
            encoding="utf-8",
        )
        baseline = Path(tmp) / "baseline.json"
        baseline.write_text(json.dumps(ADAPTER.ledger_snapshot(workspace)), encoding="utf-8")
        with ledger.open("a", encoding="utf-8") as handle:
            for index in range(extra_records + 1):
                handle.write(
                    json.dumps(
                        {"invocation_id": f"codex:{self.SESSION_ID}:hash{index}", "status": "PASS", "network_model_calls": 0}
                    )
                    + "\n"
                )
        return workspace, baseline, sessions

    def test_one_ordinary_invocation_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace, baseline, sessions = self._fixture(tmp, "Codex Desktop", [("assistant", VISIBLE_ANSWER)])
            result = ADAPTER.check_ordinary_session(workspace, baseline, sessions)
            self.assertEqual("PASS", result["status"], result.get("detail"))
            self.assertEqual(1, result["new_invocations"])

    def test_baseline_required(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace, _, sessions = self._fixture(tmp, "Codex Desktop", [("assistant", VISIBLE_ANSWER)])
            self.assertEqual("GATE", ADAPTER.check_ordinary_session(workspace, None, sessions)["status"])

    def test_no_advance_is_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace, _, sessions = self._fixture(tmp, "Codex Desktop", [("assistant", VISIBLE_ANSWER)])
            baseline = Path(tmp) / "baseline.json"
            baseline.write_text(json.dumps(ADAPTER.ledger_snapshot(workspace)), encoding="utf-8")
            self.assertEqual("GATE", ADAPTER.check_ordinary_session(workspace, baseline, sessions)["status"])

    def test_duplicate_invocations_fail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace, baseline, sessions = self._fixture(
                tmp, "Codex Desktop", [("assistant", VISIBLE_ANSWER)], extra_records=1
            )
            result = ADAPTER.check_ordinary_session(workspace, baseline, sessions)
            self.assertEqual("FAIL", result["status"])
            self.assertIn("duplicate", result["detail"])

    def test_non_desktop_originator_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace, baseline, sessions = self._fixture(tmp, "codex_exec", [("assistant", VISIBLE_ANSWER)])
            result = ADAPTER.check_ordinary_session(workspace, baseline, sessions)
            self.assertEqual("FAIL", result["status"])
            self.assertIn("originator", result["detail"])

    def test_injected_context_only_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace, baseline, sessions = self._fixture(tmp, "Codex Desktop", [("developer", INJECTED_CONTRACT)])
            result = ADAPTER.check_ordinary_session(workspace, baseline, sessions)
            self.assertEqual("FAIL", result["status"])
            self.assertIn("assistant", result["detail"])

    def test_visible_contract_incomplete_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace, baseline, sessions = self._fixture(tmp, "Codex Desktop", [("assistant", "热狗通常算三明治。")])
            result = ADAPTER.check_ordinary_session(workspace, baseline, sessions)
            self.assertEqual("FAIL", result["status"])
            self.assertIn("visible contract incomplete", result["detail"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
