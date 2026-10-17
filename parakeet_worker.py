#!/usr/bin/env python3
"""Offline NeMo worker. Protocol on stdout; never log audio or transcripts."""
import base64
import contextlib
import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parent
# Library imports/loaders print progress. Keep the protocol separate and quiet.
protocol=sys.stdout
sys.stdout=open(os.devnull,'w')

def emit(value):
    protocol.write(json.dumps(value)+'\n');protocol.flush()

def main():
    config=json.loads((ROOT/'gpu.local.json').read_text())
    uuid=config.get('uuid')
    if not isinstance(uuid,str) or not uuid.startswith('GPU-'):raise RuntimeError('gpu-not-configured')
    os.environ['CUDA_VISIBLE_DEVICES']=uuid
    os.environ['HF_HUB_OFFLINE']='1';os.environ['TRANSFORMERS_OFFLINE']='1'
    runtime=Path(os.environ.get('XDG_RUNTIME_DIR',f'/run/user/{os.getuid()}'))/'hey-gpt'
    os.environ['HF_HOME']=str(runtime/'hf-cache')
    os.environ['NUMBA_CACHE_DIR']=str(runtime/'numba-cache')
    os.environ['TORCH_HOME']=str(runtime/'torch-cache')
    os.environ['MPLCONFIGDIR']=str(runtime/'matplotlib-cache')
    import numpy as np
    import torch
    torch.set_num_threads(2)
    if not torch.cuda.is_available():raise RuntimeError('cuda-unavailable')
    name=torch.cuda.get_device_name(0)
    if 'RTX 4060' not in name:raise RuntimeError('wrong-cuda-gpu')
    from nemo.collections.asr.models import ASRModel
    model=ASRModel.restore_from(str(ROOT/'models/parakeet-tdt-0.6b-v2/parakeet-tdt-0.6b-v2.nemo'),map_location='cuda:0')
    model.eval().to('cuda:0')
    # No CUDA graph reservations; this shares an 8 GB card with wake detection.
    from omegaconf import OmegaConf, open_dict
    decoding=OmegaConf.create(OmegaConf.to_container(model.cfg.decoding,resolve=True))
    with open_dict(decoding):
        decoding.strategy='greedy_batch'
        decoding.greedy.use_cuda_graph_decoder=False
    model.change_decoding_strategy(decoding)
    def transcribe(pcm):
        audio=np.frombuffer(pcm,dtype='<i2').astype(np.float32)/32768.
        with torch.inference_mode(), torch.autocast('cuda',dtype=torch.bfloat16):
            result=model.transcribe([audio],batch_size=1,num_workers=0,verbose=False)
        return result[0].text if hasattr(result[0],'text') else str(result[0])
    transcribe(b'\0'*32000)
    torch.cuda.empty_cache()
    emit({'state':'ready','device':name})
    for line in sys.stdin.buffer:
        if len(line)>8*1024*1024:break
        try:
            request=json.loads(line)
            pcm=base64.b64decode(request['audio'],validate=True)
            if not 0<len(pcm)<=180*32000 or len(pcm)%2:raise ValueError()
            emit({'text':transcribe(pcm)})
        except Exception:
            emit({'error':'transcription-failed'})
        finally:
            # Do not retain the previous recording while waiting for another.
            pcm=None;request=None;line=b''
            torch.cuda.empty_cache()

if __name__=='__main__':
    try:main()
    except Exception as exc:
        if os.environ.get('HEY_GPT_WORKER_DEBUG')=='1':
            import traceback
            traceback.print_exc(file=sys.stderr)
        code=str(exc) if str(exc) in {'gpu-not-configured','cuda-unavailable','wrong-cuda-gpu'} else 'parakeet-load-failed'
        emit({'state':'error','error':code})
