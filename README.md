# Agent Status Light

Make a USB serial tower light show what your local AI agent is doing.

This project was extracted from a real Hermes Agent setup on macOS using a CH340/CH341 USB serial tower light. It is designed so other people can clone the repository, install it, and get the same behavior with minimal editing.

## What it does

Default lifecycle mapping:

| Agent state | Light state |
| --- | --- |
| Agent is thinking / using tools | steady yellow |
| Agent is waiting for approval | flashing red |
| User answered approval prompt | steady yellow |
| Turn finished | green flashing 10s, green steady 20s, then off |
| New work starts during the completion sequence | immediately interrupts and returns to yellow |

The serial writer runs in a background daemon and keeps the serial port open. Hook calls only enqueue the desired state, so your agent is not slowed down by USB serial latency.

## Supported hardware

Tested with a CH341 / CH340 USB serial tower light using the common 4-byte frame protocol:

```text
frame = A0 + address + opcode + checksum
checksum = low byte of the sum of the first 3 bytes
```

Default frames:

| Mode | Frame |
| --- | --- |
| off | `A0 00 00 A0` |
| yellow | `A0 01 01 A2` |
| yellow_flash | `A0 01 02 A3` |
| green | `A0 02 01 A3` |
| green_flash | `A0 02 02 A4` |
| red | `A0 03 01 A4` |
| red_flash | `A0 03 02 A5` |
| beep_off | `A0 04 00 A4` |
| beep_on | `A0 04 01 A5` |

Other serial lights can work if you edit `agent_status_light/lamp.py` or contribute another driver.

## Requirements

- macOS or Linux
- Python 3.10+
- USB serial tower light
- `stty` command available
- For Hermes integration: Hermes Agent with shell hooks or access to `~/.hermes/logs/agent.log`

No Python package dependencies are required.

## Quick start on macOS

```bash
git clone git@github.com:Alec-9527/agent-status-light.git
cd agent-status-light
./scripts/install-macos.sh
```

Then test the lamp:

```bash
~/bin/agent-status-light yellow
sleep 2
~/bin/agent-status-light green_flash
sleep 2
~/bin/agent-status-light off
```

If auto port detection picks the wrong device, set:

```bash
export AGENT_STATUS_LIGHT_PORT=/dev/cu.usbserial-XXXX
```

For a persistent setting, add it to `~/.zshrc` or your launchd plist environment.

## Hermes Agent integration

### Option A: shell hooks

Add hooks like this to your Hermes config. Adjust the path if you installed elsewhere.

```yaml
hooks:
  pre_llm_call:
    - command: /Users/YOUR_USER/bin/agent-status-light
      timeout: 3
  pre_tool_call:
    - command: /Users/YOUR_USER/bin/agent-status-light
      timeout: 3
  pre_approval_request:
    - command: /Users/YOUR_USER/bin/agent-status-light
      timeout: 3
  post_approval_response:
    - command: /Users/YOUR_USER/bin/agent-status-light
      timeout: 3
  transform_llm_output:
    - command: /Users/YOUR_USER/bin/agent-status-light
      timeout: 3
  on_session_start:
    - command: /Users/YOUR_USER/bin/agent-status-light
      timeout: 3
  on_session_end:
    - command: /Users/YOUR_USER/bin/agent-status-light
      timeout: 3
```

Then allowlist/restart Hermes according to your Hermes shell hook workflow.

### Option B: log monitor fallback

Some frontends do not expose every hook at the exact visible lifecycle moment. The log monitor watches `~/.hermes/logs/agent.log` and drives the lamp from real turn lifecycle log lines.

Install the macOS LaunchAgent:

```bash
./scripts/install-macos.sh --with-log-monitor
```

Or manually:

```bash
mkdir -p ~/Library/LaunchAgents
sed "s#__HOME__#$HOME#g" launchd/com.agent-status-light.log-monitor.plist \
  > ~/Library/LaunchAgents/com.agent-status-light.log-monitor.plist
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.agent-status-light.log-monitor.plist 2>/dev/null || true
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.agent-status-light.log-monitor.plist
launchctl enable gui/$(id -u)/com.agent-status-light.log-monitor
```

## CLI usage

```bash
agent-status-light yellow       # enqueue yellow and start daemon if needed
agent-status-light done         # green flash 10s -> green 20s -> off
agent-status-light --send-now off
agent-status-light --daemon
agent-status-light-log-monitor
```

Supported modes:

```text
off yellow yellow_flash green green_flash red red_flash beep_off beep_on done
```

## Files used at runtime

By default runtime state lives under `~/.agent-status-light/`:

```text
~/.agent-status-light/request.json
~/.agent-status-light/state.json
~/.agent-status-light/daemon.pid
~/.agent-status-light/logs/lamp.log
~/.agent-status-light/logs/log-monitor.log
```

Override with environment variables:

| Variable | Purpose |
| --- | --- |
| `AGENT_STATUS_LIGHT_HOME` | runtime directory |
| `AGENT_STATUS_LIGHT_PORT` | fixed serial device path |
| `AGENT_STATUS_LIGHT_BAUD` | baud rate, default `9600` |
| `AGENT_STATUS_LIGHT_AGENT_LOG` | log file watched by monitor |
| `AGENT_STATUS_LIGHT_LAMP_BIN` | lamp CLI used by monitor |

## Development

Run tests:

```bash
python3 -m unittest discover -s tests -v
```

Run style/syntax checks:

```bash
python3 -m py_compile agent_status_light/*.py tests/*.py
```

Open in VS Code:

```bash
code .
```

## Safety notes

- The default implementation only writes the known frames above.
- It sends `off` before most non-off light states to avoid overlapping modes on simple controllers.
- The completion sequence is interruptible by a newer request file timestamp.
- If your lamp has a buzzer, `beep_on` can be noisy. The default lifecycle does not use the buzzer.

## License

MIT
