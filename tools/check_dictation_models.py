#!/usr/bin/env python3
"""Real local GPU/decoder smoke check with supplied clips; no mic or paste.

Reports timings, devices and success flags only, never audio or transcripts.
"""
import argparse
import asyncio
import json
from pathlib import Path
import sys
import time
import wave

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from dictation import Parakeet
from vietnamese_dictation import VietnameseDictation
from wake_worker import WakeModels


def read_clip(path):
    with wave.open(str(path)) as wav:
        if (wav.getframerate(),wav.getnchannels(),wav.getsampwidth())!=(16000,1,2):
            raise ValueError('Expected 16 kHz mono PCM16 WAV')
        if not 0<wav.getnframes()<=16000*180:raise ValueError('Invalid clip duration')
        return wav.readframes(wav.getnframes())


async def check(args):
    acoustic=WakeModels(ROOT/'models/wav2vec2-base-vietnamese-250h')
    english=Parakeet(ROOT);vietnamese=VietnameseDictation(ROOT)
    try:
        await asyncio.gather(asyncio.to_thread(acoustic.load),english.load(),vietnamese.load())
        vietnamese.acoustic=acoustic
        report={'gpu':acoustic.device_name,'english_engine':english.engine,'vietnamese_engine':vietnamese.engine}
        for name,path,model in (('english',args.english_wav,english),('vietnamese',args.vietnamese_wav,vietnamese)):
            started=time.monotonic()
            text=await model.transcribe(read_clip(path))
            if not text.strip():raise RuntimeError(name+' transcription returned empty text')
            report[name]={'nonempty':True,'latency_ms':round((time.monotonic()-started)*1000)}
            if name=='vietnamese':
                report[name]['accented_unicode']=any(ord(c)>127 for c in text)
                if not report[name]['accented_unicode']:raise RuntimeError('Vietnamese reference returned no accented text')
            text=''
        await asyncio.to_thread(acoustic.vad.feed,b'\0'*3200)
        report['vad_after_transcription']=True
        print(json.dumps(report,ensure_ascii=False,indent=2))
    finally:
        await asyncio.gather(english.unload(),vietnamese.unload())
        await asyncio.to_thread(acoustic.close)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--english-wav',type=Path,required=True)
    parser.add_argument('--vietnamese-wav',type=Path,required=True)
    asyncio.run(check(parser.parse_args()))
