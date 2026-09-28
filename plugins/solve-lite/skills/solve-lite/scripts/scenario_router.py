"""Deterministic adapter-layer routing over the frozen 20-scenario catalog."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


REGISTRY_PATH = Path(__file__).resolve().parents[1] / "assets" / "scenarios" / "registry.json"
DEFAULT_SCENARIO = "MESSAGE_INTENT"

SCENARIO_SIGNALS: dict[str, tuple[str, ...]] = {
    "CHAT_RELATIONSHIP": ("聊天", "对话", "微信", "关系", "relationship", "chat"),
    "MESSAGE_INTENT": ("消息", "意思", "意图", "message", "intent"),
    "CUSTOMER_SUPPORT": ("工单", "客服", "客户支持", "ticket", "support"),
    "SALES_LEAD": ("销售", "询价", "购买", "lead", "sales"),
    "EMAIL_PRIORITY": ("邮件", "收件箱", "email", "inbox"),
    "AGENT_NEXT_ACTION": ("下一步", "下一动作", "next action"),
    "AGENT_LOOP_CONTROL": ("继续", "重试", "停止", "loop", "retry"),
    "COMPLETION_VERIFIER": ("完成", "验收", "复核", "completion", "verify"),
    "LLM_OUTPUT_GUARD": ("输出检查", "回答审查", "grounded", "output guard"),
    "RAG_RELEVANCE": ("检索", "证据相关", "rag", "relevance"),
    "CLAIM_VERIFICATION": ("真假", "核验", "事实核查", "fact check", "claim"),
    "CONTENT_MODERATION": ("内容风险", "审核", "骚扰", "自伤", "moderation"),
    "OPERATIONS_DECISION": ("退款", "欺诈", "运营", "refund", "fraud"),
    "DOCUMENT_DATA_QUALITY": ("数据质量", "字段", "结构", "document quality", "schema"),
    "PRODUCT_CONTENT_ROUTING": ("内容路由", "产品标签", "content routing", "product tag"),
    "AGENT_TOOL_GUARD": ("工具", "权限", "tool call", "permission"),
    "MODEL_ROUTER": ("模型", "model router", "which model"),
    "TASK_ROUTER": ("任务路由", "分派", "task router", "dispatch"),
    "AGENT_TRACE_OBSERVABILITY": ("轨迹", "追踪", "trace", "observability"),
    "SECURITY_INCIDENT_TRIAGE": ("安全事件", "分诊", "incident", "security"),
}


def load_catalog() -> dict[str, dict[str, Any]]:
    payload = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    scenarios = payload.get("scenarios")
    if not isinstance(scenarios, list) or len(scenarios) != 20:
        raise ValueError("scenario catalog must contain exactly 20 entries")
    catalog = {str(item.get("scenario_id")): item for item in scenarios if isinstance(item, dict)}
    if set(catalog) != set(SCENARIO_SIGNALS):
        raise ValueError("scenario catalog and adapter router differ")
    return catalog


def route_prompt_scene(prompt: str) -> dict[str, Any]:
    catalog = load_catalog()
    text = (prompt or "").casefold()
    ranked = []
    for scenario_id, signals in SCENARIO_SIGNALS.items():
        matches = sorted({signal for signal in signals if signal.casefold() in text})
        if matches:
            ranked.append((len(matches), scenario_id, matches))
    ranked.sort(key=lambda row: (-row[0], row[1]))
    scenario_id = ranked[0][1] if ranked else DEFAULT_SCENARIO
    item = catalog[scenario_id]
    return {
        "scenario_id": scenario_id,
        "display_name_zh": str(item.get("display_name_zh") or scenario_id),
        "matched_signals": ranked[0][2] if ranked else [],
        "catalog_size": len(catalog),
        "fallback": not ranked,
    }


__all__ = ["DEFAULT_SCENARIO", "REGISTRY_PATH", "SCENARIO_SIGNALS", "load_catalog", "route_prompt_scene"]
