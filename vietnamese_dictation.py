"""Reuse the wake acoustic model on CUDA; decode its logits with a CPU 4-gram."""
import asyncio
import base64
from dictation import Parakeet, MAX_SECONDS, RATE_BYTES


def acoustic_windows(pcm):
    """Six-second cores with one-second context, bounded to eight seconds/GPU pass.

    Frame centers account for Wav2Vec2 Base's 400-sample receptive field and
    320-sample stride. Context frames are discarded rather than duplicating words.
    """
    samples=len(pcm)//2
    for core in range(0,samples,96000):
        end=min(core+96000,samples)
        start=max(0,core-16000)
        stop=min(end+16000,samples)
        audio=pcm[start*2:stop*2]
        if len(audio)<800:audio+=b'\0'*(800-len(audio))
        yield audio,core-start,end-start


class VietnameseDictation(Parakeet):
    worker='vietnamese_worker.py'
    engine='wav2vec2-vietnamese-4gram'

    def __init__(self, root):
        super().__init__(root)
        self.acoustic=None

    async def payload(self, pcm):
        if not pcm or len(pcm)%2 or len(pcm)>MAX_SECONDS*RATE_BYTES:
            raise ValueError('invalid-vietnamese-audio')
        if self.acoustic is None:raise RuntimeError('wake-model-not-ready')
        parts=[];frames=0;vocab=None
        for audio,begin,end in acoustic_windows(pcm):
            # Each small request releases the wake-worker lock, allowing VAD
            # frames between GPU passes. The large CPU beam search is isolated
            # in its own process and never blocks microphone/VAD handling.
            item=await asyncio.to_thread(self.acoustic.ctc_logits,audio)
            count,width=item['shape']
            if width!=110 or len(item['data'])!=count*width*4:
                raise ValueError('invalid-vietnamese-logits')
            if vocab is not None and width!=vocab:raise ValueError('invalid-vietnamese-logits')
            vocab=width
            lo=max(0,(begin-200+319)//320)
            hi=min(count,max(lo,(end-200+319)//320))
            parts.append(item['data'][lo*width*4:hi*width*4]);frames+=hi-lo
            await asyncio.sleep(0)
        return {'logits':base64.b64encode(b''.join(parts)).decode(),'shape':[frames,vocab]}
