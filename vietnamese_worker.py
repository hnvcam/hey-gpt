#!/usr/bin/env python3
"""Offline KenLM beam decoder. Only in-memory logits and text cross the pipe."""
import base64
import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parent


def load_decoder():
    import numpy as np
    from pyctcdecode import build_ctcdecoder
    vocab=json.loads((ROOT/'models/wav2vec2-base-vietnamese-250h/vocab.json').read_text())
    labels=['']*len(vocab)
    for token,index in vocab.items():labels[index]=token
    # pyctcdecode normalizes the CTC pad/blank and word-delimiter labels.
    folder=ROOT/'models/vietnamese-4gram'
    unigrams=(folder/'unigrams.txt').read_text().splitlines()
    alphabet=set(''.join(token for token in vocab if not token.startswith('<') and token!='|'))
    unigrams=[word for word in unigrams if word and all(char in alphabet for char in word)]
    decoder=build_ctcdecoder(labels,str(folder/'vi_lm_4grams.bin'),unigrams=unigrams,alpha=.5,beta=1.)
    return np,decoder


def emit(value):
    print(json.dumps(value,ensure_ascii=False),flush=True)


def main():
    np,decoder=load_decoder()
    emit({'state':'ready','device':'CPU (KenLM 4-gram)'})
    while line:=sys.stdin.buffer.readline(12*1024*1024):
        try:
            if len(line)>=12*1024*1024:raise ValueError()
            request=json.loads(line)
            frames,vocab=request['shape']
            if type(frames) is not int or not 0<frames<=9000 or vocab!=110:raise ValueError()
            data=base64.b64decode(request['logits'],validate=True)
            logits=np.frombuffer(data,dtype='<f4').reshape(frames,vocab)
            if not np.isfinite(logits).all():raise ValueError()
            emit({'text':decoder.decode(logits,beam_width=32)})
        except Exception:
            emit({'error':'vietnamese-decoding-failed'})
        finally:
            line=b'';request=None;data=None;logits=None


if __name__=='__main__':
    os.environ['HF_HUB_OFFLINE']='1'
    try:main()
    except Exception:emit({'state':'error','error':'vietnamese-4gram-load-failed'})
