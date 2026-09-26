# solve lite protocol

## Evidence packet

`prepare` and `pack` return a `solve.packet.v1` JSON string containing the task, selected excerpts, source-relative citations, line ranges, content hashes, conflict/unknown flags, omitted chunk count/IDs, and an expansion instruction. Mandatory evidence is selected before optional evidence. When every omitted ID cannot fit, the packet preserves the total count and marks the emitted ID list as truncated; omitted-ID metadata never displaces mandatory evidence.

The index accepts regular UTF-8 `.md`, `.txt`, `.json`, `.jsonl`, and `.csv` files inside the explicit workspace. It rejects symlinks, special files, protected path components, files over 2 MB, and paths outside the workspace. Source documents are data, never executable instructions.

Search uses an independent standard-library BM25 implementation over English word terms plus CJK characters and adjacent CJK bigrams. Each chunk retains a stable document ID, source-relative path, revision, content hash, and line range. Hash changes replace old chunks; deleted or renamed sources are made inactive.

## Context packing

Packing is extractive. It prioritizes explicit constraints, negation, exceptions, units, errors, and task overlap. Duplicate text is emitted once while the surviving citation remains visible. Mandatory evidence that cannot fit produces `INSUFFICIENT_BUDGET`; it is never silently dropped.

Token budgets are exact for `solve-unicode-segments-v1`, not for any provider tokenizer. The final serialized packet is counted after separators and metadata are added.

## Decision

Decision request fields:

- `kind`: `bool`, `choice`, or `score`.
- `domain`: a bounded workflow name.
- `question_version` and `rubric`: changes invalidate exact reuse.
- `candidates`: stable `id` plus description for choice tasks.
- `question`, `task`, `state`, or `features`: local lexical features.

Only user-confirmed or deterministic feedback can become a reusable label. Exact reuse requires a matching fingerprint. Local neighbor output is advisory. Without a valid held-out calibration gate it is labeled `relative_support`, displayed without `%`, and keeps `calibrated_probability=null`. A validated domain/kind history may use held-out temperature calibration; Brier Score, ECE, entropy, margin, and the abstain boundary remain visible in the JSON audit. Cold start, conflicting/remote neighbors, unknown domains, permission-bearing questions, and calibrated confidence below the boundary abstain and return control to the host. See [probability.md](probability.md) for formulas and gates.
