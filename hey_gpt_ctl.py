#!/usr/bin/env python3
"""Read or control the same-user local wake listener."""
import argparse
import json
import os
from pathlib import Path
import socket

parser = argparse.ArgumentParser()
parser.add_argument("command", choices=("status", "enable", "disable", "disarm", "wake", "typing", "model-load", "model-unload", "dictation-settings", "reload-typing-templates"), default="status", nargs="?")
parser.add_argument('--autoload',choices=('on','off'))
parser.add_argument('--silence',type=int)
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
            message={'cmd':args.command,'request':'cli'}
            if args.command=='dictation-settings':
                settings=initial['dictation']['settings']
                if args.autoload is not None:settings['autoload']=args.autoload=='on'
                if args.silence is not None:settings['silence_seconds']=args.silence
                message['settings']=settings
            sock.sendall(json.dumps(message).encode()+b'\n')
            while line:=reader.readline():
                response=json.loads(line)
                if response.get('type')=='error':
                    print(json.dumps(response));raise SystemExit(1)
                if response.get('type')=='status':initial=response
                if response.get('type')=='ack':break
            print(json.dumps(initial,ensure_ascii=False,indent=2))
except OSError:
    raise SystemExit("Dịch vụ chưa chạy; không có bộ nghe Hey GPT đang hoạt động.")
