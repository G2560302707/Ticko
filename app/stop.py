# -*- coding: utf-8 -*-
"""优雅停止采集与主窗口。"""
import os
import subprocess
import sys
import time
import urllib.request

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

BASE_DIR = os.path.dirname(SCRIPT_DIR)
PID_PATH = os.path.join(BASE_DIR, "data", "app.pid")
URL_PATH = os.path.join(BASE_DIR, "data", "url.txt")


def _read(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return (f.read() or "").strip()
    except Exception:
        return ""


def main():
    url = _read(URL_PATH)
    if url:
        try:
            req = urllib.request.Request(url.rstrip("/") + "/api/shutdown", data=b"{}", method="POST")
            urllib.request.urlopen(req, timeout=3).read()
            time.sleep(0.8)
        except Exception:
            pass
    pid = _read(PID_PATH)
    if pid:
        subprocess.run(
            ["taskkill", "/PID", pid, "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=0x08000000,
        )
    subprocess.run(
        ["taskkill", "/IM", "Ticko.exe", "/F"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=0x08000000,
    )
    try:
        if os.path.exists(PID_PATH):
            os.remove(PID_PATH)
    except Exception:
        pass


if __name__ == "__main__":
    main()
