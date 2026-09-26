# Honest measurement

solve lite separates four buckets:

1. `content_delta`: before/after text under the same named tokenizer.
2. `host_usage`: formal usage reported by the host or provider.
3. `paired_experiment`: baseline usage minus solve lite usage under one task and quality contract.
4. `estimate`: potential or estimated values that did not occur as observed usage.

The endpoint delta is counted once. Stage-level changes explain attribution but are not added to the endpoint total. Cached input is part of input, and reasoning output is part of output when the provider says so; neither is added twice. Overhead already included in `after` or host usage is not deducted again. Unknown is `null`, negative values stay negative, and demo/test/benchmark namespaces never award production achievements.

`solve-unicode-segments-v1` counts English word/number segments, each CJK character, and punctuation as documented local tokens. `exact_for_selected_tokenizer` means exactly that; it does not claim an exact model tokenizer.

No solve lite report may describe content reduction as a refund, returned credit, account balance, or provider cost saving. Use `BENEFIT=NOT_MEASURED` until a fair paired real-host run captures usage and quality.
