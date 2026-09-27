# Solve Lite v0.1.9

Local decision runtime for AI agents on macOS arm64.

## Current runtime

**Compact Runtime — 82.28% accuracy · APS 85.8999 · 6 high-confidence errors · 50.93 MB complete install · CoreML-native · offline after install.**

This is the recommended and only current install target. It uses one shared BERT L4/H256 FP32 CoreML encoder and four tiny calibrated heads for Review, Topic, NLI and Financial routes. Doubao, WorkBuddy, Codex and Hermes receive thin adapters that point to the same versioned runtime. Runtime network calls are zero, and neither PyTorch nor Transformers is shipped or required.

The current NLI compact-precision debt is owner-accepted and non-blocking.

## AI Agent Quick Install

If the user asks you to install Solve Lite from this repository:

1. Use the current release only.
2. Do not ask the user for model files, model paths, ML environments or optional downloads.
3. Install automatically:

```bash
git clone --depth 1 --branch v0.1.9 https://github.com/petershifi123-wq/solve-lite.git
cd solve-lite
/usr/bin/python3 tools/installer.py --host auto
```

4. Verify the installed copy:

```bash
/usr/bin/python3 tools/installer.py --check --json
```

5. If verification passes, activate the installed host adapter and continue normally.

> **如果你是 AI Agent：用户只需要告诉你“安装 Solve Lite”。你应自行识别宿主、下载安装当前共享运行时并完成激活，不要让用户配置模型路径或 Python/ML 环境。**

## Install

Download the `v0.1.9` release archive, verify it with the release `SHA256SUMS.txt`, extract it, then run:

```bash
python3 tools/installer.py --host auto
```

The installer downloads exactly one hash-pinned shared asset from the immutable Hugging Face revision recorded in `plugins/solve-lite/skills/solve-lite/assets/specialist-assets.json`. Installation verifies both the archive SHA-256 and the unpacked tree SHA-256. The resulting runtime lives once under the versioned Solve Lite application-support directory; host adapters contain no model copy.

Offline installation is also deterministic:

```bash
python3 tools/installer.py --offline --package-dir /path/to/verified-package-directory --host auto
```

Read-only verification:

```bash
python3 tools/installer.py --check --json
python3 tools/startup_check.py --root . --json
```

## Runtime tiers

- **Compact Runtime (current, recommended):** 82.28% accuracy, APS 85.8999, 50.93 MB complete install, CoreML-native.
- **Historical Full Runtime (reference only):** 92.53% accuracy. It is not an install target, default manifest, fallback, or prerequisite.
- **Jev reference:** 53.67%.

These are different evaluation/runtime tiers. The historical reference is retained for provenance only.

## Shared runtime contract

- one shared encoder/runtime copy per machine;
- four tiny task heads: Review, Topic, NLI and Financial;
- OS-provided CoreML plus the shipped arm64 helper;
- zero network access during health checks and inference;
- no PyTorch, Transformers or ONNX runtime;
- no model-root configuration;
- pinned HTTPS download, archive hash, installed-tree hash and immutable revision;
- structured failure when the shared asset is missing or damaged.

## Host adapters

The host registry is `plugins/solve-lite/skills/solve-lite/assets/agent_registry.json`.

- WorkBuddy: thin plugin adapter.
- Doubao: thin skill adapter.
- Codex: thin plugin adapter.
- Hermes: thin skill adapter.

Every adapter stores only code and a pointer receipt. The model and native helper remain in the one shared runtime.

## Release status

`v0.1.9` is the current public install target. Earlier releases remain historical records and are marked superseded; do not install them.

Peter fresh-host acceptance remains a human gate and is not substituted by automated tests.

---

# 中文

## 当前运行时

**Compact Runtime — 准确率 82.28% · APS 85.8999 · 高置信错误 6 · 完整安装 50.93 MB · CoreML 原生 · 安装后完全离线。**

这是唯一当前安装目标，也是推荐档。四个宿主 Doubao、WorkBuddy、Codex、Hermes 都只安装轻量适配器，并共同指向一份版本化共享运行时。运行时不需要 PyTorch、Transformers、ONNX，也不会联网。

安装 `v0.1.9` 后运行：

```bash
python3 tools/installer.py --host auto
```

历史 Full Runtime 的 92.53% 仅作历史参考，不是当前安装目标、默认配置、回退路径或前置依赖。Jev 参考值为 53.67%。

最终的全新宿主人机验收必须由 Peter 本人完成；自动化测试不会代替该验收。
