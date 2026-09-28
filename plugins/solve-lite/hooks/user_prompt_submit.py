#!/usr/bin/env python3
"""Codex Desktop UserPromptSubmit bridge for the frozen Solve Lite ABI."""

from __future__ import annotations

import hashlib
import argparse
import json
import math
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any


def _plugin_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _config() -> dict[str, Any]:
    """Optional host config: a fresh install runs on the bundled LITE runtime.

    A missing, unreadable or asset_root-less config file is NOT an error - the
    loader finds the bundled runtime by itself.
    """
    value: dict[str, Any] = {}
    root = _plugin_root()
    for path in (root / ".codex-runtime.json", root / ".solve-lite-runtime.json"):
        if not path.is_file():
            continue
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            loaded = {}
        if isinstance(loaded, dict):
            value.update(loaded)
    asset_root = value.get("asset_root")
    if not isinstance(asset_root, str) or not asset_root.strip():
        asset_root = None
    return {
        "asset_root": asset_root,
        "runtime_root": str(value.get("runtime_root") or "").strip() or None,
        "namespace": str(
            os.environ.get("SOLVE_LITE_NAMESPACE")
            or value.get("namespace")
            or "production"
        ),
        "specialist_fallback": str(value.get("specialist_fallback") or "silent"),
    }


def _workspace() -> Path:
    configured = os.environ.get("SOLVE_LITE_WORKSPACE") or os.environ.get("PLUGIN_DATA")
    path = (
        Path(configured).expanduser()
        if configured
        else Path.home() / ".solve-lite" / "state"
    )
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path, 0o700)
    return path


