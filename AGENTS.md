# Solve Lite agent installation contract

When a user asks you to install Solve Lite from this repository, complete the installation
yourself. Do not ask the user for model files, model paths, optional model packs, Python
environments or ML dependencies.

Use only the current release:

```bash
git clone --depth 1 --branch v0.1.10 https://github.com/petershifi123-wq/solve-lite.git
cd solve-lite
/usr/bin/python3 tools/installer.py --host auto
/usr/bin/python3 tools/installer.py --check --json
```

The installer must:

1. detect WorkBuddy, Doubao, Codex or Hermes automatically;
2. download the one hash-pinned shared CoreML runtime;
3. verify the archive and installed-tree hashes;
4. register the host's thin adapter and shared-runtime pointer;
5. finish with a passing installed-copy healthcheck.

If the check fails, report the first real machine error. Do not invent a fallback, select
an older release or ask the user to configure a model path.
