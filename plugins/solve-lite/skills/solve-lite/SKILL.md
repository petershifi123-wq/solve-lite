---
name: solve-lite
description: Use when a host needs a local, offline decision layer - Solve Lite answers bounded Choice/Score questions with a native kernel and optional specialist DLC components, all on CPU without a remote decision service.
license: Apache-2.0
---

# Solve Lite

Solve Lite is a local decision layer for agent hosts. It answers **bounded**
questions ("which of these options", "how strongly", "is this entailed") and
returns a structured decision plus a reward/token settlement, without calling a
remote decision service.

## MANDATORY CONTRACT / 强制契约（所有宿主，含没有 hook API 的宿主）

<!-- SOLVE_LITE_MANDATORY_FIRST_STEP -->

Every host — including hosts that expose no hook API — MUST satisfy this before answering:

1. **Run one local Lite pass on every user prompt first.** The host model never decides
   whether Solve Lite applies.
   * host with a hook API -> the `UserPromptSubmit` hook does it automatically
     (activation model: `CAPABILITY_ROUTED_LAZY`).
   * host without a hook API -> make it the fixed first step outside the model, or run the
     one-step command: `python3 "<plugin>/hooks/user_prompt_submit.py" --clipboard`.
   * verify any host: `python3 tools/hook_selftest.py --host auto`.

2. **Presentation is mandatory (20 decision scenarios included).**
   * Decision **percentages** — rendered from `raw_support` with `support_semantics`
     labelled; a degenerate calibrated distribution is never presented as the conclusion.
   * **Reward-pool settlement** — `+N Score | Total M · 🔒 Local` — must be shown.
   * The **Token line** is shown only when the trace really packed context
     (`status == MEASURED_PACK`); otherwise that single line is omitted.

3. **Public specialist DLC is installed by default and loaded by capability.** Review,
   Topic and NLI stay separate from Core, are not preloaded, and only the DLC selected by
   the existing capability router may be resident: one at a time, released when idle.

## What a fresh clone gives you (base Lite)

A plain clone is complete and usable immediately:

* the LITE native kernel (8 modules, hash-verified by `CORE_ASSET_MANIFEST.json`),
* the public ABI (`route_prompt`, `healthcheck`, `capabilities`),
* the host integration (hook + adapter) and the offline test suite.

| | Base Lite | + all public DLC components |
|---|---|---|
| Runtime | `plugins/solve-lite/skills/solve-lite/runtime` (~4.6 MB, 8 native modules) | same |
| Clone on disk | ~5.7 MB | ~5.7 MB + repo-local specialist venv + ~181.9 MB DLC assets |
| Extra download | none | 149.84 MB (review 29.17 + topic 44.32 + nli 76.35) |
| Network at runtime | never | never |
| PyTorch needed | no | installed only inside the repo-local venv; imported only for a DLC route |
| Native routes | `markov` | `markov` |
| Specialist routes | not available | available per installed component |

**Base Lite is ~5.7 MB on disk; it is never the same thing as "Lite + DLC".**
Quote the layer you mean: the DLC components are a separate 149.84 MB download.

## Install

```bash
git clone <this repository> && cd solve-lite

# 1. install: base Lite + the published specialist DLC components (default)
python3 tools/installer.py

# 2. read-only status / capability report
python3 tools/installer.py --check
python3 tools/doctor.py --json
```

The installer finishes by running the startup checker and prints
`STARTUP_CHECK=PASS` or `STARTUP_CHECK=FAIL`; before the first session (or any
time later) you can ask it directly:

```bash
python3 tools/startup_check.py --json
```

`STARTUP_CHECK=PASS` means this install can be used right now: the bundled LITE
core is verified, `healthcheck` passes with no asset root, and a native decision
really runs. Normal installation also requires the pinned repository-local
specialist venv and all three public DLCs. A missing dependency, hash mismatch,
or failed DLC download makes the normal installer fail closed; `--skip-dlc` is
an engineering-only Base Lite fixture switch.

