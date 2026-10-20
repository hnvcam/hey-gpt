#!/usr/bin/env python3
"""Register reviewed workspace app with user systemd and Chrome; no root."""
import argparse
import json
import os
from pathlib import Path
import shlex
import subprocess

ROOT = Path(__file__).resolve().parent
parser = argparse.ArgumentParser()
parser.add_argument("--config-dir", type=Path, default=Path(os.environ.get("XDG_CONFIG_HOME", Path.home()/".config")))
parser.add_argument("--data-dir", type=Path, default=Path(os.environ.get("XDG_DATA_HOME", Path.home()/".local/share")))
parser.add_argument("--stage-only", action="store_true", help="Write files without starting/enabling systemd")
args = parser.parse_args()
python = ROOT / ".venv/bin/python"
if not python.exists():
    raise SystemExit("Tạo .venv và cài requirements.txt trước; xem README.md.")
subprocess.run([str(python), "-c", "import torch, transformers"], check=True)
identity = json.loads((ROOT/"identity.json").read_text())
# Read only the last-used profile name, never browser credentials or cookies.
browser_config = ROOT / 'browser.local.json'
if not browser_config.exists():
    try:
        local_state = json.loads((args.config_dir / 'google-chrome/Local State').read_text())
        profile = local_state.get('profile', {}).get('last_used', 'Default')
    except (OSError, ValueError):
        profile = 'Default'
    browser_config.write_text(json.dumps({'profile': profile}) + '\n')
    browser_config.chmod(0o600)
host = ROOT / "native-host.sh"
host.write_text("#!/bin/sh\nexec /usr/bin/python3 " + shlex.quote(str(ROOT/"native_host.py")) + ' "$@"\n')
host.chmod(0o700)

def unit_quote(path):
    # systemd specifiers are expanded even inside quotes.
    return '"' + str(path).replace("%", "%%").replace("\\", "\\\\").replace('"','\\"') + '"'

unit = (ROOT/"systemd/hey-gpt.service.in").read_text()
unit = unit.replace("@PYTHON@",unit_quote(python)).replace("@APP@/daemon.py",unit_quote(ROOT/"daemon.py"))
dictation_config=args.config_dir/'hey-gpt'
dictation_config.mkdir(mode=0o700,parents=True,exist_ok=True)
unit=unit.replace('@DICTATION_CONFIG@',unit_quote(dictation_config))
service = args.config_dir/"systemd/user/hey-gpt.service"
tray_service = args.config_dir/"systemd/user/hey-gpt-tray.service"
manifest = args.config_dir/"google-chrome/NativeMessagingHosts/org.local.hey_gpt.json"
for path in (service,tray_service,manifest):
    path.parent.mkdir(parents=True, exist_ok=True)
service.write_text(unit)
tray_unit = (ROOT/"systemd/hey-gpt-tray.service.in").read_text().replace("@APP@/tray.py",unit_quote(ROOT/"tray.py"))
tray_service.write_text(tray_unit)
manifest.write_text(json.dumps({"name":"org.local.hey_gpt", "description":"Hey GPT local Vietnamese wake bridge",
    "path":str(host),"type":"stdio", "allowed_origins":[f"chrome-extension://{identity['extension_id']}/"]},indent=2)+"\n")
manifest.chmod(0o600)
launcher = args.data_dir / "applications/hey-gpt.desktop"
launcher.parent.mkdir(parents=True, exist_ok=True)
icon = str(ROOT / "icons/listening.png").replace("\\", "\\\\").replace("\n", "\\n").replace("\r", "\\r")
launcher.write_text((ROOT / "systemd/hey-gpt.desktop.in").read_text().replace("@ICON@", icon))
if not args.stage_only:
    subprocess.run(["systemctl","--user","daemon-reload"],check=True)
    subprocess.run(["systemctl","--user","enable","hey-gpt.service","hey-gpt-tray.service"],check=True)
    subprocess.run(["systemctl","--user","restart","hey-gpt.service","hey-gpt-tray.service"],check=True)
print("Đã ghi dịch vụ:",service)
print("Đã ghi biểu tượng và bảng điều khiển:",tray_service)
print("Đã đăng ký cầu nối Chrome:",manifest)
print("Đã thêm Hey GPT vào danh sách ứng dụng:",launcher)
print("Thư mục Load unpacked:",ROOT/"extension")
print("Extension ID:",identity["extension_id"])
print("Tùy chọn tự nghe trong Cài đặt điều khiển cả nghe khi đăng nhập và nạp mô hình.")
