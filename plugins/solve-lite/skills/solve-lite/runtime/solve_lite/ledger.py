from __future__ import annotations

import html
import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

from .core import TOKENIZER_ID, canonical_json, count_tokens, sha256_text, stable_id, state_dir, utc_now


def connect(workspace: Path) -> sqlite3.Connection:
    db = sqlite3.connect(state_dir(workspace) / "solve-lite.sqlite3", timeout=30)
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
    db.execute("PRAGMA foreign_keys=ON")
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS receipts (
          event_id TEXT PRIMARY KEY,
          namespace TEXT NOT NULL,
          event_type TEXT NOT NULL,
          kind TEXT NOT NULL,
          task_id TEXT NOT NULL,
          pipeline_id TEXT NOT NULL,
          request_slot_id TEXT NOT NULL,
          receipt_json TEXT NOT NULL,
          reverses_event_id TEXT,
          created_at TEXT NOT NULL
        );
        CREATE UNIQUE INDEX IF NOT EXISTS one_reversal_per_event
          ON receipts(reverses_event_id) WHERE event_type='reversal';
        """
    )
    return db


def content_delta(before: int | None, after: int | None, overhead: int | None, overhead_in_after: bool, quality: str) -> tuple[int | None, str]:
    if before is None or after is None or (overhead is None and not overhead_in_after):
        return None, "unavailable"
    net = before - after - (0 if overhead_in_after else int(overhead or 0))
    return net, "estimate" if quality == "estimated" else "content_delta"


def provider_total(usage: dict[str, Any] | None) -> int | None:
    if usage is None:
        return None
    if usage.get("total_tokens") is not None:
        return int(usage["total_tokens"])
    if usage.get("input_tokens") is None or usage.get("output_tokens") is None:
        return None
    # cached input and reasoning output are provider-reported subsets, not addends.
    return int(usage["input_tokens"]) + int(usage["output_tokens"])


def paired_usage_delta(baseline: dict[str, Any] | None, solve: dict[str, Any] | None) -> int | None:
    a, b = provider_total(baseline), provider_total(solve)
    return None if a is None or b is None else a - b


def make_content_receipt(
    workspace: Path,
    before_text: str,
    after_text: str,
    *,
    task_id: str,
    namespace: str,
    evidence_level: str = "text_comparison",
    delivery_status: str = "planned",
    overhead_tokens: int | None = None,
    overhead_in_after: bool = True,
    count_quality: str = "exact_for_selected_tokenizer",
    pipeline_id: str | None = None,
    request_slot_id: str = "context_packet",
    task_outcome: str = "pending",
) -> dict[str, Any]:
    before = count_tokens(before_text)
    after = count_tokens(after_text)
    if overhead_tokens is None:
        overhead_tokens = count_tokens(
            f"solve lite receipt: {TOKENIZER_ID}; provider savings NOT_MEASURED; task outcome {task_outcome}."
        )
        overhead_in_after = False
    delta, bucket = content_delta(before, after, overhead_tokens, overhead_in_after, count_quality)
    workspace_id = stable_id(str(workspace.resolve()), prefix="ws_")
    receipt = {
        "schema_version": "solve.receipt.v1",
        "event_id": f"evt_{uuid.uuid4().hex}",
        "workspace_id": workspace_id,
        "task_id": task_id,
        "pipeline_id": pipeline_id or f"pipe_{uuid.uuid4().hex[:20]}",
        "request_slot_id": request_slot_id,
        "kind": "estimate" if bucket == "estimate" else "content_delta",
        "namespace": namespace,
        "event_type": "measurement",
        "timestamp": utc_now(),
        "evidence_level": evidence_level,
        "baseline_spec_id": None,
        "before_sha256": sha256_text(before_text),
        "after_sha256": sha256_text(after_text),
        "counts": {
            "before": before,
            "after": after,
            "tokenizer_id": TOKENIZER_ID,
            "count_quality": count_quality,
            "overhead_tokens": overhead_tokens,
            "overhead_in_after": overhead_in_after,
            "content_delta": delta,
            "bucket": bucket,
        },
        "delivery_status": delivery_status,
        "task_outcome": task_outcome,
        "verification_source": None,
        "provider_usage": None,
        "paired_baseline_usage": None,
        "reverses_event_id": None,
    }
    return receipt


def record(workspace: Path, receipt: dict[str, Any]) -> bool:
    with connect(workspace) as db:
        cursor = db.execute(
            """
            INSERT OR IGNORE INTO receipts
            (event_id, namespace, event_type, kind, task_id, pipeline_id,
             request_slot_id, receipt_json, reverses_event_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                receipt["event_id"],
                receipt["namespace"],
                receipt["event_type"],
                receipt["kind"],
                receipt["task_id"],
                receipt["pipeline_id"],
                receipt["request_slot_id"],
                canonical_json(receipt),
                receipt.get("reverses_event_id"),
                receipt["timestamp"],
            ),
        )
        return cursor.rowcount == 1


