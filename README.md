# Solve Lite

**Local System-One decisions on an ordinary CPU. No paid remote decision API required.**

**本地 System-One 决策运行时。普通 CPU 即可运行，无需专用付费远程决策 API。**

**Lite Runtime: ~4.6MB · CPU-only · ~24MB idle RAM · no PyTorch · no model weights · offline native decisions.**

**Full Runtime: 92.53% accuracy vs Jev 53.67% · 3–0 across three frozen benchmark rounds · 1,500 cases / 7,500 decisions · ~34× current validated latency.**

**Lite 默认运行时：约 4.6MB · 普通 CPU · 空闲内存约 24MB · 无需 PyTorch · 无需模型权重 · 本地离线原生决策能力。**

**Full 完整运行时：准确率 92.53% vs Jev 53.67% · 三轮冻结测试 3:0 · 1,500 个案例 / 7,500 次决策 · 当前验证版本实测约 34 倍延迟差异。**

Solve Lite is a CPU-first local decision runtime for AI agents. It provides 20 decision workflows through one frozen local Core and replaceable host adapters. Decisions, visible confidence, truthful token reporting and the local Reward ledger stay on the user's machine.

Solve Lite 是面向 AI Agent 的 CPU 优先本地决策运行时。它通过一个冻结的本地 Core 和可替换的宿主适配器提供 20 类决策工作流。决策、可见置信度、如实 Token 记录和本地奖励池均保留在用户设备上。

## Lite Runtime and Specialist Runtime / 轻量运行时与专家运行时

**Lite Runtime** — ~4.6MB · CPU-only · ~24MB idle RAM · No PyTorch · No model weights · Offline native decision runtime.

**Specialist Runtime** — Semantic capabilities in an installer-managed, repository-local Python environment. No global PyTorch/Transformers install is required.

**Lite 默认运行时**：约 4.6MB，普通 CPU 运行，空闲内存约 24MB，无需 PyTorch、无需模型权重、完全本地运行原生决策能力。

**Specialist 专家运行时** — 由安装器管理的仓库内隔离 Python 环境；用户无需预装全局 PyTorch/Transformers。

```
BASE LITE (this repository)      = ~4.6MB runtime / native subset / zero model weights / offline
SHARED SPECIALIST RUNTIME        = repo-local pinned Python 3.9 venv / separate size class
DLC COMPONENTS (optional)        = review 29.17MB + topic 44.32MB + nli 76.35MB download
                                 = 149.84MB extra download on top of the ~5.7MB clone
financial specialist DLC         = NOT_PUBLIC (licence chain unresolved, not distributed)
```

## Why Solve Lite / 为什么使用 Solve Lite

- **Local CPU / 本地 CPU** — routine decision work does not require a paid remote decision service.
- **One frozen Core / 单一冻结核心** — every adapter routes to the same decision authority.
- **Replaceable adapters / 可替换适配器** — host integration can change without changing Core semantics.
- **20 decision workflows / 20 类决策工作流** — including Noul, Choice, Score, routing, filtering, verification and sequential decisions.
- **Visible confidence / 可见置信度** — probability output follows the decision structure instead of inventing one universal percentage.
- **Truthful Token and Reward / 如实 Token 与奖励池** — token reduction appears only when real packing occurs; Reward events settle locally.
- **No paid remote decision API / 无付费远程决策 API** — the decision path is local and offline once authorized runtime assets are supplied.

## Frozen benchmark / 冻结测试

Three independently frozen rounds covered **1,500 cases and 7,500 decisions**. No post-result tuning, retry-to-improve, Jev source code, Jev model weights, Jev training data or Jev output distillation was used.

三轮独立冻结测试覆盖 **1,500 个案例、7,500 次决策**。没有赛后调参，没有为提高分数而重试，也没有使用 Jev 源码、模型权重、训练数据或输出蒸馏。

