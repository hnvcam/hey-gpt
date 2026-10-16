#!/usr/bin/env python3
"""Read listener state or close local microphone; cannot remotely arm it."""
import argparse
import json
import os
from pathlib import Path
import socket

parser = argparse.ArgumentParser()
parser.add_argument("command", choices=("status", "disarm"), default="status", nargs="?")
args = parser.parse_args()
path = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")) / "hey-gpt/control.sock"
try:
    with socket.socket(socket.AF_UNIX) as sock:
        sock.settimeout(5)
        sock.connect(str(path))
        reader = sock.makefile("rb")
        initial = json.loads(reader.readline())
        if args.command == "status":
            print(json.dumps(initial, ensure_ascii=False, indent=2))
        else:
            sock.sendall(b'{"cmd":"disarm"}\n')
            print(reader.readline().decode().strip())
except OSError:
    raise SystemExit("Dịch vụ chưa chạy; không có bộ nghe Hey GPT đang hoạt động.")
