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
2.33GB specialist assets = OPTIONAL
                         = NOT REQUIRED FOR LITE
Lite  = 4.6MB / native subset / zero model weights
Full  = 20 workflows / specialist expansion / 92.53% / 3–0 / ~34x
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

The public repository contains the source-available integration layer, Universal Adapter, public ABI/loader, tests, checksums and documentation. The local closed Core is distributed separately.

公开仓库包含源码可见的集成层、Universal Adapter、公共 ABI/loader、测试、校验和与文档。本地封闭 Core 单独分发。

**Native Core binaries only. Model runtime assets are not redistributed and must be supplied separately.**

**Core Release 只包含原生二进制。模型运行资产不再分发，必须由用户或 Owner 独立提供。**

The 2.33GB specialist assets are **OPTIONAL · NOT REQUIRED FOR LITE**.

2.33GB 专家资产为 **OPTIONAL · NOT REQUIRED FOR LITE**（可选，Lite 运行时不需要）。

The five runtime model directories are `EXTERNAL_REQUIRED`, are not in GitHub or Release assets, and are never auto-downloaded. Missing or mismatched runtime assets fail closed with `CORE_ASSET_UNAVAILABLE`; there is no fallback computation.

五个运行时模型目录属于 `EXTERNAL_REQUIRED`，不会进入 GitHub 或 Release，也不会自动下载。缺失或哈希不匹配时以 `CORE_ASSET_UNAVAILABLE` 关闭失败，不执行替代计算。

```text
Public repository
  -> host adapter
  -> public route_prompt ABI
  -> separately supplied native Core
  -> separately supplied owner/BYO runtime model assets
```

Therefore / 因此：

```text
PUBLIC_SELF_CONTAINED_DISTRIBUTION=FALSE
RUNTIME_MODEL_ASSETS=EXTERNAL_REQUIRED
MODEL_ASSETS=BYO_OR_OWNER_SUPPLIED
```

## Install and compatibility / 安装与兼容性

Run the read-only package doctor before any installation:

```bash
python3 tools/doctor.py --repo .
```

The installer defaults to dry-run. Clean-host public ABI routing is machine-verified for Codex, Hermes, Doubao, and WorkBuddy. This scoped PASS does not claim a native desktop UI hook or full automatic lifecycle support. `PARTIAL` and `NOT_RUN` are never presented as PASS. See [`COMPATIBILITY.md`](COMPATIBILITY.md).

安装器默认 dry-run。Codex、Hermes、豆包与 WorkBuddy 的 clean-host 公共 ABI 路由已通过机器验证；该范围内的 PASS 不代表桌面 UI 钩子或完整自动生命周期已经通过。`PARTIAL` 与 `NOT_RUN` 不会被包装成 PASS。详见 [`COMPATIBILITY.md`](COMPATIBILITY.md)。

Host evidence naming / 宿主证据命名：

```
HOST_SHAPED_COLD_INSTALL_COMPATIBILITY=PASS
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