| Metric / 指标 | Solve Lite | Jev |
|---|---:|---:|
| Accuracy / 准确率 | **92.53%** | 53.67% |
| APS / 概率综合得分 | **92.72** | 65.84 |
| Wrong answers at ≥90% confidence / ≥90% 置信度错答 | **6** | 282 |
| Mean latency / 平均延迟 | **40.77 ms** | 1388.33 ms |
| P50 latency / P50 延迟 | **40.91 ms** | 1188.91 ms |
| P95 latency / P95 延迟 | **77.38 ms** | 2847.72 ms |

**Series result / 系列结果：Solve Lite 3–0 Jev**

**Qualified speed comparison / 限定口径速度对比：~34×**

The latency comparison is **Solve Lite local CPU decision-path execution vs Jev official remote API end-to-end latency**. It is not a claim that every workload or hardware combination is 34× faster. The earlier frozen figures (mean 32.46 ms, ~42.8×) are retained as `HISTORICAL_FROZEN_RESULT` and are no longer the headline claim.

延迟对比口径为 **Solve Lite 本地 CPU 决策路径执行时间 vs Jev 官方远程 API 端到端延迟**。这不是“所有工作负载、所有硬件均快 34 倍”的泛化承诺。

## Decision UI and local settlement / 决策显示与本地结算

Solve Lite exposes structures that match the task:

- **Noul** — yes / no probability.
- **Choice** — candidate distribution totaling 100%.
- **Score** — ordered score distribution.
- **Independent Risk** — independent signals that do not have to total 100%.

When evidence is insufficient, the result says so instead of fabricating precision. A user-visible result may include the final local inference duration, Reward delta and cumulative ledger total. Token reduction is shown only when measured context packing actually occurred; otherwise it reports zero or no compressible context.

Solve Lite 会按任务结构显示 Noul、Choice、Score 与独立风险概率。证据不足时会明确说明，不为了界面好看而伪造精度。用户可见结果可显示最后一次本地推理耗时、奖励增量与累计奖励；只有真实发生上下文压缩时才显示实测 Token 缩减，否则如实显示为零或无可压缩上下文。

## Architecture and distribution truth / 架构与分发真值

The public repository contains the source-available integration layer, Universal Adapter, public ABI/loader, the LITE native kernel (8 modules), tests, checksums and documentation. A plain clone is complete: base Lite installs nothing and needs no external asset root.

公开仓库包含源码可见的集成层、Universal Adapter、公共 ABI/loader、LITE 原生内核（8 个模块）、测试、校验和与文档。克隆即完整：基础 Lite 不需安装任何东西，也不需要任何外部资产根目录。

**Base Lite is self-contained. Specialist model assets are redistributed only as the three public DLC component packages attached to this repository's Release.**

**基础 Lite 自带完整运行时。专家模型资产仅以三个公开 DLC 组件包的形式随本仓库 Release 分发。**

The 2.33GB full-precision specialist directory tree belongs to the **HISTORICAL FULL-PRECISION REFERENCE** (`CORE_ASSET_MANIFEST_FULL_FP_REFERENCE.json`). It is **not** an install requirement, it is **not** needed by base Lite, and nothing asks you to supply it.

2.33GB 全精度专家目录树属于 **历史全精度参考**（`CORE_ASSET_MANIFEST_FULL_FP_REFERENCE.json`）。它不是安装要求、基础 Lite 不需要它，也不会有人要求你提供它。

Base Lite needs no model directory at all. The three public DLC components install into the repository's own DLC area (`runtime/addons/solve-lite-int4-dlc/`) from the Release. A capability whose pack is absent is reported as `SPECIALIST_CAPABILITY_UNAVAILABLE` with the exact missing directories; `CORE_ASSET_UNAVAILABLE` is reserved for a genuinely broken native core (missing module or hash mismatch). There is never a fallback computation.

```text
Public repository
  -> host adapter (or hooks/user_prompt_submit.py)
  -> public route_prompt ABI
  -> bundled LITE native Core (hash-verified by CORE_ASSET_MANIFEST.json)
  -> public DLC components, installed by default from this repository's Release
     and loaded only when the capability router selects them
```

