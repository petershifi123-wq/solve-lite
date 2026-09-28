# Compatibility

Current target: Solve Lite `v0.1.11` on macOS arm64.

| Surface | v0.1.11 contract |
|---|---|
| Native decisions | Bundled, hash-verified Lite kernel |
| Specialist decisions | One shared CoreML encoder and four tiny heads |
| Host profiles | 18 registry-driven thin profiles; evidence status retained per host |
| Runtime network | Zero after installation |
| Added ML runtime | Zero; CoreML is provided by macOS |
| Model copies | One shared copy per machine |
| Complete install | 50.932773 MB |

The public ABI is `solve_lite_abi:route_prompt`. A missing or damaged shared asset returns `SPECIALIST_CAPABILITY_UNAVAILABLE`; it never fabricates a specialist answer.

The current installer verifies the immutable Hugging Face revision, archive SHA-256 and unpacked-tree SHA-256 recorded in the GitHub control manifest.

The declared profiles are Claude Code, Cursor, GitHub Copilot, Codex, Windsurf, Gemini CLI, Amp, Goose, Aider, Cline, Roo Code, Trae, Hermes, OpenCode, ChatGPT, WorkBuddy, Doubao and Qwen Code. Declaration means the quick installer has a deterministic destination and portable invocation path. It does not mean every host has passed an ordinary-session native-hook acceptance gate.

All non-empty ordinary messages are required to select one of the frozen 20 scenarios, expose the scenario percentage surface and settle the local reward pool once.

Historical Full Runtime accuracy 92.53% is a reference only. Jev reference is 53.67%.

Peter fresh-host acceptance remains a separate human gate.
