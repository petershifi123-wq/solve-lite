# Compatibility Snapshot

This snapshot reports only the capability proven by machine evidence. A fresh-install public ABI PASS does not claim a native desktop UI hook, automatic installer lifecycle, or full host-product support.

| Surface | Version | Status |
|---|---|---|
| Solve Lite public plugin | 0.1.6 | FRESH_INSTALL_ACCEPTANCE_PASS |
| LITE runtime (bundled, 8 native modules) | LITE build lot | PASS_VERIFIED_BUNDLED_RUNTIME |
| Full-precision core manifest | v2 (historical) | HISTORICAL_REFERENCE_ONLY |
| DLC components (review, topic, nli) | 0.1.5 packages | INSTALL_VERIFIED_OPT_IN_ACTIVATION |
| Financial specialist DLC | not published | NOT_PUBLIC |
| Doubao | fresh isolated host shape | PASS_VERIFIED_FRESH_INSTALL_PUBLIC_ABI |
| WorkBuddy | fresh isolated host shape | PASS_VERIFIED_FRESH_INSTALL_PUBLIC_ABI |
| Codex | prior scope | PASS_VERIFIED_PUBLIC_ABI_PRIOR_SCOPE |
| Hermes | prior scope | PASS_VERIFIED_PUBLIC_ABI_PRIOR_SCOPE |
| Cline | not rerun in this gate | PARTIAL_FROZEN |
| Qwen | not rerun in this gate | PARTIAL_FROZEN |
| Cursor | not run | NOT_RUN |
| macOS | 27.0 arm64 | TESTED |
| Python | 3.9.6 | TESTED |

The two fresh isolated hosts each started from a clean copy of the public tree and passed: bundled-runtime healthcheck `PASS` with no asset root configured, one real offline native decision, clean `SPECIALIST_CAPABILITY_UNAVAILABLE` for a specialist case, verified installation of the three public DLC components, opt-in lazy activation left off, and byte-identical frozen kernel modules. Network attempts during runtime, credential reads, and Jev API calls were zero. Codex and Hermes were verified earlier under the owner-runtime scope and are not re-claimed here.

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

Distribution truth: `PUBLIC_SELF_CONTAINED_DISTRIBUTION=TRUE` for base Lite (bundled LITE runtime, no asset root required). Specialist model assets are `OPTIONAL_DLC_COMPONENTS`: the three public packs come only from this repository's Release, the financial pair is `NOT_PUBLIC`, nothing is auto-downloaded, and a missing pack is reported as `SPECIALIST_CAPABILITY_UNAVAILABLE` - never as a core failure and never with a fallback computation.

Round-3 execution truth: with the opt-in backend active (`SOLVE_LITE_INT4_DLC=1`), `nli` and `topic` execute real specialist decisions on an isolated install; at most one DLC model is resident at a time (load/unload swap, `DLCBusy` while a forward is in flight), and with the switch off an installed component still answers `SPECIALIST_CAPABILITY_UNAVAILABLE` (reason `INT4_BACKEND_NOT_ACTIVATED`).

Known limitation (measured): the `review` component's route is admitted by the case-schema check but its sealed adapter then refuses with `adapter support dimension does not match public schema`. That route is refused cleanly (no fallback, no fabricated answer) pending a VV ruling on the intended review schema.
