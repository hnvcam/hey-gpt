#!/usr/bin/env python3
"""Explicit install-time download via hf CLI; never called by the listener."""
import hashlib
import json
import os
from pathlib import Path
import subprocess

MODEL_ID = 'nguyenvulebinh/wav2vec2-base-vietnamese-250h'
FILES = ['config.json', 'preprocessor_config.json', 'pytorch_model.bin',
         'vocab.json', 'tokenizer_config.json', 'special_tokens_map.json', 'README.md']


def fetch(destination):
    env = dict(os.environ, HF_HUB_DISABLE_IMPLICIT_TOKEN='1', HF_HUB_DISABLE_TELEMETRY='1')
    info = subprocess.check_output(['hf', 'models', 'info', MODEL_ID, '--expand', 'sha', '--json'], env=env)
    revision = json.loads(info)['sha']
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    subprocess.run(['hf', 'download', MODEL_ID, *FILES, '--revision', revision,
                    '--local-dir', str(destination)], env=env, check=True)
    hashes = {}
    for filename in FILES:
        digest = hashlib.sha256()
        with (destination / filename).open('rb') as source:
            for block in iter(lambda:source.read(1024*1024), b''):
                digest.update(block)
        hashes[filename] = digest.hexdigest()
    (destination / 'download-manifest.json').write_text(json.dumps({
        'model':MODEL_ID, 'revision':revision, 'sha256':hashes,
        'source':'https://huggingface.co/' + MODEL_ID,
        'license':'CC BY-NC 4.0 (see upstream model card)',
    }, indent=2) + '\n')
    print('Đã tải mô hình tiếng Việt, không tải language model 4-gram 904 MB.', flush=True)


if __name__ == '__main__':
    fetch(Path(__file__).resolve().parents[1] / 'models/wav2vec2-base-vietnamese-250h')
