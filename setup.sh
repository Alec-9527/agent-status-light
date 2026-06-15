#!/usr/bin/env bash
set -euo pipefail
# ──────────────────────────────────────────────────────────────────────
# Agent Status Light — 一键安装
# 用法: ./setup.sh
# ──────────────────────────────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
HERMES_SRC="$HOME/.hermes/hermes-agent/tools"
HERMES_CONFIG="$HOME/.hermes/config.yaml"

echo "🚦 Agent Status Light 安装"
echo "========================="
echo ""

# ── 1. 检测串口 ──
echo "1. 检测串口设备..."
PORT=""
for pat in /dev/cu.usbserial-* /dev/cu.wchusbserial* /dev/cu.SLAB_USBtoUART* /dev/cu.usbmodem* /dev/ttyUSB* /dev/ttyACM*; do
    if ls $pat 2>/dev/null | head -1 >/dev/null 2>&1; then
        PORT=$(ls $pat 2>/dev/null | head -1)
        break
    fi
done

if [ -z "$PORT" ]; then
    echo "   ⚠️  未检测到 USB 串口设备"
    echo "   请手动编辑 lamp_config.json 填写 serial_port"
else
    echo "   ✅ 找到: $PORT"
    # 自动写入配置文件
    python3 -c "
import json
p = '$PORT'
f = open('$SCRIPT_DIR/lamp_config.json')
cfg = json.load(f)
f.close()
if cfg.get('serial_port') != p:
    cfg['serial_port'] = p
    json.dump(cfg, open('$SCRIPT_DIR/lamp_config.json','w'), indent=4, ensure_ascii=False)
    print('   已自动填入配置文件')
" 2>/dev/null || true
fi

# ── 2. 测试灯 ──
echo ""
echo "2. 测试灯（闪烁红绿黄各一次）..."
python3 "$SCRIPT_DIR/hermes_lamp.py" red_flash
sleep 1
python3 "$SCRIPT_DIR/hermes_lamp.py" green_flash
sleep 1
python3 "$SCRIPT_DIR/hermes_lamp.py" yellow_flash
sleep 1
python3 "$SCRIPT_DIR/hermes_lamp.py" off
echo "   ✅ 测试完成（如果灯没反应，检查 lamp_config.json 里的命令）"

# ── 3. 启动 daemon ──
echo ""
echo "3. 启动后台 daemon..."
# Kill old daemon if exists
PID_FILE="$HOME/.hermes/lamp-daemon.pid"
if [ -f "$PID_FILE" ]; then
    kill $(cat "$PID_FILE") 2>/dev/null && sleep 0.5 || true
fi
python3 "$SCRIPT_DIR/hermes_lamp.py" --daemon &
sleep 1
if [ -f "$PID_FILE" ] && kill -0 $(cat "$PID_FILE") 2>/dev/null; then
    echo "   ✅ daemon 已启动 (pid=$(cat "$PID_FILE"))"
else
    echo "   ⚠️  daemon 启动失败，请手动运行: python3 hermes_lamp.py --daemon"
fi

# ── 4. 安装 Hermes hooks ──
echo ""
echo "4. 安装 Hermes hooks..."

LAMP_CMD="$SCRIPT_DIR/hermes_lamp.py"
HOOK_BLOCK=$(cat <<EOF

  # === Agent Status Light hooks ===
  pre_llm_call:
  - command: $LAMP_CMD
    timeout: 3
  pre_tool_call:
  - command: $LAMP_CMD
    timeout: 3
  pre_approval_request:
  - command: $LAMP_CMD
    timeout: 3
  post_approval_response:
  - command: $LAMP_CMD
    timeout: 3
  transform_llm_output:
  - command: $LAMP_CMD
    timeout: 3
  on_session_start:
  - command: $LAMP_CMD
    timeout: 3
  on_session_end:
  - command: $LAMP_CMD
    timeout: 3
EOF
)

