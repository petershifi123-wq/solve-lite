from __future__ import annotations

import json
import hashlib
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

from .core import TOKENIZER_ID, canonical_json, state_dir, utc_now
from .ledger import paired_usage_delta

SCHEMA_VERSION = "solve.reward.v1"
SCORE_FORMULA = "display-v1: positive verified-or-measured tokens/100 + reduction/5 + decisions*5 + verified avoided calls*5; capped at 100"
PASS_OUTCOMES = {"pass", "passed", "success", "succeeded", "quality_pass", "verified"}


def start_local_timer() -> int:
    """Start a local monotonic timer. Wall time is never used for latency."""
    return time.perf_counter_ns()


def local_elapsed_ns(start_ns: int, end_ns: int | None = None) -> int:
    stop = time.perf_counter_ns() if end_ns is None else int(end_ns)
    return max(0, stop - int(start_ns))


def _source_receipt(result: dict[str, Any]) -> dict[str, Any] | None:
    candidates = (
        result.get("receipt"),
        result.get("context", {}).get("receipt") if isinstance(result.get("context"), dict) else None,
        result.get("pack", {}).get("receipt") if isinstance(result.get("pack"), dict) else None,
    )
    return next((item for item in candidates if isinstance(item, dict)), None)


def _savings(receipt: dict[str, Any] | None) -> dict[str, Any]:
    measured = estimated = verified = None
    context_reduction = None
    verified_status = "NOT_MEASURED"
    if receipt:
        counts = receipt.get("counts") or {}
        delta = counts.get("content_delta")
        quality = counts.get("count_quality")
        bucket = counts.get("bucket")
        if isinstance(delta, int):
            if bucket == "estimate" or quality == "estimated":
                estimated = delta
            elif quality == "exact_for_selected_tokenizer":
                measured = delta
                before = counts.get("before")
                if isinstance(before, int) and before > 0:
                    context_reduction = round(delta * 100.0 / before, 1)
        paired = paired_usage_delta(receipt.get("paired_baseline_usage"), receipt.get("provider_usage"))
        outcome = str(receipt.get("task_outcome") or "").lower()
        provider_verified = all(
            (
                paired is not None,
                bool(receipt.get("baseline_spec_id")),
                bool(receipt.get("verification_source")),
                receipt.get("delivery_status") == "delivered",
                outcome in PASS_OUTCOMES,
            )
        )
        if provider_verified:
            verified = paired
            verified_status = "VERIFIED_PAIRED_PROVIDER_USAGE"
    return {
        "verified_tokens_saved": verified,
        "verified_status": verified_status,
        "measured_content_tokens_saved": measured,
        "measured_tokenizer_id": TOKENIZER_ID if measured is not None else None,
        "estimated_tokens_saved": estimated,
        "context_reduction_percent": context_reduction,
        "provider_refund_or_credit": False,
    }


