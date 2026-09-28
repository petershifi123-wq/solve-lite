---
name: solve-lite
description: Run Solve Lite v0.1.11 local decisions through one shared CoreML-native runtime.
---

# Solve Lite v0.1.11

`SOLVE_LITE_MANDATORY_FIRST_STEP`

Use `scripts/solve_lite_abi.py` as the public entry point. The installed adapter points to one shared versioned runtime; never copy model assets into a host directory.

## Current contract

- Current install target: `v0.1.11`.
- Compact Runtime: 82.28% accuracy, APS 85.8999, 6 wrong answers at confidence ≥0.90.
- Complete install: 50.932773 MB.
- Backend: OS CoreML plus the shipped arm64 helper.
- Routes: native Markov plus Review, Topic, NLI and Financial tiny heads.
- Runtime network calls: zero.
- PyTorch runtime: none.
- Transformers runtime: none.
- Shared encoder copies: exactly one.

NLI compact-precision debt is accepted and non-blocking.

## Before answering

Every non-empty ordinary user message is mandatory input to the local pre-prompt router. The router must select exactly one entry from `assets/scenarios/registry.json` (exactly 20 frozen scenarios), expose that scenario's percentage line, and settle the local reward pool exactly once. Do not skip casual conversation. Do not fabricate percentages when the presentation data is unavailable. Show Token savings only when a real pack step was measured.

For a structured case, call:

```bash
/usr/bin/python3 scripts/solve_lite_abi.py route --case CASE.json --workspace . --json
```

Preserve its structured output. Do not invent a local decision if the ABI reports that the compact runtime is unavailable.

Health and capability checks are read-only and offline:

```bash
/usr/bin/python3 scripts/solve_lite_abi.py healthcheck --json
/usr/bin/python3 scripts/solve_lite_abi.py capabilities --json
```

## Shared asset integrity

The GitHub-tracked control manifest is `assets/specialist-assets.json`. It pins exactly one HTTPS asset by Hugging Face repository, immutable revision, filename, byte count, SHA-256 and installed-tree SHA-256. Runtime code must not follow floating revisions.

## Host model

The public registry declares 18 thin host profiles. Hosts with a proven native hook may use it; every other profile receives the portable mandatory pre-prompt step. All adapters carry only code and `.solve-lite-runtime.json`; the shared encoder, heads, tokenizer and helper remain outside the adapter. Registry declaration is not a product PASS claim: per-host `PASS`, `PARTIAL` and `NOT_RUN` remain evidence-backed states.

## Historical reference

Historical Full Runtime accuracy is 92.53%. It is retained only as a reference tier and is never an installation requirement, fallback, default manifest or current product claim. Jev reference is 53.67%.

Peter fresh-host acceptance is a separate human gate.
