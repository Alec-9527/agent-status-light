#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mkdir -p "$HOME/bin" "$HOME/.agent-status-light/logs"

# Install runnable wrappers that use this checkout directly.
cat > "$HOME/bin/agent-status-light" <<EOF
#!/usr/bin/env bash
PYTHONPATH="$ROOT_DIR" exec python3 -m agent_status_light.lamp "\$@"
EOF
chmod +x "$HOME/bin/agent-status-light"

cat > "$HOME/bin/agent-status-light-log-monitor" <<EOF
#!/usr/bin/env bash
PYTHONPATH="$ROOT_DIR" exec python3 -m agent_status_light.log_monitor "\$@"
EOF
chmod +x "$HOME/bin/agent-status-light-log-monitor"

echo "Installed: $HOME/bin/agent-status-light"
echo "Installed: $HOME/bin/agent-status-light-log-monitor"

if [[ ":$PATH:" != *":$HOME/bin:"* ]]; then
  echo "Note: add ~/bin to PATH if your shell cannot find agent-status-light."
fi

if [[ "${1:-}" == "--with-log-monitor" ]]; then
  mkdir -p "$HOME/Library/LaunchAgents"
  sed "s#__HOME__#$HOME#g" "$ROOT_DIR/launchd/com.agent-status-light.log-monitor.plist" \
    > "$HOME/Library/LaunchAgents/com.agent-status-light.log-monitor.plist"
  uid="$(id -u)"
  launchctl bootout "gui/$uid" "$HOME/Library/LaunchAgents/com.agent-status-light.log-monitor.plist" 2>/dev/null || true
  launchctl bootstrap "gui/$uid" "$HOME/Library/LaunchAgents/com.agent-status-light.log-monitor.plist"
  launchctl enable "gui/$uid/com.agent-status-light.log-monitor"
  echo "Started LaunchAgent: com.agent-status-light.log-monitor"
fi

"$HOME/bin/agent-status-light" --help
