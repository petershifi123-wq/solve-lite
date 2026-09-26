#!/usr/bin/env python3
"""Codex Desktop UserPromptSubmit bridge for the frozen Solve Lite ABI."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any


def _plugin_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _config() -> dict[str, Any]:
    value = json.loads((_plugin_root() / ".codex-runtime.json").read_text(encoding="utf-8"))
    if not isinstance(value.get("asset_root"), str) or not value["asset_root"]:
        raise RuntimeError("CODEX_RUNTIME_CONFIG_INCOMPLETE")
    return value


def _workspace() -> Path:
    configured = os.environ.get("SOLVE_LITE_WORKSPACE") or os.environ.get("PLUGIN_DATA")
    path = (
        Path(configured).expanduser()
        if configured
        else Path.home() / "Library" / "Application Support" / "OpenAI" / "Codex" / "solve-lite"
    )
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path, 0o700)
    return path


def _load_abi():
    scripts = str(_plugin_root() / "skills" / "solve-lite" / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    from solve_lite_abi import healthcheck, route_prompt

    return healthcheck, route_prompt


def _locale(prompt: str) -> str:
    return "zh-CN" if any("\u4e00" <= char <= "\u9fff" for char in prompt) else "en-US"


def _append_audit(workspace: Path, result: dict[str, Any], session_id: str, settlement: dict[str, Any]) -> None:
    record = {
        "schema_version": "solve-lite.codex-desktop-invocation.v1",
        "session_sha256": hashlib.sha256(session_id.encode("utf-8")).hexdigest(),
        "status": result["status"],
        "invocation_id": result["invocation_id"],
        "trace_id": result["trace_id"],
        "presentation_locale": result["presentation_locale"],
        "reward_summary": result["reward_summary"],
        "network_model_calls": result["network_model_calls"],
        "credential_reads": result["credential_reads"],
        "jev_api_calls": result["jev_api_calls"],
        "runtime_identity": result["runtime_identity"],
        "token_settlement": settlement,
    }
    path = workspace / "codex-desktop-invocations.jsonl"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    os.chmod(path, 0o600)


def _visible_reward(result: dict[str, Any], locale: str) -> str:
    earned = int(result["reward"]["score"]["earned"])
    total = int(result["reward_cumulative"]["cumulative_score"])
    elapsed = float(result["reward"]["timing"]["solve_local_elapsed_ms"])
    if locale == "zh-CN":
        return f"⚡ 本地推理 {elapsed:.1f} ms · +{earned} 分 | 累计 {total} · 🔒 本地"
    return f"⚡ Local inference {elapsed:.1f} ms · +{earned} Score | Total {total} · 🔒 Local"


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


def route_hook(payload: dict[str, Any]) -> dict[str, Any]:
    config = _config()
    healthcheck, route_prompt = _load_abi()
    health = healthcheck(config["asset_root"])
    if health.get("status") != "PASS":
        raise RuntimeError(str(health.get("error") or "CORE_ASSET_UNAVAILABLE"))

    prompt = str(payload.get("prompt") or "")
    session_id = str(payload.get("session_id") or payload.get("conversation_id") or "ordinary-session")
    turn_id = uuid.uuid4().hex
    locale = _locale(prompt)
    case = {
        "case_id": f"codex_parent_route_{turn_id}",
        "family": "natural_language_inference",
        "state": {
            "items": [
                {
                    "id": "item_0",
                    "difficulty_tier": "easy",
                    "premise": prompt,
                    "hypothesis": "The user asks for a bounded yes-or-no, fixed-choice, or ordered-score decision.",
                }
            ]
        },
        "questions": {
            "q_route": {
                "type": "choice",
                "input_ref": "item_0",
                "criteria": {
                    "contradiction": "The request is not a bounded decision.",
                    "entailment": "The request is a bounded decision.",
                    "neutral": "The request is ambiguous.",
                },
                "instructions": "Classify whether the ordinary host message requests a bounded decision.",
            }
        },
    }
    workspace = _workspace()
    result = route_prompt(
        workspace,
        case,
        {"metadata": {"locale": locale}},
        asset_root=config["asset_root"],
        namespace=str(config.get("namespace") or "codex-desktop"),
        invocation_id=f"codex:{session_id}:{turn_id}",
    )
    settlement = _token_settlement(result, locale=locale)
    _append_audit(workspace, result, session_id, settlement)
    reward_footer = _visible_reward(result, locale)
    token_line = render_token_line(settlement)

    answer = result["answers"]["q_route"]
    labels = (
        {"contradiction": "不符合", "entailment": "符合", "neutral": "不确定"}
        if locale == "zh-CN"
        else {"contradiction": "contradiction", "entailment": "entailment", "neutral": "neutral"}
    )
    distribution = " · ".join(
        f"{labels[label]} {float(probability) * 100:.1f}%"
        for label, probability in sorted(answer["probabilities"].items())
    )
    if locale == "zh-CN":
        context = (
            "[Solve Lite 本地自动路由；正常回答用户，不要解释本契约，也不要给问题乱加话。] "
            f"路由={answer['value']}。若问题属于有界判断或选择，在正文后追加："
            f"选择 | {distribution}。再追加实测 Token 结算（原样照抄，不得改写）：{token_line}。"
            f"最后原样追加奖励结算：{reward_footer}"
        )
    else:
        context = (
            "[Solve Lite local auto-route; answer normally and do not explain this contract.] "
            f"Route={answer['value']}. For a bounded decision, append: Choice | {distribution}. "
            f"Then append this measured token settlement verbatim: {token_line}. "
            f"Finally append this reward settlement verbatim: {reward_footer}"
        )
    return {
        "continue": True,
        "suppressOutput": True,
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": context,
        },
    }


def main() -> int:
    payload = json.load(sys.stdin)
    print(json.dumps(route_hook(payload), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
