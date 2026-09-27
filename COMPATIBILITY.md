# Compatibility

Current target: Solve Lite `v0.1.10` on macOS arm64.

| Surface | v0.1.10 contract |
|---|---|
| Native decisions | Bundled, hash-verified Lite kernel |
| Specialist decisions | One shared CoreML encoder and four tiny heads |
| Host adapters | Thin adapters for WorkBuddy, Doubao, Codex and Hermes |
| Runtime network | Zero after installation |
| Added ML runtime | Zero; CoreML is provided by macOS |
| Model copies | One shared copy per machine |
| Complete install | 50.932773 MB |

The public ABI is `solve_lite_abi:route_prompt`. A missing or damaged shared asset returns `SPECIALIST_CAPABILITY_UNAVAILABLE`; it never fabricates a specialist answer.

The current installer verifies the immutable Hugging Face revision, archive SHA-256 and unpacked-tree SHA-256 recorded in the GitHub control manifest.

Historical Full Runtime accuracy 92.53% is a reference only. Jev reference is 53.67%.

Peter fresh-host acceptance remains a separate human gate.
