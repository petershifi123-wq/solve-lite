# Changelog

## 0.1.7 — 2026-09-27

- **Unconditional activation (P1).** The `UserPromptSubmit` hook now runs on every prompt and always injects a structured result; activation is a mechanism, not a model decision. When the LITE layer produces no prompt-level decision the envelope says so (`本轮本地结论=无`) and explicitly forbids inventing Choice/Token/reward lines. This supersedes the 0.1.6 "stays silent" behaviour for the ordinary-prompt path.
- **The hook gate now uses the per-route truth.** The aggregate specialist flag is `UNAVAILABLE(MODEL_PACK_MISSING)` on every public install (the two financial packs are never published), so gating on it meant an installed specialist could never be reached from a host prompt. The hook asks `routes_available` for the `nli` route it needs and resolves the DLC asset root through `solve_lite_dlc.effective_asset_root()`; an installed DLC now produces a real calibrated decision on the ordinary prompt path.
- **Install-time host registration.** `python3 tools/installer.py --host workbuddy|doubao|auto` registers the hook in the host's own writable config (settings-level `hooks` entry plus a local directory-marketplace plugin layer), is idempotent, backs up every file it touches, and prints a ready-to-paste one-step command when the host exposes no hook API. `install_workbuddy.command` and `install_doubao.command` install, self-test and run `startup_check` from a double click, with no sudo.
- **New host tools.** `tools/host_hooks.py` (detect / register / unregister), `tools/hook_selftest.py` (`HOOK_FIRED=PASS|FAIL` by replaying the host's own registered command, with ledger, latency and RSS evidence; a host without a hook API is asserted on its off-host pre-prompt step and labelled `HOST_HOOK_API=NO_HOST_HOOK_API`, never smoothed into a PASS) and `tools/build_public_manifest.py` (regenerates `PUBLIC_REPO_MANIFEST.json` + `SHA256SUMS.txt`; verified to reproduce the previous tree-hash formula byte-for-byte).
- **Install-time DLC asset-view pre-assembly.** A DLC install now finishes by calling `assemble_asset_root()` and reports the outcome, so the first specialist call does not pay for building the view. Measured on the host-shaped copies: pre-assembly idempotent in ~0.2ms; first prompt-level specialist call 2.26s wall (and 63ms for the LITE-only path with no DLC activated).
- **Doubao Work has no local hook API.** The installer writes the skill plus a mandatory first-step banner into the host workspace and reports `UNAVAILABLE_NO_HOST_HOOK_API` with a copy-paste one-step command, instead of claiming an automatic hook.
- **Fresh-install tests pin their own environment.** `test_package.py`, `test_solve_lite_abi.py` and `tools/offline_harness.py` now clear `SOLVE_LITE_INT4_DLC` / `SOLVE_LITE_INT4_DLC_ROOT` (and the runtime-root overrides) instead of inheriting them. All three assert the plain-environment contract, so an ambient opt-in in a developer's shell used to produce a false `ACTIVATED != NOT_ACTIVATED` failure and a false `dlc_not_preloaded=false` on a clean tree.
- Unchanged: math, thresholds, calibration, native kernel bytes and the frozen runtime modules.

## 0.1.6 — 2026-09-27

- **Fresh install works out of the box.** The public repository now carries the LITE runtime (8 verified native modules, ~4.6MB) and the public loader finds it with no configuration: `healthcheck` returns `PASS`, a native decision runs offline, and `SOLVE_LITE_CORE_ASSET_ROOT` is no longer required (honoured only as a deprecated override).
- Removes the stale install/run requirements: `PUBLIC_SELF_CONTAINED_DISTRIBUTION` is now `TRUE`, and the v2 full-precision core manifest with its `EXTERNAL_REQUIRED` model directories and `2.33GB` total is kept only as `CORE_ASSET_MANIFEST_FULL_FP_REFERENCE.json`, explicitly labelled a historical reference and not an install requirement.
- **DLC components instead of an all-or-nothing pack.** The three public specialist packs (`review` 29.17MB, `topic` 44.32MB, `nli` 76.35MB download) install with `python3 tools/installer.py --install-dlc` from this repository's GitHub Release only; the financial pair stays `NOT_PUBLIC`. Installation is verified against pinned release digests, staging is reclaimed, and installing a DLC never activates it (`SOLVE_LITE_INT4_DLC=1` opt-in, lazy, `max_resident_dlc=1`, `DLCBusy` semantics unchanged).
- **Error semantics corrected.** A missing specialist pack is reported as `SPECIALIST_CAPABILITY_UNAVAILABLE` with the exact missing directories; `CORE_ASSET_UNAVAILABLE` is now reserved for a genuinely broken native core (missing module or hash mismatch). The UserPromptSubmit hook no longer raises on a partial config and stays silent instead of injecting a footer for a decision that was not computed.
- Rebased the host evidence on fresh isolated installs: Doubao and WorkBuddy shapes verified end-to-end on a clean clone; Codex/Hermes keep their earlier scope (`PASS_VERIFIED_PUBLIC_ABI_PRIOR_SCOPE`), and untested hosts are labelled `UNTESTED_PUBLIC_ABI_AVAILABLE`.
- Repacks the LITE runtime release asset with the new loader and refreshes every affected checksum (`SHA256SUMS.txt`, `PUBLIC_REPO_MANIFEST.json`, `addon-index.json`, `INT4_DLC_VALIDATION_SUMMARY.json`).
- **Round 2.** `ASSET_ROOT_MISSING` is retired: the only core failure code is `CORE_ASSET_UNAVAILABLE` ("bundled LITE runtime not found or damaged (reinstall the package)"), and a clean clone provably never produces it.
- **Round 2.** A plain `python3 tools/installer.py` now installs the three public DLC components by default (`--skip-dlc` opts out), and finishes by running `tools/startup_check.py`, printing `STARTUP_CHECK=PASS|FAIL`.
- **Round 2.** DLC downloads survive a flaky CDN: retry with exponential backoff (default 3 attempts), HTTP Range resume, post-download sha256 verification with retry, plus `SOLVE_LITE_DLC_OFFLINE` and the attempts/backoff/timeout knobs. A failed download reports `DLC_NOT_INSTALLED` and "No specialist add-on installed; base Lite is unaffected" - the install still succeeds.
- **Round 3.** Activation now actually assembles the runtime view: `assemble_asset_root()` rebuilds `runtime/addons/solve-lite-int4-dlc/asset-root` from the installed units (symlink first, copy if the filesystem refuses links, idempotent and self-healing), the loader activates the bundled INT4 backend when `SOLVE_LITE_INT4_DLC=1`, and specialist gating is per route instead of one global five-directory gate. Verified on an isolated install: `nli` returns a real calibrated decision, `topic` too, at most one resident DLC (load/unload swap), and `DLCBusy` when a swap is attempted with a forward in flight.
- **Round 3.** `tools/startup_check.py` reports the base runtime as the LITE core payload only (`BASE_SIZE_SANE` keeps it inside 4.0-5.5MB and excludes `runtime/addons/**` and `runtime/dlc_runtime/**`); DLC numbers are reported separately.
- **Round 3.** `tools/installer.py --help` states the default install (three public DLC components), the opt-in activation switch and `--skip-dlc`.
- Unchanged: math, thresholds, calibration, probability and markov implementations, and the frozen native kernel bytes (the 8 modules are byte-identical to the LITE build lot; only the already-authorised lazily-importing `_slk5` differs from the full-precision core).

## 0.1.5 — 2026-09-27

- Publishes the two capability surfaces: **Lite Runtime** (~4.6MB · CPU-only · ~24MB idle RAM · No PyTorch · No model weights · Offline native decision runtime) and **Specialist Runtime** (optional semantic capabilities using external model packs and ML dependencies).
- States the 2.33GB specialist assets as `OPTIONAL · NOT REQUIRED FOR LITE`.
- Headlines the current validated latency scope `~34×` (Solve Lite full-capability mean 40.767 ms vs Jev 1388.328 ms = 34.06×). The earlier frozen figures (mean 32.46 ms, ~42.8×) are retained only as `HISTORICAL_FROZEN_RESULT` and are no longer the headline claim.
- Keeps the frozen benchmark record unchanged: 92.53% vs Jev 53.67%, 3–0 across three frozen rounds, 1,500 cases / 7,500 decisions, 6 vs 282 wrong answers at ≥90% confidence.
- Names host evidence as `HOST_SHAPED_COLD_INSTALL_COMPATIBILITY=PASS`, `NATIVE_DESKTOP_PROCESS_INTEGRATION=NOT_RUN`, `FULL_UI_LIFECYCLE=NOT_CLAIMED`.
- Keeps Native Core 0.1.3, external model ownership, fail-closed loading, `PUBLIC_SELF_CONTAINED_DISTRIBUTION=FALSE` and all protected product boundaries unchanged.
- Does not modify math, thresholds, calibration, probability or markov implementations; no Core rebuild and no Core binary byte mutation.

- Adds optional **Compact Specialist Add-ons** (review / topic / NLI) for advanced semantic capabilities: mixed int4/int3 grouped quantization, 34.96 / 51.86 / 94.98 MB, downloaded and loaded strictly on demand, one at a time, with idle unload; decision agreement vs the frozen full-precision reference 97.47% / 99.13% / 95.93%.
- Records that the 2.33 GB full-precision specialist pack is no longer required for anything: Lite runs without it and add-ons are optional.
- Keeps financial specialist assets out of all public packages and releases (licence chain unresolved; engineering-verification-only).
- Adds `addon-index.json` and `INT4_DLC_VALIDATION_SUMMARY.json` release evidence; no case-level prompts or expected outputs are published.

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