def _load_abi():
    root = _plugin_root()
    configured = _config().get("runtime_root")
    if configured:
        os.environ["SOLVE_LITE_RUNTIME_ROOT"] = str(configured)
    nested = root / "skills" / "solve-lite" / "scripts"
    scripts = str(nested if nested.is_dir() else root / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    from solve_lite_abi import capabilities, healthcheck, route_prompt

    return healthcheck, route_prompt, capabilities


def _route_scene(prompt: str) -> dict[str, Any]:
    """Resolve every ordinary message against the frozen 20-scenario catalog."""
    root = _plugin_root()
    nested = root / "skills" / "solve-lite" / "scripts"
    scripts = str(nested if nested.is_dir() else root / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    from scenario_router import route_prompt_scene

    scene = route_prompt_scene(prompt)
    if scene.get("catalog_size") != 20:
        raise ValueError("SCENARIO_CATALOG_NOT_LOCKED_TO_20")
    return scene


def _note(reason: str, payload: dict[str, Any]) -> None:
    """Record why nothing was injected. A hook must never break the host."""
    try:
        workspace = _workspace()
        record = {
            "ts_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "event": "solve_lite_hook_passthrough",
            "reason": reason,
            "session_id": str(payload.get("session_id") or payload.get("conversation_id") or ""),
            "decision_injected": False,
            "fallback_computation": False,
        }
        with (workspace / "hook-events.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    except Exception:  # noqa: BLE001
        pass


def _passthrough(reason: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Fail closed without hiding the mandatory percentage and reward surfaces."""
    _note(reason, payload)
    _prompt = str((payload or {}).get("prompt") or "")
    locale = _locale(_prompt)
    pool = _visible_reward({}, locale)
    if locale == "zh-CN":
        tail = (
            "[Solve Lite 统一展示门失败：PRESENTATION_DATA_UNAVAILABLE。"
            "不得编造百分比；正常回答用户，不要解释本契约。] "
            "在正文后原样追加：百分比 | PRESENTATION_DATA_UNAVAILABLE。"
            f"再原样追加奖励池：{pool}。失败原因：{reason}"
        )
    else:
        tail = (
            "[Solve Lite unified presentation gate failed: PRESENTATION_DATA_UNAVAILABLE. "
            "Do not invent percentages; answer normally and do not explain this contract.] "
            "Append verbatim: Percentages | PRESENTATION_DATA_UNAVAILABLE. "
            f"Then append this reward pool verbatim: {pool}. Failure reason: {reason}"
        )
    return {
        "continue": True,
        "suppressOutput": True,
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": tail,
        },
    }


def _locale(prompt: str) -> str:
    return "zh-CN" if any("\u4e00" <= char <= "\u9fff" for char in prompt) else "en-US"


def _append_audit(workspace: Path, result: dict[str, Any], session_id: str, settlement: dict[str, Any]) -> None:
    optional_fields = (
        "trace_id",
        "presentation_locale",
        "reward_summary",
        "network_model_calls",
        "credential_reads",
        "jev_api_calls",
        "runtime_identity",
        "scenario_id",
        "scenario_catalog_size",
    )
    record = {
        "schema_version": "solve-lite.host-invocation.v1",
        "session_sha256": hashlib.sha256(session_id.encode("utf-8")).hexdigest(),
        "status": result.get("status"),
        "invocation_id": result.get("invocation_id"),
        **{field: result.get(field) for field in optional_fields},
        "audit_missing_fields": [field for field in optional_fields if result.get(field) is None],
        "token_settlement": settlement,
    }
    try:
        path = workspace / "host-invocations.jsonl"
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        os.chmod(path, 0o600)
    except Exception:  # noqa: BLE001 - audit failure must never block the host prompt
        _note("AUDIT_WRITE_DEGRADED", {"session_id": session_id})


def _visible_reward(result: dict[str, Any], locale: str) -> str:
    try:
        earned = int(result["reward"]["score"]["earned"])
        total = int(result["reward_cumulative"]["cumulative_score"])
        elapsed = float(result["reward"]["timing"]["solve_local_elapsed_ms"])
    except (KeyError, TypeError, ValueError):
        try:
            from solve_lite import reward as reward_mod

            overview = reward_mod.reward_overview(
                _workspace(),
                namespace=str(_config().get("namespace") or "production"),
                locale=locale,
            )
            total = int(overview["cumulative"]["cumulative_score"])
        except Exception:  # noqa: BLE001 - reward display must never block the host prompt
            return "REWARD_DISPLAY_UNAVAILABLE"
        if locale == "zh-CN":
            return f"🎁 本地奖励池 | 累计 {total} 分 · 🔒 本地"
        return f"🎁 Local reward pool | Total {total} Score · 🔒 Local"

    summary = result.get("reward_summary")
    if isinstance(summary, str) and summary:
        return summary
    if locale == "zh-CN":
        return f"⚡ 本地推理 {elapsed:.1f} ms · +{earned} 分 | 累计 {total} · 🔒 本地"
    return f"⚡ Local inference {elapsed:.1f} ms · +{earned} Score | Total {total} · 🔒 Local"


def _attach_reward_if_missing(
    result: dict[str, Any],
    *,
    workspace: Path,
    namespace: str,
    locale: str,
    invocation_id: str,
    elapsed_ns: int,
) -> dict[str, Any]:
    """Settle compact decisions once; the compact router itself is ledger-neutral."""
    if isinstance(result.get("reward"), dict):
        return result
    try:
        from solve_lite import reward as reward_mod

        return reward_mod.attach_reward(
            workspace,
            result,
            operation="ordinary_host_prompt",
            namespace=namespace,
            elapsed_ns=elapsed_ns,
            quality_gate_pass=result.get("status") == "PASS",
            quality_gate_reason=(
                "COMPACT_ROUTE_PASS" if result.get("status") == "PASS" else "ROUTE_FAILED"
            ),
            local_decisions=len(result.get("answers") or {}),
            locale=locale,
            invocation_id=invocation_id,
        )
    except Exception:  # noqa: BLE001 - the visible pool falls back to ledger overview
        return result


def _visible_distribution(answer: dict[str, Any], display_labels: dict[str, str]) -> tuple[str, str]:
    support_labels = answer.get("support_labels")
    if not isinstance(support_labels, (list, tuple)) or not support_labels:
        return "", "PRESENTATION_DATA_UNAVAILABLE"
    if not all(isinstance(label, str) and label for label in support_labels):
        return "", "PRESENTATION_DATA_UNAVAILABLE"
    support_labels = list(support_labels)
    if len(set(support_labels)) != len(support_labels):
        return "", "PRESENTATION_DATA_UNAVAILABLE"

    def valid_values(value: Any, *, probability: bool) -> list[float] | None:
        if isinstance(value, dict):
            if set(value) != set(support_labels):
                return None
            source = [value[label] for label in support_labels]
        elif isinstance(value, (list, tuple)) and len(value) == len(support_labels):
            source = value
        else:
            return None
        if any(isinstance(item, bool) for item in source):
            return None
        try:
            values = [float(item) for item in source]
        except (TypeError, ValueError):
            return None
        if not all(math.isfinite(item) and 0.0 <= item <= 1.0 for item in values):
            return None
        if probability and not math.isclose(sum(values), 1.0, rel_tol=1e-6, abs_tol=1e-6):
            return None
        return values

    values = valid_values(answer.get("raw_support"), probability=False)
    if values is not None:
        semantics = answer.get("support_semantics")
        semantics = semantics if isinstance(semantics, str) and semantics else "uncalibrated_relative_support"
        status = "RAW_SUPPORT_PRIORITY"
    else:
        values = valid_values(answer.get("probabilities"), probability=True)
        if values is None:
            return "", "PRESENTATION_DATA_UNAVAILABLE"
        semantics = "calibrated_probability"
        status = "PROBABILITY_FALLBACK"

    distribution = " · ".join(
        f"{display_labels.get(label, label)} {value * 100:.1f}%"
        for label, value in zip(support_labels, values)
    )
    return f"{distribution}（口径: {semantics}）", status


TOKEN_SETTLEMENT_SCHEMA = "solve-lite.token-settlement.v1"
# Wording for the measured-zero case required by the token-truth gate.  The branch
# is chosen from measured data, never assumed: `_token_settlement` only reaches it
# when this trace carried no packing receipt, and the numbers it renders are the
# measured zeros of that trace.
TOKEN_ZERO_TEXT = {"zh-CN": "Token：0（无可压缩上下文）", "en-US": "Token: 0 (no compressible context)"}
TOKEN_PACK_TEXT = {
    "zh-CN": "Token：输入 {before} · 输出 {after} · 压缩 {delta} · 凭据 {receipt_id}",
    "en-US": "Token: in {before} · out {after} · packed {delta} · receipt {receipt_id}",
}


def _token_settlement(result: dict[str, Any], *, locale: str) -> dict[str, Any]:
    """Token settlement measured from this same trace.

    ``route_prompt`` performs no packing step, so the ordinary path has no packing
    receipt and the settlement is a measured zero - it is not a statement about the
    host context.  When a packing receipt *is* present in the same trace (the pack
    path), the settlement carries the measured input, output and delta token counts
    plus the receipt id a reviewer can look up.  Provider-side savings are never
    derived from local counts and stay ``NOT_MEASURED``.
    """
    pack = result.get("pack") if isinstance(result.get("pack"), dict) else {}
    receipt = pack.get("receipt") if isinstance(pack.get("receipt"), dict) else {}
    counts = receipt.get("counts") if isinstance(receipt.get("counts"), dict) else {}
    delta = counts.get("content_delta")
    measured = delta is not None and receipt.get("event_id")
    status = "MEASURED_PACK" if measured else "NO_PACK_STEP_IN_TRACE"
    return {
        "schema_version": TOKEN_SETTLEMENT_SCHEMA,
        "status": status,
        "measurement_source": "same_trace_packing" if measured else "same_trace_route_only",
        "reason": None if measured else "NO_COMPRESSIBLE_CONTEXT",
        "tokenizer_id": counts.get("tokenizer_id"),
        "input_tokens": counts.get("before") if measured else 0,
        "output_tokens": counts.get("after") if measured else 0,
        "delta_tokens": int(delta) if measured else 0,
        "receipt_id": receipt.get("event_id") if measured else None,
        "pack_status": pack.get("status"),
        "trace_id": result.get("trace_id"),
        "provider_savings": None,
        "provider_savings_status": "NOT_MEASURED",
        "locale": locale,
    }


def render_token_line(settlement: dict[str, Any]) -> str:
    """Render one measured token settlement; never invents a status."""
    locale = settlement.get("locale") if settlement.get("locale") in TOKEN_ZERO_TEXT else "zh-CN"
    if settlement.get("status") != "MEASURED_PACK":
        return TOKEN_ZERO_TEXT[locale]
    return TOKEN_PACK_TEXT[locale].format(
        before=settlement["input_tokens"],
        after=settlement["output_tokens"],
        delta=settlement["delta_tokens"],
        receipt_id=settlement["receipt_id"],
    )


# --- universal router -----------------------------------------------------------
# Owner ruling: every non-empty ordinary host message enters the shared local
# classifier.  Adapters may not silently downgrade a conversation to a footer-less
# quick path.  The legacy keyword constants remain only for source compatibility.
_BOUNDED_ZH = ("选哪个", "该不该", "要不要", "是否", "排序", "打分", "评分", "概率", "哪个更",
               "值得吗", "更划算", "蕴含", "推理", "判断", "评估", "比较一下", "帮我选")
_BOUNDED_EN = ("which ", "should i", "rank", "score", "compare", "probab", "entail",
               "whether", "choose", "is it worth", "better option", "decide")


def _needs_specialist(prompt: str) -> bool:
    return bool((prompt or "").strip())


def _ordinary_exclusion_reason(payload: dict[str, Any]) -> str | None:
    """Return why a hook event is not an ordinary user message.

    UserPromptSubmit is the normal host entrypoint, but portable hosts can feed
    richer envelopes into the same adapter.  The public contract excludes
    system/assistant/tool/internal traffic and host retries so the hook cannot
    reward its own output or replay a settled turn.
    """
    prompt = str((payload or {}).get("prompt") or "")
    if not _needs_specialist(prompt):
        return "EMPTY_OR_WHITESPACE_MESSAGE"

    role = str(
        (payload or {}).get("role")
        or (payload or {}).get("message_role")
        or "user"
    ).strip().lower()
    if role not in {"user", "human"}:
        return "NON_USER_MESSAGE"

    for name in ("is_retry", "retry", "internal_replay", "is_internal", "hook_internal"):
        value = (payload or {}).get(name)
        if value is True or (isinstance(value, str) and value.strip().lower() in {"1", "true", "yes"}):
            return "RETRY_OR_INTERNAL_REPLAY"

    event_type = str((payload or {}).get("event_type") or "").strip().lower()
    if event_type in {"assistant", "system", "tool", "tool_event", "hook_internal", "internal_replay"}:
        return "INTERNAL_EVENT"
    return None


def _silent_continue(reason: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Pass excluded traffic through without percentages or reward settlement."""
    _note(reason, payload)
    return {"continue": True, "suppressOutput": True}


def route_hook(payload: dict[str, Any]) -> dict[str, Any]:
    exclusion = _ordinary_exclusion_reason(payload)
    if exclusion:
        return _silent_continue(exclusion, payload)

    config = _config()
    healthcheck, route_prompt, _capabilities = _load_abi()
    health = healthcheck(config["asset_root"])
    if health.get("status") != "PASS":
        return _passthrough(str(health.get("error") or "CORE_ASSET_UNAVAILABLE"), payload)

    prompt = str(payload.get("prompt") or "")
    session_id = str(payload.get("session_id") or payload.get("conversation_id") or "ordinary-session")
    turn_id = str(
        payload.get("turn_id")
        or payload.get("message_id")
        or payload.get("request_id")
        or uuid.uuid4().hex
    )
    locale = _locale(prompt)
    try:
        scene = _route_scene(prompt)
    except Exception:  # noqa: BLE001 - catalog failure must be explicit, never guessed
        return _passthrough("SCENARIO_CATALOG_UNAVAILABLE", payload)
    scenario_id = str(scene["scenario_id"])
    scenario_name = str(scene["display_name_zh"])
    case = {
        "case_id": f"host_scene_{scenario_id.lower()}_{turn_id}",
        "family": "natural_language_inference",
        "state": {
            "items": [
                {
                    "id": "item_0",
                    "difficulty_tier": "easy",
                    "premise": prompt,
                    "hypothesis": (
                        "The ordinary host message belongs to the "
                        f"{scenario_id} scenario ({scenario_name})."
                    ),
                }
            ]
        },
        "questions": {
            "q_route": {
                "type": "choice",
                "input_ref": "item_0",
                "criteria": {
                    "contradiction": f"The message does not belong to {scenario_id}.",
                    "entailment": f"The message belongs to {scenario_id}.",
                    "neutral": f"Membership in {scenario_id} is ambiguous.",
                },
                "instructions": "Classify membership in the selected frozen Solve Lite scenario.",
            }
        },
    }
    workspace = _workspace()
    started_ns = time.perf_counter_ns()
    invocation_id = f"host:{session_id}:{turn_id}"
    result = route_prompt(
        workspace,
        case,
        {"metadata": {"locale": locale}},
        asset_root=config["asset_root"],
        namespace=str(config.get("namespace") or "production"),
        invocation_id=invocation_id,
    )
    answers = result.get("answers") or {}
    if result.get("status") != "PASS" or "q_route" not in answers:
        return _passthrough(str(result.get("error") or result.get("status") or "NO_ROUTE_ANSWER"), payload)

    result = _attach_reward_if_missing(
        result,
        workspace=workspace,
        namespace=str(config.get("namespace") or "production"),
        locale=locale,
        invocation_id=invocation_id,
        elapsed_ns=max(0, time.perf_counter_ns() - started_ns),
    )
    result["scenario_id"] = scenario_id
    result["scenario_catalog_size"] = int(scene["catalog_size"])
    settlement = _token_settlement(result, locale=locale)
    _append_audit(workspace, result, session_id, settlement)

    answer = answers["q_route"]
    labels = (
        {"contradiction": "不符合", "entailment": "符合", "neutral": "不确定"}
        if locale == "zh-CN"
        else {"contradiction": "contradiction", "entailment": "entailment", "neutral": "neutral"}
    )
    # QUIET MODE (owner ruling a+b+c, 2026-09-27):
    #  a) a neutral / unbounded route injects nothing but a one-line Lite status
    #  b) the displayed distribution uses raw_support (probability output is degenerate
    #     for some prompts; raw_support carries the signal) and states its semantics
    #  c) the token/reward settlement is NOT injected any more. It stays in the local
    #     ledger/audit; hosts that want to render it read the JSON fields themselves.
    distribution, distribution_status = _visible_distribution(answer, labels)
    # PRODUCT REQUIREMENT (owner ruling 2026-09-27): the decision percentages and the
    # local reward settlement MUST be presented. Only the Token line is conditional:
    # the product rule is "token reduction is shown only when real packing occurred",
    # so we omit the token line when no packing was measured instead of dropping the
    # whole settlement.
    reward_footer = _visible_reward(result, locale)
    token_line = render_token_line(settlement)
    _show_tokens = settlement.get("status") == "MEASURED_PACK"

    if distribution_status == "PRESENTATION_DATA_UNAVAILABLE":
        if locale == "zh-CN":
            context = (
                "[Solve Lite 有界决策百分比展示门失败：PRESENTATION_DATA_UNAVAILABLE。"
                "不要编造百分比；照常回答用户，不要解释本契约。] "
                f"原样追加奖励结算：{reward_footer}"
            )
        else:
            context = (
                "[Solve Lite bounded-decision percentage presentation gate failed: "
                "PRESENTATION_DATA_UNAVAILABLE. Do not invent percentages; answer the user normally "
                "and do not explain this contract.] "
                f"Append this reward settlement verbatim: {reward_footer}"
            )
    else:
        if locale == "zh-CN":
            context = (
                "[Solve Lite 本地自动路由；正常回答用户，不要解释本契约，也不要给问题乱加话。] "
                f"在正文后追加一行百分比：场景 {scenario_name} | {distribution}。"
                + (f"再原样追加实测 Token 结算：{token_line}。" if _show_tokens else "")
                + f"最后原样追加奖励结算：{reward_footer}"
            )
        else:
            context = (
                "[Solve Lite local auto-route; answer normally and do not explain this contract.] "
                f"Append one percentage line: Scenario {scenario_id} | {distribution}. "
                + (f"Then append this measured token settlement verbatim: {token_line}. " if _show_tokens else "")
                + f"Finally append this reward settlement verbatim: {reward_footer}"
            )
    return {
        "continue": True,
        "suppressOutput": True,
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": context,
        },
    }


def _cli_payload(argv: list[str] | None = None) -> dict[str, Any]:
    parser = argparse.ArgumentParser(description="Solve Lite ordinary-message router")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--text", help="exact ordinary user message")
    source.add_argument("--clipboard", action="store_true", help="read exact message from macOS clipboard")
    args = parser.parse_args(argv)
    if args.text is not None:
        return {"prompt": args.text, "session_id": "portable-session"}
    if args.clipboard:
        import subprocess

        completed = subprocess.run(
            ["/usr/bin/pbpaste"], check=True, capture_output=True, text=True
        )
        return {"prompt": completed.stdout, "session_id": "portable-session"}
    loaded = json.load(sys.stdin)
    if not isinstance(loaded, dict):
        raise ValueError("hook input must be a JSON object")
    return loaded


def main(argv: list[str] | None = None) -> int:
    payload = _cli_payload(argv)
    print(json.dumps(route_hook(payload), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