Therefore / 因此：

```text
PUBLIC_SELF_CONTAINED_DISTRIBUTION=TRUE            # base Lite: native decisions, offline
CORE_ASSET_ROOT_REQUIRED=FALSE                     # no SOLVE_LITE_CORE_ASSET_ROOT needed
RUNTIME_MODEL_ASSETS=SEPARATE_PUBLIC_DLC_LAYER     # 3 default-installed packs; financial NOT_PUBLIC
SPECIALIST_PACK_REQUIRED_AT_STARTUP=FALSE
```

## Specialist DLC layer / 专业能力 DLC 层

**Core remains a separate ~4.6 MB layer; a normal public install also installs Review, Topic and NLI.**
**Core 仍是独立的约 4.6 MB 基座；普通公开安装会同时安装 Review、Topic 和 NLI。**

The Lite Core is about 4.6 MB and runs on an ordinary CPU, with no PyTorch, no Transformers and no model weights. Normal installation creates a repository-local Python 3.9 virtual environment, installs a hash-locked specialist dependency set there, and downloads the three public specialist packages. It never runs system/global `pip`. If no compatible Python 3.9 exists, the installer fetches one pinned arm64 macOS build and verifies its SHA-256 before use. Specialist code remains dormant at Lite startup. The existing capability router starts the isolated worker only for the selected capability, loads only that DLC, and keeps at most one model resident. Financial assets remain `NOT_PUBLIC`. If a required runtime or pack is absent or damaged, Solve Lite fails closed and identifies it; there is no fabricated fallback.

基础 Lite Core 约 4.6 MB，可在普通 CPU 本地运行，无需 PyTorch、Transformers 或模型权重。普通安装会在仓库内创建隔离的 Python 3.9 venv，按哈希锁文件安装专业依赖，并下载三个公开专业包；不会调用系统或全局 `pip`。如果机器没有兼容的 Python 3.9，安装器会下载固定版本的 macOS arm64 Python 并先校验 SHA-256。Lite 启动不会拉起专家环境；只有 capability router 命中时才启动隔离 worker、加载对应 DLC，且最多常驻一个。金融资产继续为 `NOT_PUBLIC`。必需运行时或模型包缺失、损坏时会明确失败，不会伪造回退答案。

| Add-on (DLC component) | Capability | Download | Installed | Normal install |
|---|---|---:|---:|---|
| `solve-lite-review-compact` | Advanced sentiment analysis (review polarity) | 29.17 MB | 29.17 MB | Included |
| `solve-lite-topic-compact` | Knowledge / topic routing | 44.32 MB | 44.32 MB | Included |
| `solve-lite-nli-compact` | Natural-language inference | 76.35 MB | 158.86 MB | Included |

Download sizes are the measured `.tar.gz` sizes in the Release; "installed" is the uncompressed on-disk size. The three public DLC archives total **149.84 MB of download**. The verified default complete installed copy — Base Lite, isolated specialist Python environment and all three DLC components — is **678.67 MB logical on disk (647.23 MiB)**; the base Lite clone alone is **~5.7 MB**. Base Lite is never described as if it included the DLC components.

三个公开 DLC 压缩包合计下载 **149.84 MB**；包含 Base Lite、隔离专家 Python 环境和三个 DLC 的默认完整安装副本，实测逻辑占用为 **678.67 MB（647.23 MiB）**。约 **5.7 MB** 只代表 Base Lite 仓库本体。