def reverse(workspace: Path, event_id: str, *, task_id: str) -> dict[str, Any]:
    with connect(workspace) as db:
        original = db.execute("SELECT receipt_json FROM receipts WHERE event_id=?", (event_id,)).fetchone()
        if not original:
            raise ValueError(f"Unknown event_id: {event_id}")
        old = json.loads(original[0])
        receipt = dict(old)
        receipt.update(
            event_id=f"rev_{uuid.uuid4().hex}",
            task_id=task_id,
            event_type="reversal",
            timestamp=utc_now(),
            reverses_event_id=event_id,
            task_outcome="unknown",
        )
        try:
            inserted = record(workspace, receipt)
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"Event already reversed: {event_id}") from exc
        if not inserted:
            raise ValueError(f"Event already reversed: {event_id}")
        return receipt


def _live_receipts(workspace: Path) -> list[dict[str, Any]]:
    with connect(workspace) as db:
        rows = db.execute("SELECT receipt_json FROM receipts ORDER BY created_at, event_id").fetchall()
    receipts = [json.loads(row[0]) for row in rows]
    reversed_ids = {r.get("reverses_event_id") for r in receipts if r["event_type"] == "reversal"}
    return [r for r in receipts if r["event_type"] != "reversal" and r["event_id"] not in reversed_ids]


def stats(workspace: Path) -> dict[str, Any]:
    live = _live_receipts(workspace)
    buckets: dict[str, dict[str, Any]] = {}
    for receipt in live:
        ns = receipt["namespace"]
        bucket = buckets.setdefault(ns, {"events": 0, "content_delta": 0, "unknown": 0, "negative_events": 0})
        bucket["events"] += 1
        delta = receipt.get("counts", {}).get("content_delta")
        if delta is None:
            bucket["unknown"] += 1
        else:
            bucket["content_delta"] += delta
            if delta < 0:
                bucket["negative_events"] += 1
    production = buckets.get("production", {"events": 0, "content_delta": 0, "unknown": 0, "negative_events": 0})
    achievements = []
    if production["events"]:
        achievements.append("first-production-measurement")
    if production["content_delta"] >= 10_000:
        achievements.append("ten-thousand-token-organizer")
    return {
        "schema_version": "solve.stats.v1",
        "scope": "solve lite-visible receipts only",
        "namespaces": buckets,
        "achievements": achievements,
        "provider_savings": None,
        "provider_savings_status": "NOT_MEASURED",
        "note": "Content delta is not a provider refund or account balance.",
    }


def render_card(data: dict[str, Any]) -> str:
    prod = data["namespaces"].get("production", {})
    return (
        "solve lite · visible ledger\n"
        f"production events: {prod.get('events', 0)}\n"
        f"content delta: {prod.get('content_delta', 0)} [{TOKENIZER_ID}]\n"
        "provider/host savings: NOT_MEASURED\n"
        "Content delta is not a refund or credit balance."
    )


def render_html(data: dict[str, Any]) -> str:
    payload = html.escape(json.dumps(data, ensure_ascii=False, indent=2))
    return (
        "<!doctype html><meta charset='utf-8'><title>solve Token Ledger</title>"
        "<style>body{font:16px system-ui;max-width:880px;margin:3rem auto;padding:0 1rem}"
        "pre{white-space:pre-wrap;background:#f5f5f5;padding:1rem}</style>"
        "<h1>solve Token Ledger</h1><p>Offline report. No CDN, telemetry, or remote fonts.</p>"
        f"<pre>{payload}</pre>"
    )
