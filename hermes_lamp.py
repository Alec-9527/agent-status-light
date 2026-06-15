#!/usr/bin/env python3
"""Non-blocking control for the USB serial tower light used by Hermes hooks.

Normal invocation (used by Hermes hooks) is intentionally fast: it writes the
requested mode to ~/.hermes/lamp-state.json and ensures a background daemon is
running. The daemon owns the slow serial writes so Hermes is never delayed by
USB/driver latency.

Architecture:
  Multiple signal sources each write their state to lamp-state.json[source].
  The daemon aggregates all sources and picks the highest-priority mode:
    red_flash > done > yellow > green > off
  This prevents yellow hooks from overwriting red approval signals — a common
  race condition in single-file "last write wins" designs.

Protocol from 虹明机电 USB 串口报警灯 datasheet:
  frame = A0 + address + opcode + checksum(sum first 3 bytes, low byte)
"""
from __future__ import annotations

import glob
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

DEFAULT_BAUD = "9600"
HERMES_DIR = Path.home() / ".hermes"
STATE_FILE = HERMES_DIR / "lamp-state.json"
PID_FILE = HERMES_DIR / "lamp-daemon.pid"
LOG_FILE = HERMES_DIR / "logs" / "lamp-hook.log"

# ── Lamp config file (optional) ───────────────────────────────────────
_DEFAULT_COMMANDS: dict[str, bytes] = {
    "off":          bytes.fromhex("A0 00 00 A0"),
    "yellow":       bytes.fromhex("A0 01 01 A2"),
    "yellow_flash": bytes.fromhex("A0 01 02 A3"),
    "green":        bytes.fromhex("A0 02 01 A3"),
    "green_flash":  bytes.fromhex("A0 02 02 A4"),
    "red":          bytes.fromhex("A0 03 01 A4"),
    "red_flash":    bytes.fromhex("A0 03 02 A5"),
    "beep_off":     bytes.fromhex("A0 04 00 A4"),
    "beep_on":      bytes.fromhex("A0 04 01 A5"),
}

CONFIG_FILE = Path(__file__).resolve().parent / "lamp_config.json"
_loaded_commands: dict[str, bytes] = dict(_DEFAULT_COMMANDS)

DONE_FLASH_SECONDS = 5.0
DONE_STEADY_SECONDS = 25.0

if CONFIG_FILE.exists():
    try:
        cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        for name, hexstr in cfg.get("commands", {}).items():
            if name in _loaded_commands and isinstance(hexstr, str):
                _loaded_commands[name] = bytes.fromhex(hexstr)
        DONE_FLASH_SECONDS = float(cfg.get("done_flash_seconds", DONE_FLASH_SECONDS))
        DONE_STEADY_SECONDS = float(cfg.get("done_steady_seconds", DONE_STEADY_SECONDS))
    except Exception:
        pass

COMMANDS = _loaded_commands
SEQUENCE_MODES = {"done"}
POLL_SECONDS = 0.05
STATE_TTL = 60.0  # stale state entries expire after 60s

# ── Priority: higher value = wins when multiple sources are active ──
_MODE_PRIORITY: dict[str | None, int] = {
    "red_flash": 40,
    "red":       30,
    "done":      20,
    "yellow_flash": 11,
    "yellow":    10,
    "green_flash": 6,
    "green":     5,
    "off":       0,
    None:       -1,
}


def log(msg: str) -> None:
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + msg + "\n")
    except Exception:
        pass


def find_port() -> str | None:
    env_port = os.environ.get("HERMES_LAMP_PORT")
    if env_port and Path(env_port).exists():
        return env_port
    patterns = [
        "/dev/cu.usbserial-*",
        "/dev/cu.wchusbserial*",
        "/dev/cu.SLAB_USBtoUART*",
        "/dev/cu.usbmodem*",
    ]
    for pat in patterns:
        ports = sorted(glob.glob(pat))
        if ports:
            return ports[0]
    return None