def _score(
    savings: dict[str, Any],
    *,
    quality_gate_pass: bool,
    local_decisions: int,
    verified_avoided_calls: int | None,
) -> dict[str, Any]:
    if not quality_gate_pass:
        earned, basis = 0, "QUALITY_GATE_FAIL"
    else:
        verified = savings["verified_tokens_saved"]
        measured = savings["measured_content_tokens_saved"]
        if isinstance(verified, int):
            token_basis, basis = verified, "VERIFIED_PAIRED_PROVIDER_USAGE"
        elif isinstance(measured, int):
            token_basis, basis = measured, "MEASURED_LOCAL_CONTENT_DELTA"
        else:
            token_basis, basis = None, "LOCAL_ACTIVITY_ONLY"
        if isinstance(token_basis, int) and token_basis < 0:
            earned, basis = 0, f"{basis}_NEGATIVE"
        else:
            token_points = min(50, max(0, int(token_basis or 0)) // 100)
            reduction = savings.get("context_reduction_percent")
            reduction_points = min(20, int(max(0.0, float(reduction or 0.0)) // 5))
            decision_points = min(20, max(0, int(local_decisions)) * 5)
            avoided_points = min(10, max(0, int(verified_avoided_calls or 0)) * 5)
            earned = min(100, token_points + reduction_points + decision_points + avoided_points)
    return {
        "earned": earned,
        "maximum": 100,
        "basis": basis,
        "formula": SCORE_FORMULA,
        "authority": "DISPLAY_ONLY_NO_DECISION_EFFECT",
    }


def build_reward_event(
    result: dict[str, Any],
    *,
    operation: str,
    namespace: str,
    elapsed_ns: int,
    quality_gate_pass: bool,
    quality_gate_reason: str,
    local_decisions: int = 0,
    host_round_trip_ms: float | None = None,
    host_round_trip_source: str | None = None,
    verified_avoided_calls: int | None = None,
    verified_avoided_calls_source: str | None = None,
    invocation_id: str | None = None,
    trace_id: str | None = None,
    build_id: str | None = None,
) -> dict[str, Any]:
    if elapsed_ns < 0:
        raise ValueError("elapsed_ns must be non-negative")
    if host_round_trip_ms is not None and host_round_trip_ms < 0:
        raise ValueError("host_round_trip_ms must be non-negative")
    if host_round_trip_ms is not None and not host_round_trip_source:
        raise ValueError("measured host_round_trip_ms requires host_round_trip_source")
    if verified_avoided_calls is not None and verified_avoided_calls < 0:
        raise ValueError("verified_avoided_calls must be non-negative")
    if verified_avoided_calls is not None and not verified_avoided_calls_source:
        raise ValueError("verified_avoided_calls requires a verification source")
    receipt = _source_receipt(result)
    savings = _savings(receipt)
    score = _score(
        savings,
        quality_gate_pass=quality_gate_pass,
        local_decisions=local_decisions,
        verified_avoided_calls=verified_avoided_calls,
    )
    event_id = (
        "reward_" + hashlib.sha256(f"{namespace}\0{invocation_id}".encode("utf-8")).hexdigest()[:32]
        if invocation_id
        else f"reward_{uuid.uuid4().hex}"
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "event_id": event_id,
        "invocation_id": invocation_id,
        "trace_id": trace_id,
        "build_id": build_id,
        "timestamp": utc_now(),
        "operation": operation,
        "namespace": namespace,
        "quality_gate": {
            "status": "PASS" if quality_gate_pass else "FAIL",
            "reason": quality_gate_reason,
        },
        "timing": {
            "solve_local_elapsed_ns": int(elapsed_ns),
            "solve_local_elapsed_ms": round(elapsed_ns / 1_000_000.0, 3),
            "local_clock": "time.perf_counter_ns",
            "wall_timestamp_use": "AUDIT_ONLY",
            "host_round_trip_ms": round(float(host_round_trip_ms), 3) if host_round_trip_ms is not None else None,
            "host_round_trip_status": "MEASURED_BY_HOST" if host_round_trip_ms is not None else "NOT_MEASURED",
            "host_round_trip_source": host_round_trip_source,
        },
        "savings": savings,
        "activity": {
            "local_decisions": max(0, int(local_decisions)),
            "verified_avoided_calls": verified_avoided_calls,
            "verified_avoided_calls_status": "VERIFIED" if verified_avoided_calls is not None else "NOT_MEASURED",
            "verified_avoided_calls_source": verified_avoided_calls_source,
        },
        "score": score,
        "source_receipt_event_id": receipt.get("event_id") if receipt else None,
        "note": "Verified provider savings, exact local content delta, and estimates are separate. Score is display-only.",
    }


def _connect(workspace: Path) -> sqlite3.Connection:
    db = sqlite3.connect(state_dir(workspace) / "solve-rewards.sqlite3", timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA busy_timeout=30000")
    for attempt in range(8):
        try:
            db.execute("PRAGMA journal_mode=WAL")
            break
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc).lower() or attempt == 7:
                db.close()
                raise
            time.sleep(0.01 * (attempt + 1))
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS reward_events (
          event_id TEXT PRIMARY KEY,
          namespace TEXT NOT NULL,
          created_at TEXT NOT NULL,
          event_json TEXT NOT NULL
        )
        """
    )
    db.execute(
        "CREATE TABLE IF NOT EXISTS reward_ledger_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )
    db.execute(
        "INSERT OR IGNORE INTO reward_ledger_meta(key, value) VALUES ('ledger_id', ?)",
        (f"ledger_{uuid.uuid4().hex}",),
    )
    db.execute(
        "INSERT OR IGNORE INTO reward_ledger_meta(key, value) VALUES ('ledger_version', '0')"
    )
    db.commit()
    return db


def _record_reward_transaction(workspace: Path, event: dict[str, Any]) -> dict[str, Any]:
    with _connect(workspace) as db:
        db.execute("BEGIN IMMEDIATE")
        cursor = db.execute(
            "INSERT OR IGNORE INTO reward_events(event_id, namespace, created_at, event_json) VALUES (?, ?, ?, ?)",
            (event["event_id"], event["namespace"], event["timestamp"], canonical_json(event)),
        )
        inserted = cursor.rowcount == 1
        if inserted:
            db.execute(
                "UPDATE reward_ledger_meta SET value=CAST(CAST(value AS INTEGER)+1 AS TEXT) WHERE key='ledger_version'"
            )
        rows = dict(db.execute("SELECT key, value FROM reward_ledger_meta").fetchall())
        return {
            "inserted": inserted,
            "ledger_id": rows["ledger_id"],
            "ledger_version": int(rows["ledger_version"]),
        }


def record_reward(workspace: Path, event: dict[str, Any]) -> bool:
    return bool(_record_reward_transaction(workspace, event)["inserted"])


def reward_stats(workspace: Path, namespace: str | None = "production") -> dict[str, Any]:
    with _connect(workspace) as db:
        if namespace is None:
            rows = db.execute("SELECT event_json FROM reward_events ORDER BY created_at, event_id").fetchall()
        else:
            rows = db.execute(
                "SELECT event_json FROM reward_events WHERE namespace=? ORDER BY created_at, event_id",
                (namespace,),
            ).fetchall()
    events = [json.loads(row[0]) for row in rows]
    eligible = [e for e in events if e["quality_gate"]["status"] == "PASS"]
    verified = [e["savings"]["verified_tokens_saved"] for e in eligible if e["savings"]["verified_tokens_saved"] is not None]
    measured = [e["savings"]["measured_content_tokens_saved"] for e in eligible if e["savings"]["measured_content_tokens_saved"] is not None]
    estimated = [e["savings"]["estimated_tokens_saved"] for e in eligible if e["savings"]["estimated_tokens_saved"] is not None]
    all_measured = [e["savings"]["measured_content_tokens_saved"] for e in events if e["savings"]["measured_content_tokens_saved"] is not None]
    avoided = [e["activity"]["verified_avoided_calls"] for e in eligible if e["activity"]["verified_avoided_calls"] is not None]
    verified_status = "NOT_MEASURED" if not verified else ("VERIFIED" if len(verified) == len(eligible) else "PARTIAL")
    avoided_status = "NOT_MEASURED" if not avoided else ("VERIFIED" if len(avoided) == len(eligible) else "PARTIAL")
    return {
        "schema_version": "solve.reward-stats.v1",
        "scope": "workspace-local display-only reward events",
        "namespace": namespace or "all",
        "events": len(events),
        "quality_passed_events": len(eligible),
        "quality_failed_events": len(events) - len(eligible),
        "latest": events[-1] if events else None,
        "cumulative_verified_tokens_saved": sum(verified),
        "cumulative_verified_status": verified_status,
        "cumulative_measured_content_tokens_saved": sum(measured),
        "observed_measured_content_delta_all_events": sum(all_measured),
        "cumulative_estimated_tokens_saved": sum(estimated),
        "negative_savings_events": sum(
            1
            for event in events
            if any(
                isinstance(event["savings"].get(key), int) and event["savings"][key] < 0
                for key in ("verified_tokens_saved", "measured_content_tokens_saved", "estimated_tokens_saved")
            )
        ),
        "cumulative_local_decisions": sum(e["activity"]["local_decisions"] for e in eligible),
        "cumulative_verified_avoided_calls": sum(avoided),
        "cumulative_verified_avoided_calls_status": avoided_status,
        "cumulative_score": sum(e["score"]["earned"] for e in events),
        "authority": "DISPLAY_ONLY_NO_DECISION_EFFECT",
    }


def _tokens(value: int | None, status: str | None = None) -> str:
    if value is None:
        return status or "NOT_MEASURED"
    return f"{value:+,} Tokens"


def render_reward_audit_card(event: dict[str, Any] | None, cumulative: dict[str, Any]) -> str:
    if event is None:
        return "solve reward log is empty\nVerified savings  NOT_MEASURED\nTotal Score       0"
    ok = event["quality_gate"]["status"] == "PASS"
    mark, status = ("✓", "complete") if ok else ("✗", "quality gate failed")
    timing = event["timing"]
    savings = event["savings"]
    activity = event["activity"]
    reduction = savings["context_reduction_percent"]
    measured = _tokens(savings["measured_content_tokens_saved"])
    if reduction is not None:
        measured += f" ({reduction:+.1f}%)"
    if not ok:
        measured += " [excluded from total]"
    avoided = activity["verified_avoided_calls"]
    return "\n".join(
        (
            f"{mark} solve {status} · {timing['solve_local_elapsed_ms']:.1f} ms",
            f"Verified savings  {_tokens(savings['verified_tokens_saved'], savings['verified_status'])}",
            f"Local context     {measured}",
            f"Estimated savings {_tokens(savings['estimated_tokens_saved'])}",
            f"Local decisions   {activity['local_decisions']}",
            f"Avoided calls     {avoided if avoided is not None else 'NOT_MEASURED'}",
            f"solve Score    +{event['score']['earned']}",
            f"Verified total    {_tokens(cumulative['cumulative_verified_tokens_saved'] if cumulative['cumulative_verified_status'] != 'NOT_MEASURED' else None, cumulative['cumulative_verified_status'])}",
            f"Local total       {_tokens(cumulative['cumulative_measured_content_tokens_saved'])}",
            f"Total Score       {cumulative['cumulative_score']}",
        )
    )


def render_reward_card(event: dict[str, Any] | None, cumulative: dict[str, Any], locale: str = "en-US") -> str:
    from .presentation import render_reward_footer

    return render_reward_footer(event, cumulative, locale)


def attach_reward(
    workspace: Path,
    result: dict[str, Any],
    *,
    operation: str,
    namespace: str,
    elapsed_ns: int,
    quality_gate_pass: bool,
    quality_gate_reason: str,
    local_decisions: int = 0,
    host_round_trip_ms: float | None = None,
    host_round_trip_source: str | None = None,
    verified_avoided_calls: int | None = None,
    verified_avoided_calls_source: str | None = None,
    locale: str = "en-US",
    invocation_id: str | None = None,
    trace_id: str | None = None,
    build_id: str | None = None,
) -> dict[str, Any]:
    before = reward_stats(workspace, namespace=namespace)
    event = build_reward_event(
        result,
        operation=operation,
        namespace=namespace,
        elapsed_ns=elapsed_ns,
        quality_gate_pass=quality_gate_pass,
        quality_gate_reason=quality_gate_reason,
        local_decisions=local_decisions,
        host_round_trip_ms=host_round_trip_ms,
        host_round_trip_source=host_round_trip_source,
        verified_avoided_calls=verified_avoided_calls,
        verified_avoided_calls_source=verified_avoided_calls_source,
        invocation_id=invocation_id,
        trace_id=trace_id,
        build_id=build_id,
    )
    transaction = _record_reward_transaction(workspace, event)
    cumulative = reward_stats(workspace, namespace=namespace)
    result["reward"] = event
    result["reward_cumulative"] = cumulative
    result["reward_summary"] = render_reward_card(event, cumulative, locale=locale)
    result["reward_transaction"] = {
        "trace_id": trace_id,
        "invocation_id": invocation_id,
        "operation_status": "COMMITTED" if transaction["inserted"] else "DUPLICATE_NOT_RECORDED",
        "build_id": build_id,
        "ledger_id": transaction["ledger_id"],
        "ledger_version": transaction["ledger_version"],
        "reward_before": before["cumulative_score"],
        "reward_events": [event["event_id"]] if transaction["inserted"] else [],
        "reward_delta": event["score"]["earned"] if transaction["inserted"] else 0,
        "reward_after": cumulative["cumulative_score"],
        "reward_status": "COMMITTED" if transaction["inserted"] else "DUPLICATE",
    }
    return result


def reward_overview(workspace: Path, namespace: str | None = "production", locale: str = "en-US") -> dict[str, Any]:
    cumulative = reward_stats(workspace, namespace=namespace)
    return {
        "status": "OK",
        "cumulative": cumulative,
        "summary": render_reward_card(cumulative["latest"], cumulative, locale=locale),
    }
