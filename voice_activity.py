"""Stateful Silero voice activity on the already-selected RTX 4060.

No audio files/network here. Keep model state across frames and Voice phase
changes; reset only when the local microphone stream actually starts again.
"""
import hashlib

MODEL_SHA256='e1122837f4154c511485fe0b9c64455f7b929c96fbb8d79fbdb336383ebd3720'


class VoiceActivity:
    def __init__(self, path, torch, np, device):
        from pathlib import Path
        if hashlib.sha256(Path(path).read_bytes()).hexdigest()!=MODEL_SHA256:
            raise ValueError('vad-model-checksum-mismatch')
        self.torch,self.np,self.device=torch,np,device
        self.model=torch.jit.load(str(path),map_location=device).eval().to(device)
        if next(self.model.parameters()).device.type != 'cuda':
            raise RuntimeError('vad-not-on-cuda')
        self.reset()
        self.feed(b'\0'*3200)
        self.reset()

    def reset(self):
        self.model.reset_states()
        self.pending=b''
        self.probability=0.
        self.speech=False
        self.blocks=0

    def feed(self, pcm):
        self.pending+=pcm
        probabilities=[]
        with self.torch.inference_mode():
            while len(self.pending)>=1024:
                frame,self.pending=self.pending[:1024],self.pending[1024:]
                audio=self.np.frombuffer(frame,dtype='<i2').astype('float32')/32768.
                data=self.torch.from_numpy(audio).to(self.device)
                probabilities.append(float(self.model(data,16000).item()))
        self.probability=max(probabilities,default=0.)
        self.speech=self.probability>=.50
        self.blocks+=1
        return self.speech
