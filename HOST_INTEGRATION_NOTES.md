# Host Integration Notes / 宿主接入须知

本文件只记录**真机实测**得到的宿主契约与坑位，供所有宿主接入前阅读。

## 0 通用结论

- **hook 是热读取的**：注册完成后当轮即生效，**不需要重启宿主**。
  （实测：WorkBuddy 07:20 注册完，当轮就跑了 hook，容器里也有对应写入记录。）
  不要再把"重启才生效"当作结论。
- **安装后必须自证 hook 真的跑过**（见 `tools/hook_selftest.py`）：写入探针 → 断言注入 → `HOOK_FIRED=PASS`。

## 1 \${PLUGIN_ROOT} 不保证展开（WorkBuddy 实测不展开）

`hooks/hooks.json` 里的 `command` 若写成 `python3 "${PLUGIN_ROOT}/hooks/user_prompt_submit.py"`，
在不展开该变量的宿主里会直接执行失败 → 用户看到"Solve Lite 没激活"。

处置：
- 安装器必须提供**绝对路径注册**（把解析后的真实路径写进宿主配置）。
- 同时提供 `hooks/hooks.absolute.example.json` 作为模板（占位 `__PLUGIN_ROOT__`）。
- 不要在文档里假设所有宿主都支持变量展开。

## 2 不要用"聚合状态"当可见性闸门（永久静默）

上游曾用 `if specialist.status != AVAILABLE: 静默返回`。后果：**干净安装（无 DLC / 未激活）时，
每一个 prompt 都静默** → 宿主与用户都以为"solve-lite 未激活"。

处置（已在 `hooks/user_prompt_submit.py` 修复，commit 236dc411）：
- 成功路径：注入完整决策契约；
- 降级路径：**也必须注入**一句可见的 Base Lite 状态行（说明未调用专家扩展），
  只有 Core 自身损坏才允许静默，且要写日志。

## 3 目录创建要容忍 EEXIST / EPERM / 只读挂载

沙箱宿主常见：`mkdir` 抛 `EEXIST`，或目标目录只读。
处置：所有写目录使用 `exist_ok=True` + 失败回退（symlink 失败 → copy；copy 失败 → 报明确错误），
**绝不因为目录问题静默**。

## 4 依赖探测不要用 `python3 -s`

`-s` 会禁用用户 site-packages，导致 torch/transformers 明明可用却被判 `MODULE_MISSING`（假阴性）。
处置：宿主面向的依赖检查禁用 `-s`；需要隔离时显式传入 site-packages 路径并记录。

## 5 专家库（DLC）快速启动

- **安装即预组装** asset-root 视图并缓存 → 首次 specialist 调用不现组装。
- 运行期策略不变：`max_resident_dlc=1`、`preload_at_startup=false`、idle 卸载、`DLCBusy` 保留。
- 期望：Lite-only 路径 <200ms；专家首次调用应在数秒内（实测值以 `evidence/` 内报表为准）。

## 6 逐宿主状态（只写机器证据支持的范围）

| 宿主 | 形态 | 状态 |
|---|---|---|
| Codex | plugin + hook 契约 | PASS_VERIFIED_CLEAN_HOST_PUBLIC_ABI |
| Hermes | plugin + hook 契约 | PASS_VERIFIED_CLEAN_HOST_PUBLIC_ABI |
| WorkBuddy | hook 契约不展开变量 · 热读取 | 已按本文件整改，真机复测由 Owner 执行 |
| Doubao | prompt hook | 同上 |

`PARTIAL` 与 `NOT_RUN` 永不写成 PASS。
