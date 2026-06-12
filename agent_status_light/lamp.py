#!/usr/bin/env python3
"""Non-blocking USB serial tower light controller.

Normal invocation writes a requested mode to a runtime JSON file and ensures a
background daemon is running. The daemon owns slow serial I/O so agent hooks can
return quickly.
"""
from __future__ import annotations

import glob
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import BinaryIO

COMMANDS: dict[str, bytes] = {
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
DONE_FLASH_SECONDS = float(os.environ.get("AGENT_STATUS_LIGHT_DONE_FLASH_SECONDS", "10"))
DONE_STEADY_SECONDS = float(os.environ.get("AGENT_STATUS_LIGHT_DONE_STEADY_SECONDS", "20"))
POLL_SECONDS = float(os.environ.get("AGENT_STATUS_LIGHT_POLL_SECONDS", "0.05"))


def runtime_home() -> Path:
    return Path(os.environ.get("AGENT_STATUS_LIGHT_HOME", Path.home() / ".agent-status-light")).expanduser()


def baud() -> str:
    return os.environ.get("AGENT_STATUS_LIGHT_BAUD", "9600")


def state_file() -> Path:
    return runtime_home() / "state.json"


def request_file() -> Path:
    return runtime_home() / "request.json"


def pid_file() -> Path:
    return runtime_home() / "daemon.pid"


def log_file() -> Path:
    return runtime_home() / "logs" / "lamp.log"


def log(msg: str) -> None:
    try:
        log_file().parent.mkdir(parents=True, exist_ok=True)
        with log_file().open("a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + msg + "\n")
    except Exception:
        pass


def find_port() -> str | None:
    env_port = os.environ.get("AGENT_STATUS_LIGHT_PORT")
    if env_port:
        return env_port if Path(env_port).exists() else None
    patterns = [
        "/dev/cu.usbserial-*",
        "/dev/cu.wchusbserial*",
        "/dev/cu.SLAB_USBtoUART*",
        "/dev/cu.usbmodem*",
        "/dev/ttyUSB*",
        "/dev/ttyACM*",
    ]
    for pat in patterns:
        ports = sorted(glob.glob(pat))
        if ports:
            return ports[0]
    return None


def configure_port(port: str) -> None:
    if sys.platform == "darwin":
        cmd = ["stty", "-f", port, baud(), "cs8", "-cstopb", "-parenb", "-ixon", "-ixoff", "-crtscts", "raw"]
    else:
        cmd = ["stty", "-F", port, baud(), "cs8", "-cstopb", "-parenb", "-ixon", "-ixoff", "-crtscts", "raw"]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)


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
        state_file().parent.mkdir(parents=True, exist_ok=True)
        state_file().write_text(json.dumps({"mode": mode, "ts": time.time()}), encoding="utf-8")
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
    ok = True
    if mode != "off":
        ok = send_frame(COMMANDS["off"])
        time.sleep(0.12)
    ok = send_frame(frame) and ok
    record_state(mode)
    return ok


def write_frame_to_open_port(f: BinaryIO, frame: bytes, port: str) -> bool:
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


def send_mode_on_open_port(mode: str, f: BinaryIO, port: str) -> bool:
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
        if pid_file().exists():
            pid = int(pid_file().read_text().strip() or "0")
            if pid > 0 and pid_alive(pid):
                return
    except Exception:
        pass
    try:
        log_file().parent.mkdir(parents=True, exist_ok=True)
        out = open(log_file(), "a", encoding="utf-8")
        subprocess.Popen(
            [sys.executable, "-m", "agent_status_light.lamp", "--daemon"],
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
        runtime_home().mkdir(parents=True, exist_ok=True)
        tmp = request_file().with_name(f"{request_file().name}.{os.getpid()}.{time.time_ns()}.tmp")
        tmp.write_text(json.dumps({"mode": mode, "ts": time.time()}), encoding="utf-8")
        os.replace(tmp, request_file())
        ensure_daemon()
        return True
    except Exception as e:
        log(f"enqueue failed: {e}")
        return False


def read_request() -> dict:
    try:
        return json.loads(request_file().read_text(encoding="utf-8")) if request_file().exists() else {}
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


def run_done_sequence_on_open_port(f: BinaryIO, port: str, active_key: tuple[str | None, float]) -> bool:
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
    runtime_home().mkdir(parents=True, exist_ok=True)
    if pid_file().exists():
        try:
            old = int(pid_file().read_text().strip() or "0")
            if old and old != os.getpid() and pid_alive(old):
                return 0
        except Exception:
            pass
    pid_file().write_text(str(os.getpid()), encoding="utf-8")
    log(f"daemon started pid={os.getpid()}")
    last_key: tuple[str | None, float] | None = None
    port: str | None = None
    serial_f: BinaryIO | None = None
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
            if pid_file().read_text().strip() == str(os.getpid()):
                pid_file().unlink()
        except Exception:
            pass


def payload_from_stdin() -> dict:
    try:
        raw = sys.stdin.read()
        return json.loads(raw) if raw.strip() else {}
    except Exception:
        return {}


def mode_for_hook(payload: dict, fallback: str | None = None) -> str | None:
    event = payload.get("hook_event_name")
    if event == "pre_approval_request":
        return "red_flash"
    if event == "post_approval_response":
        return "yellow"
    if event in {"pre_llm_call", "pre_tool_call"}:
        return "yellow"
    if event == "transform_llm_output":
        return "done"
    if event == "on_session_start":
        return "off"
    if event == "on_session_end":
        return "done"
    return fallback


def print_help() -> None:
    modes = " ".join(sorted(COMMANDS | {mode: b"" for mode in SEQUENCE_MODES}))
    print(
        "Usage:\n"
        "  agent-status-light MODE\n"
        "  agent-status-light --send-now MODE\n"
        "  agent-status-light --daemon\n\n"
        f"Modes: {modes}\n"
    )


def main(argv: list[str] | None = None) -> int:
    argv = argv or sys.argv
    if len(argv) >= 2 and argv[1] in {"-h", "--help"}:
        print_help()
        return 0
    if len(argv) >= 2 and argv[1] == "--daemon":
        return daemon_loop()
    if len(argv) >= 3 and argv[1] == "--send-now":
        return 0 if send_mode_now(argv[2]) else 1
    if len(argv) >= 2:
        mode = argv[1]
    else:
        mode = mode_for_hook(payload_from_stdin())
    if not mode:
        return 0
    return 0 if enqueue_mode(mode) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
