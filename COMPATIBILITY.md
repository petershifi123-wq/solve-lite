# Compatibility Snapshot

This snapshot reports only the capability proven by machine evidence. A clean-host public ABI PASS does not claim a native desktop UI hook, automatic installer lifecycle, or full host-product support.

| Surface | Version | Status |
|---|---|---|
| Solve Lite public plugin | 0.1.5 | OFFLINE_HARNESS_PASS |
| Native Core | 0.1.3 | UNCHANGED_EXTERNAL_ASSET |
| Codex | clean-host fork | PASS_VERIFIED_CLEAN_HOST_PUBLIC_ABI |
| Hermes | clean-host fork | PASS_VERIFIED_CLEAN_HOST_PUBLIC_ABI |
| Doubao | clean-host fork | PASS_VERIFIED_CLEAN_HOST_PUBLIC_ABI |
| WorkBuddy | clean-host fork | PASS_VERIFIED_CLEAN_HOST_PUBLIC_ABI |
| Cline | not rerun in this gate | PARTIAL_FROZEN |
| Qwen | not rerun in this gate | PARTIAL_FROZEN |
| Cursor | not run | NOT_RUN |
| macOS | 27.0 arm64 | TESTED |
| Python | 3.9.6 | TESTED |

The four verified forks each passed public repository installation, sealed Owner runtime injection, runtime hash verification, host detection, and one real local invocation. Existing private host state participation, network attempts, credential reads, and Jev API calls were all zero.

Evidence identity:

- Public commit under test: `08814674c0a07c7efc1f90fc48100d64a5e6d04d`
- Native Core archive: `882dcfe4b0de0d08cf2511772e5e86ae530ccd568d240fde82e6c6eda5785c3e`
- Owner runtime tree: `62326a7600b3cc568ba0bd1cb39121510c491a6522e10bd746bc239b782f84a0`
- Four-host receipt: `64a94a211bb52cf463bd868eda5adda7efd82500921ddf0e0b14d4285eedeef8`

Host evidence naming / 宿主证据命名:

```
HOST_SHAPED_COLD_INSTALL_COMPATIBILITY=PASS
NATIVE_DESKTOP_PROCESS_INTEGRATION=NOT_RUN
FULL_UI_LIFECYCLE=NOT_CLAIMED
```

`PUBLIC_SELF_CONTAINED_DISTRIBUTION=FALSE` remains unchanged. Model assets are external and must be supplied by the user or Owner. Missing or mismatched assets fail closed.