Compressed specialist packs use a mixed int4/int3 grouped quantization scheme (see each pack's `addon.json` / the release `addon-index.json`). They reduce download and runtime footprint substantially, but may change some specialist decisions relative to the frozen full-precision reference. Installation does not preload them: the capability router activates the required component lazily and keeps at most one model resident.

量化版专业能力包采用 int4/int3 混合分组量化（见各包 `addon.json` 与 release 的 `addon-index.json`）。它显著降低下载与运行资源占用，但可能导致部分专业判断发生变化。

**Decision agreement vs. the frozen full-precision specialist reference (1,500 frozen decisions per capability):**

| Add-on | Decision agreement |
|---|---:|
| Review | 97.47% |
| Topic | 99.13% |
| NLI | 95.93% |

Quantization reduces download and runtime footprint but may change some specialist decisions.

相对于冻结的全精度专业能力参考版本，当前量化扩展的决策一致率：Review 97.47%、Topic 99.13%、NLI 95.93%。量化显著降低下载与运行资源占用，但可能导致部分专业判断发生变化。

Financial sentiment specialist assets are **not** redistributed: their licence chain is unresolved, so they stay in an engineering-verification-only state and are excluded from all public packages and releases.

金融情绪方向的专家资产**不再分发**：其许可链尚未澄清，因此仅保留工程验证状态，不进入任何公开包与 Release。

Install once; load only the intelligence the current task needs.
一次安装，运行时只加载当前任务需要的能力。

## Install and compatibility / 安装与兼容性

```bash
git clone https://github.com/petershifi123-wq/solve-lite
cd solve-lite
python3 tools/installer.py                  # install: base Lite + the 3 public DLC components
python3 tools/startup_check.py --json       # may I use it right now? (STARTUP_CHECK=PASS)
python3 tools/doctor.py                     # healthcheck + capability registry
```

Base Lite needs no asset-root configuration. Normal installation includes all three public DLC components, but does not preload them. The capability router selects and lazily activates only the component needed by the current case and keeps at most one model resident. Native Markov cases do not load a specialist. A missing required component is reported as `SPECIALIST_CAPABILITY_UNAVAILABLE`; arbitrary bounded natural-language questions route to NLI instead of being translated into invented Markov schemas.

基础 Lite 不需要资产根目录配置。普通安装默认包含三个公开 DLC，但不会预加载。capability router 只在当前 case 需要时懒激活相应组件，最多常驻一个；原生 Markov case 不加载专家模型。必需组件缺失时返回 `SPECIALIST_CAPABILITY_UNAVAILABLE`；有边界的自然语言问题交给 NLI，不会伪造 prompt→Markov 映射。

Layered disclosure / 分层披露：

```text
Lite only            -> ~5.7 MB on disk, no network, native decisions
v0.1.7 code archive   -> 2.38 MB tar.gz / 2.44 MB zip (measured release artifacts)
3 public DLC archives -> 149.84 MB total download
Default full install  -> 678.67 MB logical on disk (647.23 MiB), including the isolated runtime + 3 DLC
financial specialist  -> NOT_PUBLIC (not distributed, never counted in a total)
```

The complete-install figure is a 2026-09-27 isolated-destination measurement of
18,110 installed file/symlink entries. The release code archive, compressed DLC
downloads, and post-install isolated Python environment are different layers;
the ~4.6 MB native Core figure describes only Core and is never presented as the
size of the default full install.

完整安装数字来自 2026-09-27 的隔离目标目录实测，共 18,110 个文件/符号链接条目。
发布代码压缩包、三个 DLC 下载包、安装后的隔离 Python 环境属于不同层；约 4.6 MB
只代表原生 Core，不能冒充默认完整安装的磁盘占用。

Fresh-install compatibility was machine-verified on two isolated host shapes (Doubao, WorkBuddy). P1 adds deterministic host activation: the installer registers a real `UserPromptSubmit` hook in the host's own writable config, and that exact registered command is then replayed with a host-shaped payload to prove it fires and injects. The desktop UI process itself was not driven with a human prompt, so `NATIVE_DESKTOP_PROCESS_INTEGRATION` stays `NOT_RUN`. Doubao Work exposes no local hook API, so the installer writes the skill plus a mandatory first-step banner into the host workspace and reports `UNAVAILABLE_NO_HOST_HOOK_API` instead of pretending. `PARTIAL` and `NOT_RUN` are never presented as PASS. See [`COMPATIBILITY.md`](COMPATIBILITY.md).

全新安装兼容性已在两个隔离宿主形态（Doubao、WorkBuddy）上通过机器验证；P1 进一步做到确定性宿主激活：安装器把真正的 `UserPromptSubmit` 钩子注册进宿主自己可写的配置，并用宿主形态的载荷回放该命令，证明钩子确实触发并注入。桌面 UI 进程本身没有被人手输入驱动过，因此 `NATIVE_DESKTOP_PROCESS_INTEGRATION` 仍为 `NOT_RUN`。豆包办公没有本地钩子 API，安装器改为把技能与「第一步必跑」硬约束写入宿主工作区，并如实报告 `UNAVAILABLE_NO_HOST_HOOK_API`。`PARTIAL` 与 `NOT_RUN` 不会被包装成 PASS。详见 [`COMPATIBILITY.md`](COMPATIBILITY.md)。

Unconditional activation / 无条件激活：

```bash
python3 tools/installer.py --host auto          # register the hook in the host config (idempotent, backs up)
bash install_workbuddy.command                  # double-click install: register + self-test + startup check (no sudo)
bash install_doubao.command
python3 tools/hook_selftest.py --host all --json # HOOK_FIRED=PASS/FAIL plus dispatch, ledger and latency evidence
```

The hook runs the bundled LITE layer on **every** prompt (milliseconds, no torch, no DLC) and injects what it actually measured; the model has no "activate or not" choice. When the LITE layer produced no prompt-level decision the injected receipt says exactly that and forbids inventing Choice/Token/reward lines. With an installed DLC component the same per-prompt step returns a real specialist decision.

Host evidence naming / 宿主证据命名：

```
HOST_SHAPED_FRESH_INSTALL_COMPATIBILITY=PASS
HOST_HOOK_REGISTRATION=PASS (workbuddy) / UNAVAILABLE_NO_HOST_HOOK_API (doubao)
HOST_HOOK_DISPATCH_REPLAY=PASS
UNCONDITIONAL_ACTIVATION=PASS
NATIVE_DESKTOP_PROCESS_INTEGRATION=NOT_RUN
FULL_UI_LIFECYCLE=NOT_CLAIMED
```


## Independent implementation / 完全独立实现

Solve Lite does not use Jev source code, model weights, training data, output distillation or proprietary implementation. Jev is used only as an external benchmark reference. Solve Lite is not affiliated with or endorsed by Jev or TypeSafe AI.

Solve Lite 没有使用 Jev 源码、模型权重、训练数据、输出蒸馏或私有实现。Jev 仅作为外部 Benchmark 对照对象。Solve Lite 与 Jev、TypeSafe AI 无隶属、合作或官方背书关系。

## License and release status / 许可与发布状态

The public integration layer is released under the **Soulite Magic Source-Available Non-Commercial Research License 1.0**. Personal study, academic research, technical evaluation and non-commercial experimentation are permitted under [`LICENSE`](LICENSE). Commercial use requires a separate written license from Soulite Magic. Third-party components remain governed by their own licenses.

公开集成层采用 **Soulite Magic Source-Available Non-Commercial Research License 1.0**。个人学习、学术研究、技术评估与非商业实验依照 [`LICENSE`](LICENSE) 获得许可；商业使用需要 Soulite Magic 单独书面授权。第三方组件仍受各自许可证约束。

**Experimental research release. No maintenance SLA, no guaranteed roadmap, best-effort support only.**

**实验性研究发布，不承诺长期维护、版本路线或兼容性支持。**

## Project and creators / 项目与创作者

- **Soulite Magic｜灵智天成** — Research, architecture and engineering / 研究、架构与工程
- **Andrew Yang** — AI Agent education and public communication / AI Agent 普及与公共传播
- **Douyin / 抖音：UPAI - 升级你的 AI 能力**

## Support the project / 支持项目

**编程不易，欢迎打赏。**

![Alipay donation QR code / 支付宝打赏二维码](assets/alipay-donation.jpg)

---

> Let GPUs solve the hard problems. Give everyday intelligence back to the CPU.
>
> 让 GPU 解决真正困难的问题，把日常决策智能交还给 CPU。
