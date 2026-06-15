#!/usr/bin/env python3
"""Non-blocking control for the USB serial tower light used by Hermes hooks.

Normal invocation (used by Hermes hooks) is intentionally fast: it writes the
requested mode to ~/.hermes/lamp-request.json and ensures a background daemon is
running. The daemon owns the slow serial writes so Hermes is never delayed by
USB/driver latency.

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
REQUEST_FILE = HERMES_DIR / "lamp-request.json"
PID_FILE = HERMES_DIR / "lamp-daemon.pid"
LOG_FILE = HERMES_DIR / "logs" / "lamp-hook.log"

COMMANDS = {
    "off": bytes.fromhex("A0 00 00 A0"),
    "yellow": bytes.fromhex("A0 01 01 A2"),
    "yellow_flash": bytes.fromhex("A0 01 02 A3"),
    "green": bytes.fromhex("A0 02 01 A3"),
    "green_flash": bytes.fromhex("A0 02 02 A4"),
    "red": bytes.fromhex("A0 03 01 A4"),
    "red_flash": bytes.fromhex("A0 03 02 A5"),
    "beep_off": bytes.fromhex("A0 04 00 A4"),
    "beep_on": bytes.fromhex("A0 04 01 A5"),
}

SEQUENCE_MODES = {"done"}
DONE_FLASH_SECONDS = 5.0
DONE_STEADY_SECONDS = 25.0
POLL_SECONDS = 0.05

CODING_TOOLS = {
    "write_file",
    "patch",
    "terminal",
    "execute_code",
    "process",
    "delegate_task",
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


def record_state(mode: str) -> None:
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps({"mode": mode, "ts": time.time()}), encoding="utf-8")
    except Exception:
        pass


def send_mode_now(mode: str) -> bool:
    if mode == "done":
        ok = send_mode_now("green_flash")
        time.sleep(DONE_FLASH_SECONDS)
        ok = send_mode_now("green") and ok
        time.sleep(DONE_STEADY_SECONDS)
        ok = send_mode_now("off") and ok
        record_state("done")
        return ok
    frame = COMMANDS.get(mode)
    if frame is None:
        log(f"unknown mode: {mode}")
        return False
    if mode != "off":
        send_frame(COMMANDS["off"])
        time.sleep(0.12)
    ok = send_frame(frame)
    record_state(mode)
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
    record_state(mode)
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


def enqueue_mode(mode: str) -> bool:
    if mode not in COMMANDS and mode not in SEQUENCE_MODES:
        log(f"unknown queued mode: {mode}")
        return False
    try:
        HERMES_DIR.mkdir(parents=True, exist_ok=True)
        tmp = REQUEST_FILE.with_name(f"{REQUEST_FILE.name}.{os.getpid()}.{time.time_ns()}.tmp")
        tmp.write_text(json.dumps({"mode": mode, "ts": time.time()}), encoding="utf-8")
        os.replace(tmp, REQUEST_FILE)
        ensure_daemon()
        return True
    except Exception as e:
        log(f"enqueue failed: {e}")
        return False


def read_request() -> dict:
    try:
        return json.loads(REQUEST_FILE.read_text(encoding="utf-8")) if REQUEST_FILE.exists() else {}
    except Exception:
        return {}


def request_key(req: dict) -> tuple[str | None, float]:
    return (req.get("mode"), float(req.get("ts", 0) or 0))


def sleep_until_changed_or_timeout(active_key: tuple[str | None, float], seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if request_key(read_request()) != active_key:
            return True
        time.sleep(POLL_SECONDS)
    return False


def run_done_sequence_on_open_port(f, port: str, active_key: tuple[str | None, float]) -> bool:
    log(f"starting done sequence: green_flash {DONE_FLASH_SECONDS:g}s -> green {DONE_STEADY_SECONDS:g}s -> off")
    ok = send_mode_on_open_port("green_flash", f, port)
    if sleep_until_changed_or_timeout(active_key, DONE_FLASH_SECONDS):
        log("done sequence interrupted during green_flash")
        return ok
    ok = send_mode_on_open_port("green", f, port) and ok
    if sleep_until_changed_or_timeout(active_key, DONE_STEADY_SECONDS):
        log("done sequence interrupted during green steady")
        return ok
    ok = send_mode_on_open_port("off", f, port) and ok
    record_state("done")
    log("done sequence completed")
    return ok


def daemon_loop() -> int:
    HERMES_DIR.mkdir(parents=True, exist_ok=True)
    # Single daemon guard. If another live daemon exists, exit quietly.
    if PID_FILE.exists():
        try:
            old = int(PID_FILE.read_text().strip() or "0")
            if old and old != os.getpid() and pid_alive(old):
                return 0
        except Exception:
            pass
    PID_FILE.write_text(str(os.getpid()), encoding="utf-8")
    log(f"daemon started pid={os.getpid()}")
    last_key: tuple[str, float] | None = None
    port: str | None = None
    serial_f = None
    try:
        while True:
            req = read_request()
            mode, ts = request_key(req)
            key = (mode, ts)
            if (mode in COMMANDS or mode in SEQUENCE_MODES) and key != last_key:
                last_key = key
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
                            run_done_sequence_on_open_port(serial_f, port, key)
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


def payload_from_stdin() -> dict:
    try:
        raw = sys.stdin.read()
        if raw.strip():
            log(f"hook stdin payload: {raw.strip()}")
        return json.loads(raw) if raw.strip() else {}
    except Exception as e:
        log(f"hook stdin parse error: {e}")
        return {}


def mode_for_hook(payload: dict, fallback: str | None = None) -> str | None:
    event = payload.get("hook_event_name")
    if event == "pre_approval_request":
        return "red_flash"
    if event == "post_approval_response":
        return "yellow"
    if event == "pre_llm_call":
        return "yellow"
    if event == "pre_tool_call":
        if _tool_call_will_require_approval(payload):
            return "red_flash"
        return "yellow"
    if event == "transform_llm_output":
        return "done"
    if event == "on_session_start":
        return "off"
    if event == "on_session_end":
        return "done"
    return fallback


def _tool_call_will_require_approval(payload: dict) -> bool:
    """Detect if a tool call will trigger the approval dialog.

    When the terminal/execute_code tool is about to run a command that
    Hermes will flag for user approval, we return True so the lamp can
    switch to red_flash *before* the dialog appears — the shell hook
    fires synchronously in pre_tool_call, earlier than the
    pre_approval_request hook which has subprocess/daemon latency.
    """
    tool_name = payload.get("tool_name", "")
    tool_input = payload.get("tool_input") or {}

    if tool_name == "terminal":
        command = tool_input.get("command", "")
        patterns = [
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
        for pat in patterns:
            if re.search(pat, command):
                return True

    if tool_name == "execute_code":
        # execute_code triggers approval for destructive patterns
        return True

    if tool_name == "clarify":
        # clarify pauses the agent and waits for user input — treat as
        # "needs user attention", same as approval
        return True

    return False


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
        mode = HOOK_NAME_TO_MODE.get(argv[1], argv[1])
    else:
        mode = mode_for_hook(payload_from_stdin())
    if not mode:
        return 0
    return 0 if enqueue_mode(mode) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
