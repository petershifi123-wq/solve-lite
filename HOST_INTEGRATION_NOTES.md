# Host Integration Notes / 宿主接入须知

本文件只记录**真机实测**得到的宿主契约与坑位，供所有宿主接入前阅读。

## 0 通用结论（含一条重要更正）

- **hook 生效时机是【宿主相关】的，不要一概而论**：
  - 有的宿主热读取：注册后当轮即生效（我们实测过这种情形）。
  - 有的宿主**在启动时对 hooks 做快照**，外部改动需**重启宿主**，或在宿主自身的
    `/hooks` 菜单里复核并应用后才生效（WorkBuddy 反馈，并给出官方文档依据）。
  → 接入结论：**安装器必须同时走两条路**：(1) 注册后立刻用 `tools/hook_selftest.py` 自证；
  (2) 自证失败时提示用户"重启宿主 / 在 /hooks 菜单里应用"，并给出可复制的一步命令。
  两种情形都要有明确指引，禁止把任何一种当成普适真理。
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

## 7 性能与噪音（WorkBuddy 实测，重要）

- **无条件成本**：hook 每次新起一个进程并加载模型 ≈ **2.1 秒/次提问**。这不可接受。
  处置：改为**常驻热进程**（安装时启动，约定 socket/管道，宿主调用只做一次轻量往返），
  目标 Lite-only 路径 **<200ms**；进程不在时回退到冷路径但**必须有超时与降级**，绝不卡宿主。
- **footer 呈现规则（产品需求，勿误删）**：
  - **决策百分比与奖励池结算必须呈现**（`+分 | 累计 | 🔒 本地`）——这是产品需求，不得砍掉。
  - **Token 行是条件呈现**：产品规则为"只有真实发生上下文压缩时才显示"，
    因此无压缩时**只省略 Token 行**，而不是省略整个结算。
  - 百分比优先使用 `raw_support` 并标注 `support_semantics`（部分问题校准概率退化，
    如 33.3×3；实测同一问题 raw_support 给出 neutral 93%）。
- **概率退化**：某些"不确定"类问题校准概率呈退化（如 33.3×3），而 `raw_support` 才有信息量
  （实测：某题 raw_support 给出 neutral 93%）。
  处置：呈现优先使用 `raw_support` 并**显式标注口径**（`support_semantics`），
  不得把退化概率当作结论展示。
- **注入策略**：路由判定为无信息（neutral / 无有界决策）时**默认不注入**，避免打扰；
  需要审计时开 verbose。

## 8. Hook 绝不能阻塞宿主（P0 事故规则，2026-09-27 实测）

真实事故：WorkBuddy 执行了 plugin 层 `hooks.json` 里写死 `${PLUGIN_ROOT}` 的命令；该宿主不展开
该变量 → 命令变成 `/hooks/user_prompt_submit.py` → python3 报 Errno 2 → **宿主直接 block 了
用户的 prompt**（用户当场无法使用）。

硬规则：

1. **hook 命令必须无条件 `exit 0`**：找不到脚本、缺依赖、超时，一律静默成功。绝不能让上游
   把 hook 失败当成"拒绝本次用户输入"。推荐写法：

   ```sh
   sh -c 'D=${PLUGIN_ROOT:-$PWD}; F=$D/hooks/user_prompt_submit.py; \
          [ -f "$F" ] || F=$PWD/hooks/user_prompt_submit.py; \
          if [ -f "$F" ]; then exec /usr/bin/python3 "$F"; fi; exit 0'
   ```

2. **不把依赖变量展开的命令写进宿主配置**：不展开变量的宿主（WorkBuddy 实测）必须由 installer
   写**绝对路径**（`tools/host_hooks.py` 已如此）；plugin 层 `hooks.json` 只保留上面的 fail-safe 形式。
3. **注册后立刻自证**：`python3 tools/hook_selftest.py --host auto`；并人工做一次负向测试
   （把路径故意改坏 → hook 仍返回 0 且宿主不 block）。
4. **两条命令别同时"活着"**：宿主 settings 已有绝对路径注册时，plugin 层那条应 fail-safe 直通。
