#!/usr/bin/env python3
"""One-time explicit downloads; the running agent never downloads anything."""
import hashlib
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

ROOT=Path(__file__).resolve().parents[1]
REVISION='ae9ad07059c7c739ffaf932226a8fe64ae2620b0'
VOSK_URL='https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip'
# Official Vosk model archive (checked during installation).
VOSK_SHA256='30f26242c4eb449f948e42cb302dd7a686cb29a3423a8367f99ff41780942498'

def main():
    hf=shutil.which('hf');uv=shutil.which('uv')
    if not hf or not uv:raise SystemExit('Install hf and uv first; see README.md.')
    subprocess.run([hf,'download','nvidia/parakeet-tdt-0.6b-v2','parakeet-tdt-0.6b-v2.nemo',
                    '--revision',REVISION,'--local-dir',str(ROOT/'models/parakeet-tdt-0.6b-v2')],check=True)
    if not (ROOT/'models/vosk-model-small-en-us-0.15').is_dir():
        with tempfile.TemporaryDirectory() as folder:
            archive=Path(folder)/'english.zip'
            urllib.request.urlretrieve(VOSK_URL,archive)
            if hashlib.sha256(archive.read_bytes()).hexdigest()!=VOSK_SHA256:
                raise SystemExit('English command model checksum mismatch.')
            with zipfile.ZipFile(archive) as files:
                for name in files.namelist():
                    if Path(name).is_absolute() or '..' in Path(name).parts:raise SystemExit('Invalid model archive.')
                files.extractall(ROOT/'models')
    runtime=ROOT/'.parakeet-venv'
    if not runtime.exists():subprocess.run([uv,'venv',str(runtime),'--python','/usr/bin/python3'],check=True)
    subprocess.run([uv,'pip','install','--python',str(runtime/'bin/python'),'-r',str(ROOT/'requirements-parakeet.txt')],check=True)
    subprocess.run(['/usr/bin/python3','-c','import evdev'],check=True)
    if not __import__('os').access('/dev/uinput',__import__('os').W_OK):
        raise SystemExit('Your desktop user needs /dev/uinput access; see README.md. Do not run the agent as root.')
    print('English dictation installed. Restart hey-gpt.service and hey-gpt-tray.service.')

if __name__=='__main__':main()