def configure_port(port: str) -> None:
    subprocess.run(
        ["stty", "-f", port, DEFAULT_BAUD, "cs8", "-cstopb", "-parenb", "-ixon", "-ixoff", "-crtscts", "raw"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )


def send_frame(frame: bytes, *, port: str | None = None) -> bool:
    port = port or find_port()
    if not port:
        log("no serial port found")
        return False
    try:
        configure_port(port)
        with open(port, "wb", buffering=0) as f:
            f.write(frame)
        log(f"sent {frame.hex(' ').upper()} to {port}")
        return True
    except Exception as e:
        log(f"send failed on {port}: {e}")
        return False


def send_mode_now(mode: str) -> bool:
    if mode == "done":
        ok = send_mode_now("green_flash")
        time.sleep(DONE_FLASH_SECONDS)
        ok = send_mode_now("green") and ok
        time.sleep(DONE_STEADY_SECONDS)
        ok = send_mode_now("off") and ok
        return ok
    frame = COMMANDS.get(mode)
    if frame is None:
        log(f"unknown mode: {mode}")
        return False
    if mode != "off":
        send_frame(COMMANDS["off"])
        time.sleep(0.12)
    ok = send_frame(frame)
    return ok


def write_frame_to_open_port(f, frame: bytes, port: str) -> bool:
    try:
        f.write(frame)
        try:
            f.flush()
        except Exception:
            pass
        log(f"sent {frame.hex(' ').upper()} to {port}")
        return True
    except Exception as e:
        log(f"send failed on already-open {port}: {e}")
        return False


def send_mode_on_open_port(mode: str, f, port: str) -> bool:
    frame = COMMANDS.get(mode)
    if frame is None:
        log(f"unknown mode: {mode}")
        return False
    ok = True
    if mode != "off":
        ok = write_frame_to_open_port(f, COMMANDS["off"], port)
        time.sleep(0.12)
    ok = write_frame_to_open_port(f, frame, port) and ok
    return ok


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def ensure_daemon() -> None:
    try:
        if PID_FILE.exists():
            pid = int(PID_FILE.read_text().strip() or "0")
            if pid > 0 and pid_alive(pid):
                return
    except Exception:
        pass
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        out = open(LOG_FILE, "a", encoding="utf-8")
        subprocess.Popen(
            [sys.executable, __file__, "--daemon"],
            stdin=subprocess.DEVNULL,
            stdout=out,
            stderr=out,
            start_new_session=True,
            close_fds=True,
        )
    except Exception as e:
        log(f"failed to start daemon: {e}")


# ── State management (multi-source, priority-aggregated) ──────────────

def _read_state() -> dict[str, dict]:
    try:
        if STATE_FILE.exists():
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _write_state(state: dict[str, dict]) -> None:
    try:
        HERMES_DIR.mkdir(parents=True, exist_ok=True)
        tmp = STATE_FILE.with_name(f"{STATE_FILE.name}.{os.getpid()}.{time.time_ns()}.tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, STATE_FILE)
    except Exception:
        pass


def set_state(source: str, mode: str) -> bool:
    """Write a signal from *source* into the aggregated state file."""
    if mode not in COMMANDS and mode not in SEQUENCE_MODES:
        log(f"unknown mode: {mode}")
        return False
    try:
        state = _read_state()
        state[source] = {"mode": mode, "ts": time.time()}
        _write_state(state)
        ensure_daemon()
        return True
    except Exception as e:
        log(f"set_state failed: {e}")
        return False


def _compute_aggregate_mode() -> tuple[str | None, float]:
    """Return (mode, ts) with the highest priority across all sources.

    Stale entries (> STATE_TTL) are ignored.
    """
    state = _read_state()
    best_mode: str | None = None
    best_ts: float = 0.0
    best_priority: int = -1
    now = time.time()
    for source, entry in state.items():
        if not isinstance(entry, dict):
            continue
        mode = entry.get("mode")
        ts = float(entry.get("ts", 0))
        if now - ts > STATE_TTL:
            continue
        prio = _MODE_PRIORITY.get(mode, -1)
        if prio > best_priority or (prio == best_priority and ts > best_ts):
            best_priority = prio
            best_mode = mode
            best_ts = ts
    return (best_mode, best_ts)


# ── Daemon ────────────────────────────────────────────────────────────

def daemon_loop() -> int:
    HERMES_DIR.mkdir(parents=True, exist_ok=True)
    if PID_FILE.exists():
        try:
            old = int(PID_FILE.read_text().strip() or "0")
            if old and old != os.getpid() and pid_alive(old):
                return 0
        except Exception:
            pass
    PID_FILE.write_text(str(os.getpid()), encoding="utf-8")
    log(f"daemon started pid={os.getpid()} (priority-aggregated)")
    last_key: tuple[str | None, float] = (None, 0.0)
    port: str | None = None
    serial_f = None
    try:
        while True:
            mode, ts = _compute_aggregate_mode()
            key = (mode, ts)
            if key != last_key:
                last_key = key
                if mode is None:
                    mode = "off"
                try:
                    wanted_port = find_port()
                    if not wanted_port:
                        log("no serial port found")
                    else:
                        if serial_f is None or port != wanted_port or getattr(serial_f, "closed", False):
                            if serial_f is not None:
                                try:
                                    serial_f.close()
                                except Exception:
                                    pass
                            port = wanted_port
                            configure_port(port)
                            serial_f = open(port, "wb", buffering=0)
                            log(f"opened persistent serial port {port}")
                        if mode == "done":
                            _run_done_sequence_aggregated(serial_f, port)
                        else:
                            send_mode_on_open_port(mode, serial_f, port)
                except Exception as e:
                    log(f"persistent send failed, will reopen next time: {e}")
                    if serial_f is not None:
                        try:
                            serial_f.close()
                        except Exception:
                            pass
                    serial_f = None
                    port = None
            time.sleep(POLL_SECONDS)
    finally:
        if serial_f is not None:
            try:
                serial_f.close()
            except Exception:
                pass
        try:
            if PID_FILE.read_text().strip() == str(os.getpid()):
                PID_FILE.unlink()
        except Exception:
            pass


def _run_done_sequence_aggregated(f, port: str) -> bool:
    """Run done sequence, checking aggregate state between phases.

    If a higher-priority signal arrives (e.g. new approval), the sequence
    is interrupted early.
    """
    log(f"starting done sequence: green_flash {DONE_FLASH_SECONDS:g}s -> green {DONE_STEADY_SECONDS:g}s -> off")
    ok = send_mode_on_open_port("green_flash", f, port)
    if _sleep_until_priority_changes("done", DONE_FLASH_SECONDS):
        log("done sequence interrupted during green_flash")
        return ok
    ok = send_mode_on_open_port("green", f, port) and ok
    if _sleep_until_priority_changes("done", DONE_STEADY_SECONDS):
        log("done sequence interrupted during green steady")
        return ok
    ok = send_mode_on_open_port("off", f, port) and ok
    log("done sequence completed")
    return ok


def _sleep_until_priority_changes(current_mode: str, seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        agg_mode, _ = _compute_aggregate_mode()
        if agg_mode != current_mode:
            return True
        time.sleep(POLL_SECONDS)
    return False


# ── Hook integration ──────────────────────────────────────────────────

def payload_from_stdin() -> dict:
    try:
        raw = sys.stdin.read()
        return json.loads(raw) if raw.strip() else {}
    except Exception:
        return {}


def mode_for_hook(payload: dict) -> tuple[str, str] | None:
    """Return (source_key, lamp_mode) for a hook event, or None."""
    event = payload.get("hook_event_name")
    if event == "pre_approval_request":
        return ("hook:approval", "red_flash")
    if event == "post_approval_response":
        return ("hook:approval", "yellow")
    if event == "pre_llm_call":
        return ("hook:llm", "yellow")
    if event == "pre_tool_call":
        if _tool_call_will_require_approval(payload):
            return ("hook:tool", "red_flash")
        return ("hook:tool", "yellow")
    if event == "transform_llm_output":
        return ("hook:done", "done")
    if event == "on_session_start":
        return ("hook:session", "off")
    if event == "on_session_end":
        return ("hook:done", "done")
    return None


def _tool_call_will_require_approval(payload: dict) -> bool:
    tool_name = payload.get("tool_name", "")
    tool_input = payload.get("tool_input") or {}

    if tool_name == "terminal":
        command = tool_input.get("command", "")
        approval_patterns = [
            r"\b(bash|sh|zsh|ksh)\s+-[^\s]*c(\s+|$)",
            r"\b(python[23]?|perl|ruby|node)\s+-[ec]\s+",
            r"\b(curl|wget)\b.*\|\s*(?:[/\w]*/)?(?:ba)?sh(?:\s|$|-c)",
            r"\bkill\s+-9\s+-1\b",
            r"\bpkill\s+-9\b",
            r"\bkillall\s+(-[^\s]*\s+)*-(9|KILL|SIGKILL)\b",
            r"\brm\s+-rf?\s+/",
            r"\b>?\s*/dev/sd[a-z]",
            r"\bdd\s+if=",
            r"\bmkfs\.",
            r"\b(git)\s+push\s+.*(--force|--force-with-lease)",
            r"\bdocker\s+(restart|stop|kill)\b",
            r"\bsystemctl\s+(-[^\s]+\s+)*(stop|restart|disable|mask)\b",
            r"\bhermes\s+gateway\s+(stop|restart)\b",
        ]
        for pat in approval_patterns:
            if re.search(pat, command):
                return True
        stdin_blocking = [
            r"\bsudo\b",
            r"\bssh\b(?!\s+\S+@\S+\s+\S)",
            r"\b(su|login)\b",
            r"\bpasswd\b",
            r"\bgh\s+auth\s+login\b",
        ]
        for pat in stdin_blocking:
            if re.search(pat, command):
                return True

    if tool_name in ("execute_code", "clarify", "browser"):
        return True

    return False


# ── CLI entry point ───────────────────────────────────────────────────

HOOK_NAME_TO_MODE = {
    "pre_approval_request": "red_flash",
    "post_approval_response": "yellow",
}


def main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[1] == "--daemon":
        return daemon_loop()
    if len(argv) >= 3 and argv[1] == "--send-now":
        return 0 if send_mode_now(argv[2]) else 1
    if len(argv) >= 2:
        # Direct CLI call with hook name or mode: set_state with generic source
        mode = HOOK_NAME_TO_MODE.get(argv[1], argv[1])
        source = f"direct:{argv[1]}" if argv[1] in HOOK_NAME_TO_MODE else "direct:cli"
        return 0 if set_state(source, mode) else 1
    else:
        # Hook invocation (stdin JSON): use source-keyed state
        payload = payload_from_stdin()
        result = mode_for_hook(payload)
        if result is None:
            return 0
        source, mode = result
        return 0 if set_state(source, mode) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
