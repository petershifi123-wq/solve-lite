import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
HOOK_PATH = ROOT / "plugins/solve-lite/hooks/user_prompt_submit.py"
SPEC = importlib.util.spec_from_file_location("solve_lite_user_prompt_submit", HOOK_PATH)
HOOK = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(HOOK)


class HookAuditRegressionTest(unittest.TestCase):
    def test_frozen_scenario_catalog_has_exactly_twenty_routes(self):
        seen = set()
        for prompt in (
            "关系聊天", "消息意图", "客户支持工单", "销售询价", "邮件收件箱",
            "下一步动作", "继续重试", "完成验收", "输出检查", "RAG 检索相关",
            "事实核查", "内容风险审核", "退款运营", "数据质量字段", "产品内容路由",
            "工具权限", "模型路由", "任务分派", "轨迹追踪", "安全事件分诊",
        ):
            scene = HOOK._route_scene(prompt)
            self.assertEqual(scene["catalog_size"], 20)
            seen.add(scene["scenario_id"])
        self.assertEqual(len(seen), 20)

    def test_unmatched_chat_still_routes_to_default_scenario(self):
        scene = HOOK._route_scene("今天适合跳舞吗")
        self.assertEqual(scene["scenario_id"], "MESSAGE_INTENT")
        self.assertTrue(scene["fallback"])

    def test_portable_cli_accepts_exact_text(self):
        payload = HOOK._cli_payload(["--text", "汉堡还是薯条"])
        self.assertEqual(payload["prompt"], "汉堡还是薯条")
        self.assertEqual(payload["session_id"], "portable-session")

    def test_every_non_empty_dialog_requires_local_classification(self):
        prompts = (
            "今天适合跳舞吗",
            "你好",
            "帮我看看这句话",
            "汉堡和薯条哪个好吃",
            "写一段摘要",
            "解释这段代码",
            "这个消息什么意思",
            "客户为什么生气",
            "下一步做什么",
            "任务完成了吗",
            "这条证据相关吗",
            "这个说法真实吗",
            "内容安全吗",
            "应该退款吗",
            "数据有没有问题",
            "这篇内容放哪里",
            "可以调用工具吗",
            "用哪个模型",
            "任务交给谁",
            "这个安全事件严重吗",
        )
        self.assertEqual(len(prompts), 20)
        self.assertTrue(all(HOOK._needs_specialist(prompt) for prompt in prompts))

    def test_empty_prompt_is_not_classified(self):
        self.assertFalse(HOOK._needs_specialist("  "))

    def test_nonordinary_events_are_silent_and_never_reach_runtime(self):
        excluded = (
            {"prompt": "", "role": "user"},
            {"prompt": "system text", "role": "system"},
            {"prompt": "assistant text", "role": "assistant"},
            {"prompt": "tool result", "role": "tool"},
            {"prompt": "retry", "role": "user", "is_retry": True},
            {"prompt": "replay", "role": "user", "internal_replay": "true"},
        )
        for payload in excluded:
            with self.subTest(payload=payload), \
                    mock.patch.object(HOOK, "_load_abi") as load_abi, \
                    mock.patch.object(HOOK, "_note"):
                result = HOOK.route_hook(payload)
                self.assertEqual(result, {"continue": True, "suppressOutput": True})
                load_abi.assert_not_called()

    def test_ordinary_user_message_is_not_excluded(self):
        self.assertIsNone(HOOK._ordinary_exclusion_reason({"prompt": "hello", "role": "user"}))

    def test_raw_support_priority(self):
        rendered, status = HOOK._visible_distribution(
            {
                "support_labels": ["entailment", "neutral"],
                "raw_support": [0.75, 0.25],
                "support_semantics": "frozen_relative_support",
                "probabilities": {"entailment": 0.1, "neutral": 0.9},
            },
            {},
        )
        self.assertEqual(status, "RAW_SUPPORT_PRIORITY")
        self.assertEqual(
            rendered,
            "entailment 75.0% · neutral 25.0%（口径: frozen_relative_support）",
        )

    def test_probability_fallback(self):
        rendered, status = HOOK._visible_distribution(
            {
                "support_labels": ["entailment", "neutral"],
                "probabilities": {"entailment": 0.2, "neutral": 0.8},
            },
            {},
        )
        self.assertEqual(status, "PROBABILITY_FALLBACK")
        self.assertEqual(
            rendered,
            "entailment 20.0% · neutral 80.0%（口径: calibrated_probability）",
        )

    def test_invalid_probability_fails_closed(self):
        for answer in (
            {"support_labels": ["a", "b"], "probabilities": {"a": 1.0}},
            {"support_labels": ["a", "b"], "probabilities": {"a": float("nan"), "b": 0.5}},
            {"support_labels": ["a", "b"], "probabilities": {"a": float("inf"), "b": 0.0}},
        ):
            with self.subTest(answer=answer):
                self.assertEqual(
                    HOOK._visible_distribution(answer, {}),
                    ("", "PRESENTATION_DATA_UNAVAILABLE"),
                )

    def test_visible_reward_preserves_valid_result_summary(self):
        result = {
            "reward": {
                "score": {"earned": 7},
                "timing": {"solve_local_elapsed_ms": 12.5},
            },
            "reward_cumulative": {"cumulative_score": 41},
            "reward_summary": "canonical reward summary",
        }
        self.assertEqual(HOOK._visible_reward(result, "en-US"), "canonical reward summary")

    def test_visible_reward_missing_reward_uses_overview_total_without_earned(self):
        overview = {"cumulative": {"cumulative_score": 41}, "summary": "stale +7 earned"}
        reward_module = mock.Mock()
        reward_module.reward_overview.return_value = overview
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(HOOK, "_workspace", return_value=Path(tmp)), \
                mock.patch.dict("sys.modules", {"solve_lite": mock.Mock(reward=reward_module)}):
            rendered = HOOK._visible_reward({}, "en-US")
        self.assertEqual(rendered, "🎁 Local reward pool | Total 41 Score · 🔒 Local")
        self.assertNotIn("+7", rendered)

    def test_visible_reward_storage_failure_fails_open(self):
        reward_module = mock.Mock()
        reward_module.reward_overview.side_effect = OSError("storage unavailable")
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(HOOK, "_workspace", return_value=Path(tmp)), \
                mock.patch.dict("sys.modules", {"solve_lite": mock.Mock(reward=reward_module)}):
            self.assertEqual(HOOK._visible_reward({}, "zh-CN"), "REWARD_DISPLAY_UNAVAILABLE")

    def test_compact_answer_is_attached_to_reward_ledger_once(self):
        reward_module = mock.Mock()
        reward_module.attach_reward.return_value = {"status": "PASS", "reward": {"score": {"earned": 5}}}
        result = {"status": "PASS", "answers": {"q_route": {"value": "neutral"}}}
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.dict("sys.modules", {"solve_lite": mock.Mock(reward=reward_module)}):
            rendered = HOOK._attach_reward_if_missing(
                result,
                workspace=Path(tmp),
                namespace="production",
                locale="zh-CN",
                invocation_id="host:test:turn",
                elapsed_ns=123,
            )
        self.assertIn("reward", rendered)
        reward_module.attach_reward.assert_called_once()

    def test_same_invocation_id_creates_no_duplicate_reward_event(self):
        runtime = ROOT / "plugins/solve-lite/skills/solve-lite/runtime"
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(
            sys, "path", [str(runtime)] + list(sys.path)
        ):
            from solve_lite import reward as reward_module

            workspace = Path(tmp)
            for _ in range(2):
                result = {"status": "PASS", "answers": {"q_route": {"value": "neutral"}}}
                attached = HOOK._attach_reward_if_missing(
                    result,
                    workspace=workspace,
                    namespace="retry-idempotency",
                    locale="en-US",
                    invocation_id="host:session:stable-turn",
                    elapsed_ns=123,
                )
            self.assertEqual(reward_module.reward_stats(workspace, "retry-idempotency")["events"], 1)
            self.assertEqual(attached["reward_transaction"]["reward_status"], "DUPLICATE")

    def test_failure_path_still_requires_visible_percentage_status_and_pool(self):
        with mock.patch.object(HOOK, "_visible_reward", return_value="🎁 本地奖励池 | 累计 10 分 · 🔒 本地"), \
                mock.patch.object(HOOK, "_note"):
            result = HOOK._passthrough("CORE_ASSET_UNAVAILABLE", {"prompt": "你好"})
        context = result["hookSpecificOutput"]["additionalContext"]
        self.assertIn("百分比 | PRESENTATION_DATA_UNAVAILABLE", context)
        self.assertIn("🎁 本地奖励池", context)

    def test_missing_optional_trace_id_is_recorded_without_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            result = {"status": "PASS", "invocation_id": "test:missing-trace"}
            HOOK._append_audit(workspace, result, "session-1", {"status": "NO_PACK_STEP_IN_TRACE"})
            record = json.loads((workspace / "host-invocations.jsonl").read_text())
            self.assertIsNone(record["trace_id"])
            self.assertIn("trace_id", record["audit_missing_fields"])
            self.assertEqual(record["status"], "PASS")
            self.assertEqual(record["invocation_id"], "test:missing-trace")

    def test_audit_write_failure_fails_open(self):
        with tempfile.TemporaryDirectory() as tmp:
            not_a_directory = Path(tmp) / "blocked"
            not_a_directory.write_text("file", encoding="utf-8")
            with mock.patch.object(HOOK, "_note") as note:
                HOOK._append_audit(
                    not_a_directory,
                    {"status": "PASS", "invocation_id": "test:write-failure"},
                    "session-2",
                    {"status": "NO_PACK_STEP_IN_TRACE"},
                )
            note.assert_called_once_with("AUDIT_WRITE_DEGRADED", {"session_id": "session-2"})


if __name__ == "__main__":
    unittest.main()
