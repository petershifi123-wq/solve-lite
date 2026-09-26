#!/bin/bash
# Solve Lite · 豆包办公（DoubaoWork.app）一键安装（双击运行；不需要 sudo）
#
# 豆包办公的本地宿主没有 hook API（证据见 tools/host_hooks.py：app bundle 内
# 不存在 UserPromptSubmit / hookSpecificOutput / hook 配置读取器），所以这里：
#   1) 基座自检
#   2) 安装 solve-lite 技能到豆包办公可写的 .user_skills（带强制第一步）
#   3) hook 自测：豆包走 one-step 通道，断言预注入真的产出结构化结果
#   4) 打印可复制的一步命令（豆包没有 hook 时，激活不靠模型自己决定）
#
# 可选：SOLVE_LITE_PACKAGE_DIR=<离线包目录> 时，同一次运行安装公开 DLC 并
# 「安装即预组装资产视图」。

set -u
export TERM="${TERM:-xterm-256color}"
export PATH="/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/bin"
TREE="$(cd "$(dirname "$0")" && pwd)"
PY=/usr/bin/python3
HOST=doubao

echo "=============================================================="
echo " Solve Lite · 豆包办公（DoubaoWork.app）宿主安装"
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
  echo "[2/4] 安装技能到 .user_skills（不联网：跳过 DLC 下载）"
  "$PY" tools/installer.py --skip-dlc --host "$HOST" --json | tail -c 2000
fi
echo

echo "[3/4] hook 自测（豆包无 hook API → 走 one-step 预注入通道）"
"$PY" tools/hook_selftest.py --host "$HOST" --json > /tmp/solve_lite_hook_selftest_doubao.json 2>/tmp/solve_lite_hook_selftest_doubao.err
SELFTEST_RC=$?
tail -c 1600 /tmp/solve_lite_hook_selftest_doubao.json
if [ $SELFTEST_RC -ne 0 ]; then
  echo "--- selftest stderr ---"
  tail -c 800 /tmp/solve_lite_hook_selftest_doubao.err
fi
echo

echo "[4/4] 结果"
echo "SELFTEST_RC=$SELFTEST_RC"
echo "证据: /tmp/solve_lite_hook_selftest_doubao.json"
echo "技能位置: ~/Library/Application Support/DoubaoWork/Default/.doubaowork/agent_mode/workspace/.user_skills/solve-lite"
echo "豆包没有 hook 位，照抄这一步命令做确定性预注入（先在豆包里复制你的问题）："
"$PY" tools/host_hooks.py one-step --host "$HOST" --plugin-root "$TREE/plugins/solve-lite"
echo
echo "完成。"
if [ -t 0 ]; then
  read -n 1 -s -r -p "按任意键关闭窗口…"
fi
