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

**Specialist Runtime** — Optional semantic capabilities using external model packs and ML dependencies.

**Lite 默认运行时**：约 4.6MB，普通 CPU 运行，空闲内存约 24MB，无需 PyTorch、无需模型权重、完全本地运行原生决策能力。

**Specialist 专家运行时** — 可选的语义扩展能力，使用外部模型包与 ML 依赖。

```
BASE LITE (this repository)      = ~4.6MB runtime / native subset / zero model weights / offline
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
  -> optional DLC components, installed on request from this repository's Release
```

Therefore / 因此：

```text
PUBLIC_SELF_CONTAINED_DISTRIBUTION=TRUE            # base Lite: native decisions, offline
CORE_ASSET_ROOT_REQUIRED=FALSE                     # no SOLVE_LITE_CORE_ASSET_ROOT needed
RUNTIME_MODEL_ASSETS=OPTIONAL_DLC_COMPONENTS       # 3 public packs; financial NOT_PUBLIC
SPECIALIST_PACK_REQUIRED_AT_STARTUP=FALSE
```

## Optional Specialist Add-ons / 可选专业能力扩展

**You do not need any add-on to use Solve Lite Lite.**
**无需安装任何扩展包，也可以直接使用 Solve Lite Lite。**

The default Lite Runtime is about 4.6 MB and runs on an ordinary CPU, with no PyTorch, no Transformers and no model weights. Compact Specialist Add-ons are entirely optional extensions for advanced capabilities such as natural-language inference, financial sentiment, knowledge/topic routing and advanced sentiment judgement. Solve Lite never downloads any add-on automatically. When a task needs a specialist capability that is not installed, Solve Lite tells you which add-on is required, its download size and its expected memory usage. Whether to install it is your decision.

默认 Lite Runtime 约 4.6 MB，可直接在普通 CPU 本地运行，无需 PyTorch、Transformers，也无需任何模型权重。Compact Specialist Add-ons 是完全可选的高级能力扩展，用于自然语言推理、金融情绪、知识/主题路由与高级情感判断等能力。Solve Lite 不会自动下载任何扩展包。当某个任务需要尚未安装的专业能力时，Solve Lite 会明确告诉你需要哪个扩展、下载大小与预计内存占用。是否安装，由你决定。

| Add-on (DLC component) | Capability | Download | Installed | Required by Lite |
|---|---|---:|---:|---|
| `solve-lite-review-compact` | Advanced sentiment analysis (review polarity) | 29.17 MB | 29.17 MB | No |
| `solve-lite-topic-compact` | Knowledge / topic routing | 44.32 MB | 44.32 MB | No |
| `solve-lite-nli-compact` | Natural-language inference | 76.35 MB | 158.86 MB | No |

Download sizes are the measured `.tar.gz` sizes in the Release; "installed" is the uncompressed on-disk size. The three public DLC components total **149.84 MB of download**, and installing them together with the base Lite clone lands at roughly **155.6 MB on disk** — the base Lite clone alone is **~5.7 MB**. Base Lite is never described as if it included the DLC components.

Compressed specialist packs use a mixed int4/int3 grouped quantization scheme (see each pack's `addon.json` / the release `addon-index.json`). They reduce download and runtime footprint substantially, but may change some specialist decisions relative to the frozen full-precision reference. Installing a DLC component never executes it: activation is opt-in (`SOLVE_LITE_INT4_DLC=1`), lazy, and keeps at most one model resident.

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

Start small. Add only the intelligence you actually need.
先用最小的版本，只安装你真正需要的智能。

## Install and compatibility / 安装与兼容性

```bash
git clone https://github.com/petershifi123-wq/solve-lite
cd solve-lite
python3 tools/installer.py                  # install: base Lite + the 3 public DLC components
python3 tools/installer.py --skip-dlc       # base Lite only
python3 tools/startup_check.py --json       # may I use it right now? (STARTUP_CHECK=PASS)
python3 tools/doctor.py                     # healthcheck + capability registry
```

Base Lite needs nothing else. Installing DLC components never activates them: activation is opt-in (`SOLVE_LITE_INT4_DLC=1`), lazy, and keeps at most one model resident. With the opt-in switch on, the loader assembles the assetroot view and the installed components serve real specialist decisions; with it off, an installed component is reported as `SPECIALIST_CAPABILITY_UNAVAILABLE` (reason `INT4_BACKEND_NOT_ACTIVATED`).

基础 Lite 不需要任何额外步骤：LITE 运行时随仓库提供，无需设置任何资产根目录变量即可 `healthcheck` 返回 `PASS`，并在离线状态下执行原生决策。安装 DLC 组件不会激活它：激活需要显式选择（`SOLVE_LITE_INT4_DLC=1`），按需延迟加载，最多常驻一个模型；开启后 loader 会组装 asset-root 视图并让已装组件真正给出专家决策，关闭时已装组件仍返回 `SPECIALIST_CAPABILITY_UNAVAILABLE`（原因 `INT4_BACKEND_NOT_ACTIVATED`）。

Layered disclosure / 分层披露：

```text
Lite only            -> ~5.7 MB on disk, no network, native decisions
Lite + all public DLC -> ~187.6 MB on disk, of which 149.84 MB is the DLC download
financial specialist  -> NOT_PUBLIC (not distributed, never counted in a total)
```

Fresh-install compatibility was machine-verified on two isolated host shapes (Doubao, WorkBuddy). That scoped PASS does not claim a native desktop UI hook or full automatic lifecycle support. `PARTIAL` and `NOT_RUN` are never presented as PASS. See [`COMPATIBILITY.md`](COMPATIBILITY.md).

全新安装兼容性已在两个隔离宿主形态（Doubao、WorkBuddy）上通过机器验证；该范围内的 PASS 不代表桌面 UI 钩子或完整自动生命周期已经通过。`PARTIAL` 与 `NOT_RUN` 不会被包装成 PASS。详见 [`COMPATIBILITY.md`](COMPATIBILITY.md)。

Host evidence naming / 宿主证据命名：

```
HOST_SHAPED_FRESH_INSTALL_COMPATIBILITY=PASS
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
