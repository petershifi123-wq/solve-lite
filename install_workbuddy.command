#!/bin/bash
# Solve Lite · WorkBuddy AI 真实宿主一键安装（双击运行；不需要 sudo）
#
# 做四件事，全部有真实输出，失败不谎报：
#   1) 基座自检（bundled LITE runtime + startup_check）
#   2) 注册「无条件激活」的 UserPromptSubmit hook 到 WorkBuddy 可写配置
#   3) hook 自测：断言宿主配置里的命令真的跑起来并注入（HOOK_FIRED=PASS/FAIL）
#   4) 打印注册结果 + 注册不了时给可复制的一步命令
#
# 可选：设置 SOLVE_LITE_PACKAGE_DIR=<离线包目录> 时，本脚本会在同一次运行里
# 安装公开 DLC 组件并「安装即预组装资产视图」（首个 specialist 调用因此更快）。
# 未设置时不联网、只装基座 + hook。

set -u
export TERM="${TERM:-xterm-256color}"
export PATH="/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/bin"
TREE="$(cd "$(dirname "$0")" && pwd)"
PY=/usr/bin/python3
HOST=workbuddy

echo "=============================================================="
echo " Solve Lite · WorkBuddy AI 宿主安装"
echo " 安装树: $TREE"
echo " 宿主:   $HOST"
echo "=============================================================="
cd "$TREE" || { echo "无法进入安装树"; exit 1; }

echo
echo "[1/4] 基座自检"
"$PY" tools/startup_check.py --root . --json | tail -c 1200
echo

if [ -n "${SOLVE_LITE_PACKAGE_DIR:-}" ]; then
  echo "[2/4] 安装公开 DLC + 安装即预组装资产视图（离线包: $SOLVE_LITE_PACKAGE_DIR）"
  "$PY" tools/installer.py --install-dlc --package-dir "$SOLVE_LITE_PACKAGE_DIR" --host "$HOST" --json | tail -c 2000
else
  echo "[2/4] 注册 hook（不联网：跳过 DLC 下载；要装 DLC 请设 SOLVE_LITE_PACKAGE_DIR）"
  "$PY" tools/installer.py --skip-dlc --host "$HOST" --json | tail -c 2000
fi
echo

echo "[3/4] hook 自测（断言 hook 真跑并注入）"
"$PY" tools/hook_selftest.py --host "$HOST" --json > /tmp/solve_lite_hook_selftest_workbuddy.json 2>/tmp/solve_lite_hook_selftest_workbuddy.err
SELFTEST_RC=$?
tail -c 1600 /tmp/solve_lite_hook_selftest_workbuddy.json
if [ $SELFTEST_RC -ne 0 ]; then
  echo "--- selftest stderr ---"
  tail -c 800 /tmp/solve_lite_hook_selftest_workbuddy.err
fi
echo

echo "[4/4] 结果"
echo "SELFTEST_RC=$SELFTEST_RC"
echo "证据: /tmp/solve_lite_hook_selftest_workbuddy.json"
echo "WorkBuddy 配置: ~/.workbuddy-ai/settings.json （已备份为 settings.json.bak-solve-lite-*）"
echo "注册解不了时，照抄这一步命令即可手动跑同一段预注入："
"$PY" tools/host_hooks.py one-step --host "$HOST" --plugin-root "$TREE/plugins/solve-lite"
echo
echo "完成。回到 WorkBuddy 随便发一句话，hook 会先跑本地 Lite 再交给模型。"
if [ -t 0 ]; then
  read -n 1 -s -r -p "按任意键关闭窗口…"
fi
