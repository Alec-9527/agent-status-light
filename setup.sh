#!/usr/bin/env bash
set -euo pipefail
# ──────────────────────────────────────────────────────────────────────
# Agent Status Light — one-command setup
# Usage: ./setup.sh   or   curl .../setup.sh | bash
# ──────────────────────────────────────────────────────────────────────

# Resolve script directory (works for both cloned repo and curl pipe)
if [ -n "${BASH_SOURCE:-}" ] && [ "${BASH_SOURCE}" != "bash" ] && [ -f "${BASH_SOURCE}" ]; then
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE}")" && pwd)"
else
    REPO_DIR="$HOME/agent-status-light"
    if [ ! -d "$REPO_DIR" ]; then
        echo "📦 Downloading project..."
        git clone https://github.com/Alec-9527/agent-status-light.git "$REPO_DIR"
    fi
    SCRIPT_DIR="$REPO_DIR"
fi

HERMES_SRC="$HOME/.hermes/hermes-agent/tools"
HERMES_CONFIG="$HOME/.hermes/config.yaml"

echo "🚦 Agent Status Light Setup"
echo "============================"
echo ""

# ── 1. Detect serial port ──
echo "1. Detecting serial port..."
PORT=""
for pat in /dev/cu.usbserial-* /dev/cu.wchusbserial* /dev/cu.SLAB_USBtoUART* /dev/cu.usbmodem* /dev/ttyUSB* /dev/ttyACM*; do
    if ls $pat 2>/dev/null | head -1 >/dev/null 2>&1; then
        PORT=$(ls $pat 2>/dev/null | head -1)
        break
    fi
done

if [ -z "$PORT" ]; then
    echo "   ⚠️  No USB serial device found"
    echo "   Edit lamp_config.json and set serial_port manually"
else
    echo "   ✅ Found: $PORT"
    python3 -c "
import json
p = '$PORT'
cfg = json.load(open('$SCRIPT_DIR/lamp_config.json'))
if cfg.get('serial_port') != p:
    cfg['serial_port'] = p
    json.dump(cfg, open('$SCRIPT_DIR/lamp_config.json','w'), indent=4, ensure_ascii=False)
    print('   Auto-filled lamp_config.json')
" 2>/dev/null || true
fi

# ── 2. Test the light ──
echo ""
echo "2. Testing the light (flash red, green, yellow)..."
python3 "$SCRIPT_DIR/hermes_lamp.py" red_flash
sleep 1
python3 "$SCRIPT_DIR/hermes_lamp.py" green_flash
sleep 1
python3 "$SCRIPT_DIR/hermes_lamp.py" yellow_flash
sleep 1
python3 "$SCRIPT_DIR/hermes_lamp.py" off
echo "   ✅ Test complete (if no response, check commands in lamp_config.json)"

# ── 3. Start daemon ──
echo ""
echo "3. Starting background daemon..."
PID_FILE="$HOME/.hermes/lamp-daemon.pid"
if [ -f "$PID_FILE" ]; then
    kill $(cat "$PID_FILE") 2>/dev/null && sleep 0.5 || true
fi
python3 "$SCRIPT_DIR/hermes_lamp.py" --daemon &
sleep 1
if [ -f "$PID_FILE" ] && kill -0 $(cat "$PID_FILE") 2>/dev/null; then
    echo "   ✅ Daemon started (pid=$(cat "$PID_FILE"))"
else
    echo "   ⚠️  Daemon failed to start. Run manually: python3 hermes_lamp.py --daemon"
fi

# ── 4. Install Hermes hooks ──
echo ""
echo "4. Installing Hermes hooks..."

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
        echo "   ℹ️  Hooks already installed, skipping"
    else
        echo "$HOOK_BLOCK" >> "$HERMES_CONFIG"
        echo "   ✅ Hooks added to $HERMES_CONFIG"
    fi
else
    echo "   ⚠️  Hermes config not found. Add hooks manually to ~/.hermes/config.yaml:"
    echo "$HOOK_BLOCK"
fi

# ── 5. Patch Hermes source (approval + clarify red flash) ──
echo ""
echo "5. Patching Hermes source..."

patch_approval() {
    local f="$HERMES_SRC/approval.py"
    [ ! -f "$f" ] && echo "   ⚠️  $f not found, skipping" && return
    if grep -q "hermes_lamp.py.*post_approval" "$f" 2>/dev/null; then
        echo "   ℹ️  approval.py already patched, skipping"
        return
    fi
    if ! grep -q 'def _fire_approval_hook' "$f" 2>/dev/null; then
        echo "   ⚠️  approval.py structure changed, patch manually"
        return
    fi
    python3 -c "
f = open('$f'); text = f.read(); f.close()
old = '        logger.debug(\"Approval hook %s dispatch failed: %s\", hook_name, exc)\\n\\n'
new = '''        logger.debug(\"Approval hook %s dispatch failed: %s\", hook_name, exc)

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
    open('$f','w').write(text)
    print('   ✅ approval.py patched')
else:
    print('   ⚠️  approval.py changed, patch manually')
"
}

patch_clarify() {
    local f="$HERMES_SRC/clarify_tool.py"
    [ ! -f "$f" ] && echo "   ⚠️  $f not found, skipping" && return
    if grep -q "hermes_lamp.py.*pre_approval" "$f" 2>/dev/null; then
        echo "   ℹ️  clarify_tool.py already patched, skipping"
        return
    fi
    python3 -c "
f = open('$f'); text = f.read(); f.close()
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
    open('$f','w').write(text)
    print('   ✅ clarify_tool.py patched')
else:
    print('   ⚠️  clarify_tool.py changed, patch manually')
"
}

patch_approval
patch_clarify

# ── Done ──
echo ""
echo "============================"
echo "🎉 Setup complete!"
echo ""
echo "Next: restart Hermes (/quit then hermes)"
echo ""
echo "Test: run a command that needs approval — the light should turn red."
echo ""
