import importlib.util
import json
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

    def test_missing_optional_trace_id_is_recorded_without_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            result = {"status": "PASS", "invocation_id": "test:missing-trace"}
            HOOK._append_audit(workspace, result, "session-1", {"status": "NO_PACK_STEP_IN_TRACE"})
            record = json.loads((workspace / "codex-desktop-invocations.jsonl").read_text())
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
