#!/usr/bin/env python3
"""
Permanent Self-Healing Watchdog Daemon (PPID=1) for VnieVoices Cloud Server.
Detaches completely from SSH sessions via double-fork + os.setsid() so closing SSH
NEVER kills vbee_server.py, and automatically restarts vbee_server.py within 2s if it ever exits.
"""
import os
import sys
import time
import signal
import subprocess
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
SRV_SCRIPT = BASE_DIR / "vbee_server.py"
SRV_LOG = Path("/tmp/vbee_srv.log")
WATCHDOG_LOG = Path("/tmp/vbee_watchdog.log")
PID_FILE = Path("/tmp/vbee_watchdog.pid")


def log_msg(msg: str):
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{stamp}] {msg}\n"
    try:
        with open(WATCHDOG_LOG, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass


def is_port_8890_listening() -> bool:
    try:
        req = urllib.request.Request("http://127.0.0.1:8890/api/health", method="GET")
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            return resp.status == 200
    except Exception:
        return False


def is_vbee_process_running() -> bool:
    try:
        res = subprocess.run(["pgrep", "-f", "vbee_server.py"], capture_output=True, text=True)
        return res.returncode == 0
    except Exception:
        return False


def start_vbee_server():
    log_msg("Starting vbee_server.py daemon...")
    out_f = open(SRV_LOG, "a", encoding="utf-8")
    in_f = open(os.devnull, "r")
    subprocess.Popen(
        [sys.executable, str(SRV_SCRIPT)],
        cwd=str(BASE_DIR),
        stdin=in_f,
        stdout=out_f,
        stderr=out_f,
        start_new_session=True,
        close_fds=True,
    )


def daemonize_and_run():
    if os.name != "nt":
        # Double-fork so PPID becomes 1 (/sbin/docker-init) and SSH exits immediately!
        pid = os.fork()
        if pid > 0:
            sys.exit(0)
        os.setsid()
        signal.signal(signal.SIGHUP, signal.SIG_IGN)
        pid2 = os.fork()
        if pid2 > 0:
            sys.exit(0)

        sys.stdout.flush()
        sys.stderr.flush()
        devnull_fd = os.open(os.devnull, os.O_RDWR)
        os.dup2(devnull_fd, 0)
        os.dup2(devnull_fd, 1)
        os.dup2(devnull_fd, 2)
        if devnull_fd > 2:
            os.close(devnull_fd)

    PID_FILE.write_text(str(os.getpid()), encoding="utf-8")
    log_msg(f"Watchdog daemon started with PID={os.getpid()}, PPID={os.getppid()}")

    while True:
        try:
            if not is_vbee_process_running():
                log_msg("vbee_server.py not running! Respawning immediately...")
                start_vbee_server()
                time.sleep(6)
            elif not is_port_8890_listening():
                # Give it a second check before restarting
                time.sleep(3)
                if not is_port_8890_listening() and not is_vbee_process_running():
                    log_msg("Port 8890 unresponsive and process exited. Respawning...")
                    start_vbee_server()
                    time.sleep(6)
        except Exception as e:
            log_msg(f"Watchdog loop error: {e}")
        time.sleep(3)


if __name__ == "__main__":
    daemonize_and_run()
