# Scenario Signal Gallery

solve lite maps a finite scenario registry to its existing decision primitives. The registry supplies observable Chinese labels and axis shape; it does not introduce scenario-specific decision algorithms.

## Axis shapes

- `ONE_PRIMARY_DISTRIBUTION`: one mutually exclusive distribution backed by `choice`.
- `ORDERED_SCORE_DISTRIBUTION`: ordered levels backed by `score`.
- `MULTI_INDEPENDENT_NOUL`: separate yes/no signals backed by the existing `bool` primitive. Independent axes are never normalized against each other.

## Probability truth

- `calibrated_probability` may render `%`; deterministic largest-remainder rounding makes each choice/score distribution total 100.
- `relative_support` renders numbers without `%`.
- No renderer may invent or relabel an uncalibrated value as probability.
- An abstained axis stays abstained. The renderer does not guess a state.

## Trace and measurement truth

Every scenario run follows one local trace: `PACK -> actual packet -> DECIDE -> PRESENT -> COMPOSITE SETTLEMENT`. If packing produces a measurement, the decision consumes that exact packet and the receipt links to the pack event. If no pack measurement exists, the receipt says `Token 未测`. Score is written once for the composite scenario event.

## Chat boundary

`CHAT_RELATIONSHIP` includes `intent`, `momentum`, `reciprocity`, and `next_step`, with optional reply timing and conversation risk. Labels describe current text or interaction signals. Claims about a person's hidden or “true” feelings are forbidden.

## Public families

The bundled V1 registry contains chat relationship, message intent, customer support, sales lead, email priority, agent next action, agent loop control, completion verification, LLM output guard, RAG relevance, claim verification, content moderation, operations decision, document/data quality, and product/content routing.

List the registry with `solve scenarios --json`. Run one family with `solve scenario --workspace <path> --input scenario.json --task "分析当前信号"`, where `scenario.json` contains `scenario_id`, authorized `text`, and optional `axis_ids`/`axis_requests`. Add `--verbose` or `--format json` for the full axis payload.
