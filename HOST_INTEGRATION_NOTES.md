# Host Integration Notes / 宿主接入须知

This file describes the current `v0.1.10` host contract only.

## One shared runtime

- One versioned CoreML runtime is installed per machine.
- WorkBuddy, Doubao, Codex and Hermes receive thin adapters only.
- Adapters contain code and a `.solve-lite-runtime.json` pointer, never model copies.
- Installation verifies the pinned Hugging Face revision, archive SHA-256 and installed-tree SHA-256.
- Inference is offline and performs zero network calls.

## Automatic host detection

`/usr/bin/python3 tools/installer.py --host auto` resolves the host from an explicit
host marker first, then from the host's normal configuration directory:

| Host | Default evidence |
|---|---|
| Codex | `~/.codex` |
| Hermes | `~/.hermes` |
| WorkBuddy | `~/.workbuddy-ai`, `~/.workbuddy` or `~/.codebuddy` |
| Doubao | `~/Library/Application Support/DoubaoWork` |

An agent must not ask the user for a model path or an ML environment. If automatic
detection cannot identify a supported host, the installer uses the portable generic
skill location and reports that choice in its JSON receipt.

## Hook lifecycle

- Some hosts reload hooks immediately; others snapshot hooks at startup.
- Registration must be followed by `tools/hook_selftest.py` and installed-copy verification.
- A host that snapshots hooks may require its normal restart or its own hook reload command.
- Every hook command must fail open so a missing adapter never blocks the user's prompt.
- WorkBuddy resolves `CODEBUDDY_PLUGIN_ROOT` or `CLAUDE_PLUGIN_ROOT`; Codex resolves
  `PLUGIN_ROOT`. Never write a developer-machine absolute path into a public manifest.

## Acceptance

Installation PASS requires all of the following:

1. the pinned shared runtime is downloaded and hash-verified;
2. the installed tree matches its expected hash;
3. exactly one shared encoder copy exists;
4. the selected thin adapter is registered and its pointer resolves;
5. healthcheck and a real route invocation pass;
6. inference reports zero network calls and no extra ML runtime.

Process existence, copied files or a successful download alone are not product PASS.
Peter fresh-host acceptance remains a separate human gate.
