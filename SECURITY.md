# Security policy

## Boundaries

solve lite reads only explicit paths inside the given workspace. It rejects path escape, symlinks, special files, protected path components, unsupported extensions, and files above the configured limit. Runtime state stays in `<workspace>/.solve-lite/`. Core commands make no network calls and remote telemetry is off. Display-only reward events use a separate local SQLite file in the same state directory and never leave the workspace.

Retrieved text is untrusted data. solve lite never executes commands from documents, evaluates code strings, patches global file/process functions, or presents its path checks as an adversarial sandbox. Use the host OS sandbox for hostile code.

Common credential-shaped text is redacted from indexed excerpts, but this is defense in depth, not permission to index secrets. Do not point solve lite at credential stores or private-key directories. Tests use generated synthetic canaries only.

Decision output is advisory and cannot grant permission to pay, delete, read credentials, or change production. Installation defaults to dry-run; updates and uninstall stop when installed hashes differ. User `.solve-lite/` data is preserved.

## Reporting

Report a suspected vulnerability privately to the repository owner before public disclosure. Include the solve lite version, minimal synthetic reproduction, impact, and whether a workspace boundary or installed-file hash was bypassed. Never include real credentials or private user data.