if [ -f "$HERMES_CONFIG" ]; then
    if grep -q "Agent Status Light" "$HERMES_CONFIG" 2>/dev/null; then
        echo "   ℹ️  hooks 已存在，跳过"
    else
        echo "$HOOK_BLOCK" >> "$HERMES_CONFIG"
        echo "   ✅ hooks 已添加到 $HERMES_CONFIG"
    fi
else
    echo "   ⚠️  未找到 Hermes 配置文件，请手动在 ~/.hermes/config.yaml 添加 hooks"
    echo ""
    echo "   参考配置:"
    echo "$HOOK_BLOCK"
fi

# ── 5. Patch Hermes 源码（审批 + clarify 红灯） ──
echo ""
echo "5. Patching Hermes 源码..."

patch_approval() {
    local f="$HERMES_SRC/approval.py"
    [ ! -f "$f" ] && echo "   ⚠️  $f 不存在，跳过" && return
    if grep -q "hermes_lamp.py.*post_approval" "$f" 2>/dev/null; then
        echo "   ℹ️  approval.py 已 patch，跳过"
        return
    fi
    # Check for the exact text we're about to patch
    if ! grep -q 'def _fire_approval_hook' "$f" 2>/dev/null; then
        echo "   ⚠️  approval.py 结构变化，请手动 patch"
        return
    fi
    python3 -c "
import re
f = open('$f', 'r')
text = f.read()
f.close()

# Patch 1: _fire_approval_hook — add direct lamp call after invoke_hook
old = '        logger.debug(\"Approval hook %s dispatch failed: %s\", hook_name, exc)\\n\\n'
new = '''        logger.debug(\"Approval hook %s dispatch failed: %s\", hook_name, exc)

    # Direct lamp trigger
    try:
        import subprocess as _sp
        _sp.Popen(
            [\"$LAMP_CMD\", hook_name],
            stdin=_sp.DEVNULL, stdout=_sp.DEVNULL, stderr=_sp.DEVNULL,
            start_new_session=True,
        )
    except Exception:
        pass


def _trigger_post_approval_lamp() -> None:
    try:
        import subprocess as _sp
        _sp.Popen(
            [\"$LAMP_CMD\", \"post_approval_response\"],
            stdin=_sp.DEVNULL, stdout=_sp.DEVNULL, stderr=_sp.DEVNULL,
            start_new_session=True,
        )
    except Exception:
        pass


'''
if old in text:
    text = text.replace(old, new)
    f = open('$f', 'w')
    f.write(text)
    f.close()
    print('   ✅ approval.py patched')
else:
    print('   ⚠️  approval.py 已変更，请手动 patch')
"
}

patch_clarify() {
    local f="$HERMES_SRC/clarify_tool.py"
    [ ! -f "$f" ] && echo "   ⚠️  $f 不存在，跳过" && return
    if grep -q "hermes_lamp.py.*pre_approval" "$f" 2>/dev/null; then
        echo "   ℹ️  clarify_tool.py 已 patch，跳过"
        return
    fi
    python3 -c "
f = open('$f', 'r')
text = f.read()
f.close()

old = '''    try:
        user_response = callback(question, choices)
'''
new = '''    try:
        import subprocess as _sp
        _sp.Popen(
            [\"$LAMP_CMD\", \"pre_approval_request\"],
            stdin=_sp.DEVNULL, stdout=_sp.DEVNULL, stderr=_sp.DEVNULL,
            start_new_session=True,
        )
    except Exception:
        pass

    try:
        user_response = callback(question, choices)
'''
if old in text:
    text = text.replace(old, new)
    f = open('$f', 'w')
    f.write(text)
    f.close()
    print('   ✅ clarify_tool.py patched')
else:
    print('   ⚠️  clarify_tool.py 已变更，请手动 patch')
"
}

patch_approval
patch_clarify

# ── 完成 ──
echo ""
echo "========================="
echo "🎉 安装完成！"
echo ""
echo "下一步：重启 Hermes（/quit 然后 hermes）"
echo ""
echo "测试：在 Hermes 里运行需要审批的命令，灯应该变红"
echo ""
