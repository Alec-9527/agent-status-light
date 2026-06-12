#!/usr/bin/env python3
"""Watch an agent log file and drive the status light from runtime events."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

BUSY_PATTERNS = (
    re.compile(r"agent\.turn_context: conversation turn:"),
    re.compile(r"OpenAI client created"),
)
DONE_PATTERNS = (re.compile(r"agent\.conversation_loop: Turn ended:"),)


def runtime_home() -> Path:
    return Path(os.environ.get("AGENT_STATUS_LIGHT_HOME", Path.home() / ".agent-status-light")).expanduser()


def default_agent_log() -> Path:
    return Path.home() / ".hermes" / "logs" / "agent.log"


def agent_log() -> Path:
    return Path(os.environ.get("AGENT_STATUS_LIGHT_AGENT_LOG", default_agent_log())).expanduser()


def monitor_log() -> Path:
    return runtime_home() / "logs" / "log-monitor.log"


def lamp_bin() -> str:
    return os.environ.get("AGENT_STATUS_LIGHT_LAMP_BIN", str(Path.home() / "bin" / "agent-status-light"))


def pid_file() -> Path:
    return runtime_home() / "log-monitor.pid"


def log(msg: str) -> None:
    try:
        monitor_log().parent.mkdir(parents=True, exist_ok=True)
        with monitor_log().open("a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + msg + "\n")
    except Exception:
        pass


def set_lamp(mode: str, reason: str) -> None:
    try:
        subprocess.Popen(
            [lamp_bin(), mode],
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
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except Exception:
        return {}


def observed_lamp_mode() -> str | None:
    request_mode = read_json(runtime_home() / "request.json").get("mode")
    state_mode = read_json(runtime_home() / "state.json").get("mode")
    return request_mode or state_mode


def approval_lamp_active() -> bool:
    return observed_lamp_mode() in {"red", "red_flash"}


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


def monitor_loop() -> int:
    runtime_home().mkdir(parents=True, exist_ok=True)
    if pid_file().exists():
        try:
            old = int(pid_file().read_text().strip() or "0")
            if old and old != os.getpid() and pid_alive(old):
                log(f"another monitor already running pid={old}; exiting pid={os.getpid()}")
                return 0
        except Exception:
            pass
    pid_file().write_text(str(os.getpid()), encoding="utf-8")
    log(f"monitor started pid={os.getpid()} watching={agent_log()}")
    desired = None
    last_assert = 0.0
    f, inode = open_at_end(agent_log())
    try:
        while True:
            line = f.readline()
            if not line:
                if desired == "yellow" and time.monotonic() - last_assert >= 1.0:
                    last_assert = time.monotonic()
                    assert_lamp("yellow", "busy heartbeat")
                time.sleep(0.1)
                try:
                    st = agent_log().stat()
                    if st.st_ino != inode or st.st_size < f.tell():
                        f.close()
                        f, inode = open_at_end(agent_log())
                        log("reopened rotated/truncated agent log")
                except FileNotFoundError:
                    try:
                        f.close()
                    except Exception:
                        pass
                    time.sleep(1)
                    f, inode = open_at_end(agent_log())
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
            if pid_file().read_text().strip() == str(os.getpid()):
                pid_file().unlink()
        except Exception:
            pass


def main(argv: list[str] | None = None) -> int:
    argv = argv or sys.argv
    if len(argv) >= 2 and argv[1] in {"-h", "--help"}:
        print("Usage: agent-status-light-log-monitor")
        return 0
    return monitor_loop()


if __name__ == "__main__":
    raise SystemExit(main())
