#!/usr/bin/env python3
"""Explicit fetch of pinned official Silero files; never used by daemon."""
import hashlib
import json
from pathlib import Path
import urllib.request

REVISION='1e261b036686cd0017d500ee96acd1c4ba572a9d'
FILES={
    'silero_vad.jit':('src/silero_vad/data/silero_vad.jit','e1122837f4154c511485fe0b9c64455f7b929c96fbb8d79fbdb336383ebd3720'),
    'LICENSE':('LICENSE','2e63e9a38b6e8fc0c7bc37ce174caca1862870856c6daf5697cfb785e925520b')}


if __name__=='__main__':
    target=Path(__file__).resolve().parents[1]/'models/silero-vad'
    target.mkdir(parents=True,exist_ok=True)
    record={'repo':'https://github.com/snakers4/silero-vad','revision':REVISION,'files':{}}
    for name,(remote,expected) in FILES.items():
        url=f'https://raw.githubusercontent.com/snakers4/silero-vad/{REVISION}/{remote}'
        data=urllib.request.urlopen(url,timeout=60).read(4000000)
        if hashlib.sha256(data).hexdigest()!=expected:raise SystemExit('Checksum mismatch: '+name)
        (target/name).write_bytes(data)
        record['files'][name]={'url':url,'sha256':expected,'bytes':len(data)}
    (target/'download.json').write_text(json.dumps(record,indent=2))
    print('Đã lưu mô hình Silero VAD local và giấy phép MIT; không mở micro.')
