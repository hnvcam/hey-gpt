#!/usr/bin/env python3
"""Rebuild local acoustic references from explicitly recorded dev clips only."""
import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from acoustic_keywords import LAYER, file_hash, trim_pcm
from audio_control import SpeechGate
from wav2vec_recognizer import Wav2VecVietnamese
from keyword_dataset import read_wav, private_json


def main(session):
    os.umask(0o077)
    manifest=json.loads((session/'manifest.json').read_text())
    prompts={r['id']:r for r in manifest['plan']}
    model=ROOT/'models/wav2vec2-base-vietnamese-250h'
    wav=Wav2VecVietnamese(model)
    data={};refs=[]
    for clip in manifest['clips']:
        row=prompts[clip['prompt']]
        if row['split']!='dev' or clip['source']!='filtered':continue
        path=(session/clip['file']).resolve()
        if path.parent!=session.resolve():raise ValueError('Invalid clip path')
        pcm=read_wav(path)
        if hashlib.sha256(pcm).hexdigest()!=clip['sha256']:raise ValueError('Clip hash mismatch')
        # Preserve the original enrollment segmentation. Live gate is softer;
        # reference extraction is deliberately fixed for repeatability.
        gate=SpeechGate(minimum_level=250.)
        count=0
        for offset in range(0,len(pcm),3200):
            _,utterance=gate.feed(pcm[offset:offset+3200])
            if utterance is None or utterance.too_long:continue
            trimmed=trim_pcm(utterance.pcm,wav.np)
            if not 8000 <= len(trimmed) <= 80000:continue
            key=f'{row["id"]}-{count}';count+=1
            data[key]=wav.acoustic_features(trimmed)
            refs.append(dict(key=key,kind=row['kind'] if row['kind'] in ('wake','stop') else 'negative',
                             label=row['text'],prompt=row['id'],source_file=clip['file']))
    if not {'wake','stop','negative'} <= {r['kind'] for r in refs}:
        raise ValueError('Need dev wake, stop and negative recordings')
    parent=ROOT/'data';parent.mkdir(mode=0o700,exist_ok=True)
    target=parent/'keyword-templates'
    pending=parent/('keyword-templates-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    pending.mkdir(mode=0o700)
    wav.np.savez_compressed(pending/'templates.npz',**data)
    meta=dict(schema=1,layer=LAYER,templates=refs,enrollment_manifest=str(session/'manifest.json'),
              model_hashes={name:file_hash(model/name) for name in ('config.json','pytorch_model.bin','vocab.json')},
              features_sha256=file_hash(pending/'templates.npz'),
              policy={'wake_distance':.45,'stop_distance':.30,'minimum_margin':.08},
              evaluation_note='Dev references only. Test distances were previewed in initial development, not a blind test.')
    private_json(pending/'templates.json',meta)
    if target.exists():target.rename(parent/(pending.name+'-previous'))
    pending.rename(target)
    print(f'Đã lưu {len(refs)} mẫu tham chiếu local. Khởi động lại dịch vụ để nạp mẫu mới.')


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('session',type=Path)
    main(parser.parse_args().session.resolve())
