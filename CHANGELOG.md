# Changelog

## 0.1.5 — 2026-09-27

- Introduces the **Lite Runtime**: ~4.6MB, CPU-only, ~24MB idle RAM, no PyTorch, no model weights, offline native decision runtime (native subset only, `LITE_NATIVE_CAPABILITIES=MARKOV_ONLY`).
- The 2.33GB specialist model assets become `OPTIONAL` / `NOT_REQUIRED_FOR_LITE`; when the pack is absent the specialist routes return `SPECIALIST_CAPABILITY_UNAVAILABLE` instead of blocking the whole runtime.
- Retires the headline `~42.8×` latency claim into `HISTORICAL_FROZEN_RESULT`. The current validated full-capability build measures 40.77 ms mean against Jev 1388.33 ms official remote API end-to-end (~34×), same comparison caliber as before.
- Records host evidence naming: `HOST_SHAPED_COLD_INSTALL_COMPATIBILITY=PASS`, `NATIVE_DESKTOP_PROCESS_INTEGRATION=NOT_RUN`, `FULL_UI_LIFECYCLE=NOT_CLAIMED`.
- Keeps frozen math / threshold / calibration / probability unchanged; the only native delta is a lazy-import fix in the LITE build so the default path no longer requires PyTorch or model weights.

## 0.1.4 — 2026-09-26

- Records the one-time VV-approved four-host clean-fork closure for Codex, Hermes, Doubao, and WorkBuddy.
- Promotes only the proven clean-host public ABI scope; it does not claim full desktop UI or automatic lifecycle support.
- Keeps Cline and Qwen at `PARTIAL_FROZEN`, and Cursor at `NOT_RUN`.
- Keeps Native Core 0.1.3, external model ownership, fail-closed loading, and all protected product boundaries unchanged.

## 0.1.3 — 2026-09-26

- Declares one portable `UserPromptSubmit` hook at `hooks/hooks.json`.
- Preserves local structured route percentages, truthful per-trace token settlement, and local reward accumulation.
- Includes supported Codex plugin lifecycle diagnostics without trust bypass.
- Adds deterministic local-only packaging, canonical source/cache parity evidence, offline tests, and redacted closeout receipts.
- Excludes machine-specific runtime configuration, installed-cache copies, private Core source, credentials, session data, and remote release actions.
- Keeps product acceptance at `GATE_AWAITING_ORDINARY_SESSION` until a fresh post-baseline Codex Desktop session proves advancement and visible presentation.
