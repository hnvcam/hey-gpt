#!/usr/bin/env python3
"""Persistent Parakeet v2 Q8 GGUF on the configured RTX 4060; no PyTorch."""
import array
import base64
import ctypes as C
import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parent
MODEL=ROOT/'models/parakeet-tdt-0.6b-v2-q8/tdt-0.6b-v2-q8_0.gguf'


def configure_gpu():
    uuid=json.loads((ROOT/'gpu.local.json').read_text()).get('uuid')
    if not isinstance(uuid,str) or not uuid.startswith('GPU-'):
        raise RuntimeError('gpu-not-configured')
    os.environ['CUDA_VISIBLE_DEVICES']=uuid
    os.environ['PARAKEET_DEVICE']='CUDA0'
    os.environ['GGML_CUDA_DISABLE_GRAPHS']='1'


class Q8Model:
    def __init__(self):
        configure_gpu()
        self.lib=C.CDLL(str(ROOT/'models/parakeet-cpp/build/libhey_gpt_parakeet.so'))
        signatures={
            'parakeet_capi_load':([C.c_char_p],C.c_void_p),
            'parakeet_capi_free':([C.c_void_p],None),
            'parakeet_capi_transcribe_pcm':([C.c_void_p,C.POINTER(C.c_float),C.c_int,C.c_int,C.c_int],C.c_void_p),
            'parakeet_capi_free_string':([C.c_void_p],None),
            'hey_gpt_parakeet_backend':([],C.c_char_p),
            'hey_gpt_parakeet_shutdown':([],None),
            'ggml_backend_dev_by_name':([C.c_char_p],C.c_void_p),
            'ggml_backend_dev_description':([C.c_void_p],C.c_char_p),
        }
        for name,(args,result) in signatures.items():
            func=getattr(self.lib,name);func.argtypes=args;func.restype=result
        if self.lib.hey_gpt_parakeet_backend()!=b'CUDA0':raise RuntimeError('cuda-unavailable')
        dev=self.lib.ggml_backend_dev_by_name(b'CUDA0')
        if not dev:raise RuntimeError('cuda-unavailable')
        self.device=self.lib.ggml_backend_dev_description(dev).decode()
        if 'RTX 4060' not in self.device:raise RuntimeError('wrong-cuda-gpu')
        self.ctx=self.lib.parakeet_capi_load(os.fsencode(MODEL))
        if not self.ctx:raise RuntimeError('parakeet-q8-load-failed')

    def transcribe(self, pcm):
        if not 0<len(pcm)<=180*32000 or len(pcm)%2:raise ValueError('invalid-audio')
        samples=array.array('h');samples.frombytes(pcm)
        if sys.byteorder!='little':samples.byteswap()
        values=array.array('f',(value/32768. for value in samples))
        data=(C.c_float*len(values)).from_buffer(values)
        text=self.lib.parakeet_capi_transcribe_pcm(self.ctx,data,len(values),16000,2)
        if not text:raise RuntimeError('parakeet-q8-transcription-failed')
        try:return C.string_at(text).decode('utf-8')
        finally:self.lib.parakeet_capi_free_string(text)

    def close(self):
        self.lib.parakeet_capi_free(self.ctx);self.ctx=None
        self.lib.hey_gpt_parakeet_shutdown()


def emit(value):
    print(json.dumps(value,ensure_ascii=False),flush=True)


def main():
    model=Q8Model()
    try:
        model.transcribe(b'\0'*32000)
        emit({'state':'ready','device':model.device,'engine':'parakeet-v2-q8_0'})
        while line:=sys.stdin.buffer.readline(8*1024*1024):
            try:
                if len(line)>=8*1024*1024:raise ValueError()
                request=json.loads(line)
                pcm=base64.b64decode(request['audio'],validate=True)
                emit({'text':model.transcribe(pcm)})
            except Exception:emit({'error':'transcription-failed'})
            finally:pcm=None;request=None;line=b''
    finally:model.close()


if __name__=='__main__':
    try:main()
    except Exception as exc:
        allowed={'gpu-not-configured','cuda-unavailable','wrong-cuda-gpu'}
        emit({'state':'error','error':str(exc) if str(exc) in allowed else 'parakeet-q8-load-failed'})
