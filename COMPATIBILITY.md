# Compatibility Snapshot

This snapshot reports only the capability proven by machine evidence. A fresh-install public ABI PASS does not claim a native desktop UI hook, automatic installer lifecycle, or full host-product support.

| Surface | Version | Status |
|---|---|---|
| Solve Lite public plugin | 0.1.7 | FRESH_INSTALL_ACCEPTANCE_PASS |
| LITE runtime (bundled, 8 native modules) | LITE build lot | PASS_VERIFIED_BUNDLED_RUNTIME |
| Full-precision core manifest | v2 (historical) | HISTORICAL_REFERENCE_ONLY |
| DLC components (review, topic, nli) | 0.1.7 packages | DEFAULT_INSTALL + CAPABILITY_ROUTED_LAZY_ACTIVATION |
| Shared specialist runtime | pinned CPython 3.9 + hash-locked venv | REPO_LOCAL / NO_GLOBAL_PIP / LAZY_WORKER |
| Financial specialist DLC | not published | NOT_PUBLIC |
| Doubao | fresh isolated host shape | PASS_VERIFIED_FRESH_INSTALL_PUBLIC_ABI + UNAVAILABLE_NO_HOST_HOOK_API |
| WorkBuddy | fresh isolated host shape | PASS_VERIFIED_FRESH_INSTALL_PUBLIC_ABI + HOST_HOOK_REGISTRATION_PASS |
| Codex | prior scope | PASS_VERIFIED_PUBLIC_ABI_PRIOR_SCOPE |
| Hermes | prior scope | PASS_VERIFIED_PUBLIC_ABI_PRIOR_SCOPE |
| Cline | not rerun in this gate | PARTIAL_FROZEN |
| Qwen | not rerun in this gate | PARTIAL_FROZEN |
| Cursor | not run | NOT_RUN |
| macOS | 27.0 arm64 | TESTED |
| Python | CPython 3.9 ABI, macOS arm64 | TESTED; INSTALLER-MANAGED FALLBACK |

The two fresh isolated hosts each started from a clean copy of the public tree and passed the recorded v0.1.7 scope: bundled-runtime healthcheck `PASS` with no asset root configured, one real offline native decision, verified installation of the three public DLC components, and byte-identical frozen kernel modules. The current P0 contract supersedes its old manual-activation policy: normal installation includes all three public DLCs, while the capability router activates only the required one lazily. Network attempts during runtime, credential reads, and Jev API calls remain zero. Codex and Hermes were verified earlier under the owner-runtime scope and are not re-claimed here.

P1 host activation adds two machine-checkable facts on top of that scoped PASS:

- WorkBuddy: the installer writes one authoritative plugin-manifest `UserPromptSubmit` hook, using the host-provided `CODEBUDDY_PLUGIN_ROOT` / `CLAUDE_PLUGIN_ROOT`, and removes only its own legacy settings-level duplicate. The self-test replays **that exact registered command** with a host-shaped bounded payload, proves a real NLI result, a percentage envelope and an audit-backed reward settlement, and verifies that missing plugin-root variables fail open. `HOST_HOOK_REGISTRATION=PASS`, `HOST_HOOK_DISPATCH_REPLAY=PASS` in isolated host-shaped testing; native desktop manual acceptance remains separately scoped.
- Doubao Work: the app bundle contains no `UserPromptSubmit`, `hookSpecificOutput` or hook-config reader, so there is nothing to register. The installer instead wrote the skill plus a mandatory first-step banner into the host workspace, asserted that banner, and printed the copy-paste one-step command. `HOST_HOOK_API=NO_HOST_HOOK_API`; the off-host pre-prompt step is asserted in its place and reported as such, not as a host hook.
- Neither fact claims the desktop UI process itself was driven by a human prompt: `NATIVE_DESKTOP_PROCESS_INTEGRATION=NOT_RUN`. No installer step used sudo and no system directory was written.

Evidence identity:

- Public repository payload: `PUBLIC_REPO_MANIFEST.json` (`payload_tree_sha256`)
- Bundled LITE runtime: `CORE_ASSET_MANIFEST.json` (8 module hashes)
- Historical full-precision core manifest: `CORE_ASSET_MANIFEST_FULL_FP_REFERENCE.json`
- Fresh-install receipts: `acceptance/runs/*.json` in the release evidence bundle

Host evidence naming / 宿主证据命名:

```
HOST_SHAPED_FRESH_INSTALL_COMPATIBILITY=PASS
NATIVE_DESKTOP_PROCESS_INTEGRATION=NOT_RUN
FULL_UI_LIFECYCLE=NOT_CLAIMED
```

Distribution truth: `PUBLIC_SELF_CONTAINED_DISTRIBUTION=TRUE` for base Lite (bundled LITE runtime, no asset root required). Normal public installation creates a repository-local pinned specialist environment and downloads the three public DLC packs only from this repository's Release; the financial pair is `NOT_PUBLIC`. No system/global Python package state is changed. DLCs are not preloaded, and a missing required runtime or pack is reported as `SPECIALIST_CAPABILITY_UNAVAILABLE` - never as a core failure and never with a fallback computation.

Current execution truth: the capability router activates installed `nli`, `topic` or `review` components lazily; native Markov routes do not request a specialist. At most one DLC model is resident at a time (load/unload swap, `DLCBusy` while a forward is in flight). Missing packs fail closed.

Clean isolated evidence now includes real `review`, `topic` and `nli` decisions through the repository-local specialist worker. Host-native desktop acceptance remains separately scoped as stated above.