There is **no asset root to configure** and no `SOLVE_LITE_CORE_ASSET_ROOT`
requirement. `tools/installer.py --install-dlc` downloads only from this
repository's GitHub Release (`v0.1.7`), verifies every package against the
pinned release digests and the Release `SHA256SUMS`, and installs them under
`…/runtime/addons/solve-lite-int4-dlc/`. The financial specialist component is
**not published** (licence chain unresolved) and cannot be installed.

Offline/air-gapped hosts: `--package-dir <dir>` installs from local copies of the
Release packages and verifies them with the same digests. `SOLVE_LITE_DLC_OFFLINE=1`
skips the network stage entirely; `SOLVE_LITE_DLC_DOWNLOAD_ATTEMPTS` (default 3),
`SOLVE_LITE_DLC_BACKOFF_SECONDS` (default 2) and `SOLVE_LITE_DLC_DOWNLOAD_TIMEOUT`
(default 120) tune the retry/backoff/Range-resume downloader.

No user-managed Torch/Transformers setup is required. The installer creates
`runtime/specialist-env`, installs the exact hash-locked dependency set there,
and never uses system/global `pip`. If compatible CPython 3.9 is absent, it
downloads the pinned macOS arm64 fallback in `runtime/specialist-python` and
verifies the archive SHA-256 before extraction. Lite startup checks only the
signed local receipt and does not start the specialist worker.

## Capability-routed lazy activation

Installing a component never preloads it. The existing case-schema capability router
selects the required route and activates that installed DLC automatically and lazily.
Native Markov requests do not activate a specialist. Arbitrary bounded natural-language
questions use NLI; do not invent a prompt-to-Markov schema. At most one model is resident,
and a concurrent swap returns `DLCBusy` rather than loading a second model.

## Capability truth

* Missing *specialist* capability → `SPECIALIST_CAPABILITY_UNAVAILABLE`, with the
  reason and the exact missing directories. The core is still `AVAILABLE`; the
  native decision path still works.
* `CORE_ASSET_UNAVAILABLE` is reserved for a genuinely broken native core: a
  missing module, a hash mismatch in `CORE_ASSET_MANIFEST.json`, or an ABI Python
  that does not match the compiled modules.
* There is never a fallback computation and never a silently invented answer.

## DLC residency

Nothing is preloaded. At most one specialist model is resident at a time; while
a component is loading, a second request gets `DLCBusy` instead of a second
resident model. `SOLVE_LITE_INT4_DLC_ROOT` remains an engineering override, not
a public-install step.

## Host integration

* `hooks/user_prompt_submit.py` — Codex-style `UserPromptSubmit` bridge. It reads
  an optional `.codex-runtime.json` and works without one. When no local decision
  can be computed it returns `{"continue": true, "suppressOutput": true}` and
  records why; it never fabricates a Choice/Token/reward footer.
* `tools/adapter.py doctor|install|uninstall` — adapter lifecycle.
* `scripts/solve_lite_abi.py healthcheck|capabilities|routes|route --case f.json`
  — dependency-free CLI for hosts that prefer a command over a hook.
* `route_prompt` compatibility: `routes` (`available_routes`) tells a host what
  this install can answer before it asks.

## Environment

| Variable | Purpose |
|---|---|
| `SOLVE_LITE_RUNTIME_ROOT` | Override the runtime location (optional) |
| `SOLVE_LITE_CORE_ASSET_ROOT` | Legacy alias, still honoured, never required |
| `SOLVE_LITE_WORKSPACE` | Where audit/ledger files are written |
| `SOLVE_LITE_INT4_DLC` | `1` opts in to DLC execution |
| `SOLVE_LITE_INT4_DLC_ROOT` | Asset root for DLC execution |
| `SOLVE_LITE_INT4_DLC_IDLE_SECONDS` | Idle unload timer for the resident DLC |

## Verify

```bash
python3 tools/offline_harness.py     # integration suites, no network, no mutation
```
