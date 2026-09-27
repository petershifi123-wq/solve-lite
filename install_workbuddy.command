#!/bin/bash
# Solve Lite · WorkBuddy AI 真实宿主一键安装（双击运行；不需要 sudo）
#
# 做四件事，全部有真实输出，失败不谎报：
#   1) 基座自检（bundled LITE runtime + startup_check）
#   2) 注册「无条件激活」的 UserPromptSubmit hook 到 WorkBuddy 可写配置
#   3) hook 自测：断言宿主配置里的命令真的跑起来并注入（HOOK_FIRED=PASS/FAIL）
#   4) 打印注册结果 + 注册不了时给可复制的一步命令
#
# 普通安装默认安装全部三个公开 DLC，运行时按能力懒加载。
# 可选 SOLVE_LITE_PACKAGE_DIR=<离线包目录> 仅用于选择离线镜像来源。

set -euo pipefail
export TERM="${TERM:-xterm-256color}"
export PATH="/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/bin"
TREE="$(cd "$(dirname "$0")" && pwd)"
PY=/usr/bin/python3
HOST=workbuddy
STARTUP_JSON="/tmp/solve_lite_startup_${HOST}_$$.json"
INSTALL_JSON="/tmp/solve_lite_install_${HOST}_$$.json"
SELFTEST_JSON=/tmp/solve_lite_hook_selftest_workbuddy.json
SELFTEST_ERR=/tmp/solve_lite_hook_selftest_workbuddy.err

cleanup() {
  rm -f "$STARTUP_JSON" "$INSTALL_JSON"
}
trap cleanup EXIT

require_json_status() {
  "$PY" - "$1" "$2" "$3" <<'PY'
import json
import sys

document = json.load(open(sys.argv[1], encoding="utf-8"))
value = document
for key in sys.argv[2].split("."):
    value = value[key]
if value != sys.argv[3]:
    print("JSON_STATUS_MISMATCH:%s=%r expected=%r" % (sys.argv[2], value, sys.argv[3]))
    raise SystemExit(1)
PY
}

fail_stage() {
  echo "FAILED_STAGE=$1"
  echo "FINAL_INSTALL_STATUS=FAIL"
  exit 1
}

echo "=============================================================="
echo " Solve Lite · WorkBuddy AI 宿主安装"
echo " 安装树: $TREE"
echo " 宿主:   $HOST"
echo "=============================================================="
cd "$TREE" || { echo "无法进入安装树"; exit 1; }

echo
echo "[1/4] 基座自检"
if "$PY" tools/startup_check.py --root . --json >"$STARTUP_JSON"; then
  STARTUP_RC=0
else
  STARTUP_RC=$?
fi
tail -c 1200 "$STARTUP_JSON"
echo
if [ "$STARTUP_RC" -ne 0 ] || ! require_json_status "$STARTUP_JSON" STARTUP_CHECK PASS; then
  fail_stage startup_check
fi

if [ -n "${SOLVE_LITE_PACKAGE_DIR:-}" ]; then
  echo "[2/4] 安装公开 DLC + 安装即预组装资产视图（离线包: ${SOLVE_LITE_PACKAGE_DIR}）"
  if "$PY" tools/installer.py --install-dlc --package-dir "$SOLVE_LITE_PACKAGE_DIR" --host "$HOST" --json >"$INSTALL_JSON"; then
    INSTALL_RC=0
  else
    INSTALL_RC=$?
  fi
else
  echo "[2/4] 安装全部公开 DLC + 注册 hook（官方 Release）"
  if "$PY" tools/installer.py --host "$HOST" --json >"$INSTALL_JSON"; then
    INSTALL_RC=0
  else
    INSTALL_RC=$?
  fi
fi
tail -c 2000 "$INSTALL_JSON"
echo
if [ "$INSTALL_RC" -ne 0 ] || ! require_json_status "$INSTALL_JSON" status PASS; then
  fail_stage installer
fi

echo "[3/4] hook 自测（断言 hook 真跑并注入）"
if "$PY" tools/hook_selftest.py --host "$HOST" --json >"$SELFTEST_JSON" 2>"$SELFTEST_ERR"; then
  SELFTEST_RC=0
else
  SELFTEST_RC=$?
fi
tail -c 1600 "$SELFTEST_JSON"
if [ $SELFTEST_RC -ne 0 ]; then
  echo "--- selftest stderr ---"
  tail -c 800 "$SELFTEST_ERR"
fi
echo
if [ "$SELFTEST_RC" -ne 0 ] || ! require_json_status "$SELFTEST_JSON" hosts.workbuddy.HOOK_FIRED PASS; then
  fail_stage selftest
fi

echo "[4/4] 结果"
echo "SELFTEST_RC=$SELFTEST_RC"
echo "证据: /tmp/solve_lite_hook_selftest_workbuddy.json"
echo "WorkBuddy 配置: ~/.workbuddy-ai/settings.json （已备份为 settings.json.bak-solve-lite-*）"
echo "注册解不了时，照抄这一步命令即可手动跑同一段预注入："
"$PY" tools/host_hooks.py one-step --host "$HOST" --plugin-root "$TREE/plugins/solve-lite"
echo
echo "FINAL_INSTALL_STATUS=PASS"
echo "完成。回到 WorkBuddy 随便发一句话，hook 会先跑本地 Lite 再交给模型。"
if [ -t 0 ]; then
  read -n 1 -s -r -p "按任意键关闭窗口…"
fi
