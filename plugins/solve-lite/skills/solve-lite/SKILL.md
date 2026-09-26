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

## What a fresh clone gives you (base Lite)

A plain clone is complete and usable immediately:

* the LITE native kernel (8 modules, hash-verified by `CORE_ASSET_MANIFEST.json`),
* the public ABI (`route_prompt`, `healthcheck`, `capabilities`),
* the host integration (hook + adapter) and the offline test suite.

| | Base Lite | + all public DLC components |
|---|---|---|
| Runtime | `plugins/solve-lite/skills/solve-lite/runtime` (~4.6 MB, 8 native modules) | same |
| Clone on disk | ~5.7 MB | ~5.7 MB + ~181.9 MB DLC assets |
| Extra download | none | 149.84 MB (review 29.17 + topic 44.32 + nli 76.35) |
| Network at runtime | never | never |
| PyTorch needed | no | only for DLC execution (`SOLVE_LITE_INT4_DLC=1`) |
| Native routes | `markov` | `markov` |
| Specialist routes | not available | available per installed component |

**Base Lite is ~5.7 MB on disk; it is never the same thing as "Lite + DLC".**
Quote the layer you mean: the DLC components are a separate 149.84 MB download.

## Install

```bash
git clone <this repository> && cd solve-lite

# 1. install: base Lite + the published specialist DLC components (default)
python3 tools/installer.py

# 2. base only, no DLC components
python3 tools/installer.py --skip-dlc

# 3. read-only status / capability report
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
really runs. A DLC component that cannot be downloaded is reported as
`DLC_NOT_INSTALLED` plus `No specialist add-on installed; base Lite is
unaffected` — the installer still succeeds and Lite still starts.

There is **no asset root to configure** and no `SOLVE_LITE_CORE_ASSET_ROOT`
requirement. `tools/installer.py --install-dlc` downloads only from this
repository's GitHub Release (`v0.1.5`), verifies every package against the
pinned release digests and the Release `SHA256SUMS`, and installs them under
`…/runtime/addons/solve-lite-int4-dlc/`. The financial specialist component is
**not published** (licence chain unresolved) and cannot be installed.

Offline/air-gapped hosts: `--package-dir <dir>` installs from local copies of the
Release packages and verifies them with the same digests. `SOLVE_LITE_DLC_OFFLINE=1`
skips the network stage entirely; `SOLVE_LITE_DLC_DOWNLOAD_ATTEMPTS` (default 3),
`SOLVE_LITE_DLC_BACKOFF_SECONDS` (default 2) and `SOLVE_LITE_DLC_DOWNLOAD_TIMEOUT`
(default 120) tune the retry/backoff/Range-resume downloader.

## Activation is a separate, opt-in step

Installing a component never runs it.  To have specialist routes actually served:

```bash
SOLVE_LITE_INT4_DLC=1 python3 tools/doctor.py --json
```

With the switch on, the loader assembles the asset-root view from the installed
components, activates the bundled INT4 backend (lazy, one resident model, DLCBusy)
and specialist routes return real decisions.  With the switch off, a route whose
component is installed still answers `SPECIALIST_CAPABILITY_UNAVAILABLE` with reason
`INT4_BACKEND_NOT_ACTIVATED` - never a hidden fallback and never a fabricated answer.

## Capability truth

* Missing *specialist* capability → `SPECIALIST_CAPABILITY_UNAVAILABLE`, with the
  reason and the exact missing directories. The core is still `AVAILABLE`; the
  native decision path still works.
* `CORE_ASSET_UNAVAILABLE` is reserved for a genuinely broken native core: a
  missing module, a hash mismatch in `CORE_ASSET_MANIFEST.json`, or an ABI Python
  that does not match the compiled modules.
* There is never a fallback computation and never a silently invented answer.

## DLC activation is opt-in

Installing a component does **not** activate it. Nothing is preloaded, and at
most one specialist model is resident at a time:

```bash
export SOLVE_LITE_INT4_DLC=1                                   # opt in to DLC execution
export SOLVE_LITE_INT4_DLC_ROOT=<repo>/plugins/solve-lite/skills/solve-lite/runtime/addons/solve-lite-int4-dlc/asset-root
export SOLVE_LITE_INT4_DLC_IDLE_SECONDS=600                    # idle unload
```

While a component is loading, a second request gets `DLCBusy` instead of a
second resident model.

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
