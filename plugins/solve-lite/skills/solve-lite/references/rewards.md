# solve reward telemetry

Reward telemetry is a workspace-local display layer. It never changes Decision, Evidence, Packing, Ledger arithmetic, thresholds, calibration, or ranking. It has no network path and no authorization authority.

Every reward-bearing CLI result includes `user_visible_settlement`. A host MUST place that exact short field in the user-visible final response for both success and quality-gate failure. Merely persisting or returning it inside raw JSON is not user-visible settlement. `SILENT_RECEIPT` is forbidden.

## Truth buckets

- `verified_tokens_saved`: present only for a delivered, quality-passed paired provider-usage receipt with a baseline id and verification source.
- `measured_content_tokens_saved`: an exact delta for `solve-unicode-segments-v1`; it is not a provider bill reduction.
- `estimated_tokens_saved`: always separate and never promoted to verified.
- Negative values remain negative in the event and cumulative totals.

`host_round_trip_ms` remains `null` unless a host adapter supplies a real monotonic measurement and its source. Verified avoided calls likewise require a verification source. solve lite rejects either claim when its source is missing. The local timer uses `time.perf_counter_ns`; UTC wall timestamps are audit labels only.

## solve Score

solve Score is a non-monetary, display-only number capped at 100 per event:

```text
positive verified provider tokens, otherwise positive exact local tokens: floor(tokens / 100), cap 50
positive context reduction: floor(percent / 5), cap 20
completed local decisions: 5 each, cap 20
verified avoided calls: 5 each, cap 10
```

Estimated savings never add Score. A failed quality gate or a negative active savings basis produces `Score +0`. Score cannot alter decisions, abstention, thresholds, calibration, evidence rank, packing, or ledger data.

## Local persistence

Reward events use a separate workspace database at `.solve-lite/solve-rewards.sqlite3`. The existing solve Token Ledger database and formulas are unchanged. No event leaves the workspace.

```bash
python3 scripts/solve.py reward --workspace /authorized/project --format text
python3 scripts/solve.py reward --workspace /authorized/project --verbose
python3 scripts/solve.py reward --workspace /authorized/project --namespace all --format json
```

Successful `demo`, `pack`, `prepare`, `select`, and `decide` CLI invocations include a structured reward event, cumulative totals, and a human-friendly summary in their output. Failed quality gates are recorded with `Score +0` so failures are visible rather than silently omitted.

## Receipt presentation

The default human receipt is deliberately short: at most two lines and 320 visible characters. It shows verified savings when available; otherwise it shows an exact local content delta when available; otherwise it says `Token 未测`. Estimates stay hidden from the default receipt.

```text
✓ solve 完成 · 12.9 ms
本地内容缩减 434 Tokens · Score +12
累计 Score 186
详情：reward_xxxxx
```

A failed quality gate uses at most three lines and never implies that its observation entered the accepted cumulative totals.

```text
✗ solve 质量保护触发 · 4.1 ms
Score +0 · 本次不计累计
详情：reward_xxxxx
```

- `solve reward`: short human receipt.
- `solve reward --verbose`: full human audit receipt.
- `solve reward --format json`: full machine JSON.

Do not display the full audit or raw JSON to a normal user unless they explicitly ask for details, verbose output, an audit, JSON, or evidence detail.
