#!/usr/bin/env python3
"""Watch Hermes agent.log and drive the USB tower light from real runtime logs.

Why this exists: shell hooks can be too early/late or unavailable in some Hermes
frontends. agent.log always records the real turn lifecycle, so this monitor uses
it as the source of truth:
  - conversation turn / OpenAI client created  -> yellow (busy)
  - Turn ended                                -> done sequence
                                               (green flash 10s, green 20s, off)

It delegates actual serial control to /Users/chen/bin/hermes_lamp.py, whose daemon
keeps the CH341 serial port open and performs non-blocking writes.
"""
from __future__ import annotations

import os
import re
import subprocess
import time
from pathlib import Path

HOME = Path.home()
HERMES_DIR = HOME / ".hermes"
AGENT_LOG = HERMES_DIR / "logs" / "agent.log"
MONITOR_LOG = HERMES_DIR / "logs" / "lamp-log-monitor.log"
LAMP = HOME / "bin" / "hermes_lamp.py"
PID_FILE = HERMES_DIR / "lamp-log-monitor.pid"

BUSY_PATTERNS = (
    re.compile(r"agent\.turn_context: conversation turn:"),
    re.compile(r"OpenAI client created"),
)
DONE_PATTERNS = (
    re.compile(r"agent\.conversation_loop: Turn ended:"),
)


def log(msg: str) -> None:
    try:
        MONITOR_LOG.parent.mkdir(parents=True, exist_ok=True)
        with MONITOR_LOG.open("a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + msg + "\n")
    except Exception:
        pass


def set_lamp(mode: str, reason: str) -> None:
    try:
        subprocess.Popen(
            [str(LAMP), mode],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )
        log(f"lamp={mode} reason={reason}")
    except Exception as e:
        log(f"failed to set lamp={mode}: {e}")


def read_json(path: Path) -> dict:
    try:
        return __import__("json").loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except Exception:
        return {}


def observed_lamp_mode() -> str | None:
    state_mode = read_json(HERMES_DIR / "lamp-state.json").get("mode")
    request_mode = read_json(HERMES_DIR / "lamp-request.json").get("mode")
    return request_mode or state_mode


def approval_lamp_active() -> bool:
    """Return True when approval/request state should outrank generic busy yellow.

    pre_approval_request is delivered by a shell hook and writes red_flash. While
    Hermes is waiting for the user's allow/deny response, ordinary model/runtime
    log lines can still appear; those must not immediately overwrite red_flash.
    post_approval_response writes yellow, which clears this priority state.
    """
    actual = observed_lamp_mode()
    return actual in {"red", "red_flash"}


def assert_lamp(mode: str, reason: str) -> None:
    actual = observed_lamp_mode()
    if mode == "yellow" and actual in {"red", "red_flash"}:
        log(f"preserve approval lamp={actual}; skip yellow assert reason={reason}")
        return
    if actual != mode:
        set_lamp(mode, f"assert expected={mode} actual={actual} reason={reason}")


def open_at_end(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(exist_ok=True)
    f = path.open("r", encoding="utf-8", errors="replace")
    f.seek(0, os.SEEK_END)
    return f, path.stat().st_ino


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def main() -> int:
    HERMES_DIR.mkdir(parents=True, exist_ok=True)
    if PID_FILE.exists():
        try:
            old = int(PID_FILE.read_text().strip() or "0")
            if old and old != os.getpid() and pid_alive(old):
                log(f"another monitor already running pid={old}; exiting pid={os.getpid()}")
                return 0
        except Exception:
            pass
    PID_FILE.write_text(str(os.getpid()), encoding="utf-8")
    log(f"monitor started pid={os.getpid()} watching={AGENT_LOG}")
    desired = None
    last_assert = 0.0
    f, inode = open_at_end(AGENT_LOG)
    try:
        while True:
            line = f.readline()
            if not line:
                if desired == "yellow" and time.monotonic() - last_assert >= 1.0:
                    last_assert = time.monotonic()
                    assert_lamp("yellow", "busy heartbeat")
                time.sleep(0.1)
                try:
                    st = AGENT_LOG.stat()
                    # Handle log rotation/truncation.
                    if st.st_ino != inode or st.st_size < f.tell():
                        f.close()
                        f, inode = open_at_end(AGENT_LOG)
                        log("reopened rotated/truncated agent.log")
                except FileNotFoundError:
                    try:
                        f.close()
                    except Exception:
                        pass
                    time.sleep(1)
                    f, inode = open_at_end(AGENT_LOG)
                continue

            if any(p.search(line) for p in BUSY_PATTERNS):
                desired = "yellow"
                last_assert = time.monotonic()
                if approval_lamp_active():
                    log(f"preserve approval lamp={observed_lamp_mode()}; skip busy yellow reason={line.strip()[:220]}")
                else:
                    set_lamp("yellow", line.strip()[:220])
            elif any(p.search(line) for p in DONE_PATTERNS):
                desired = "done"
                set_lamp("done", line.strip()[:220])
    finally:
        try:
            f.close()
        except Exception:
            pass
        try:
            if PID_FILE.read_text().strip() == str(os.getpid()):
                PID_FILE.unlink()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
