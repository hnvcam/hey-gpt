"""Small local audio gate: utterance boundaries and inactivity, no files/network."""
from array import array
from collections import deque
from dataclasses import dataclass
import math
import sys

STOP_PHRASES = frozenset({'hết','kết thúc','dừng lại','done','kết thúc trò chuyện'})


def rms(pcm):
    samples=array('h',pcm)
    if sys.byteorder!='little':samples.byteswap()
    return math.sqrt(sum(int(x)*int(x) for x in samples)/len(samples)) if samples else 0


def stop_command(result, preceding_silence, minimum_pause=1.0):
    """An entire separate utterance, never a substring in an ordinary sentence."""
    text=' '.join(result.get('text','').lower().split())
    words=result.get('result',[])
    return (preceding_silence+1e-6>=minimum_pause and text in STOP_PHRASES
            and len(words)==len(text.split()) and all(w.get('conf',0)>=0.80 for w in words))


@dataclass
class Utterance:
    pcm:bytes
    preceding_silence:float
    peak:float
    too_long:bool


class SpeechGate:
    """100 ms PCM blocks; 0.8 s trailing quiet closes a short utterance."""
    def __init__(self,rate=16000,tail=0.8,max_speech=6.0,minimum_level=100.0):
        self.rate=rate;self.tail=tail;self.max_speech=max_speech
        self.minimum_level=minimum_level
        self.noise=50.0;self.quiet=0.0;self.active=False
        self.frames=[];self.trailing=0.0;self.preceding=0.0;self.peak=0.0;self.length=0.0
        self.preroll=deque(maxlen=5)
        self._prior_quiet=0.0

    def feed(self,pcm,voiced=None):
        dt=len(pcm)/(self.rate*2);level=rms(pcm)
        threshold=max(self.minimum_level,self.noise*3.5)
        voiced=level>=threshold if voiced is None else bool(voiced)
        self.quiet=0.0 if voiced else self.quiet+dt
        if not voiced and not self.active:
            self.noise=max(20,min(300,self.noise*0.98+level*0.02))
        if voiced and not self.active:
            self.active=True;self.frames=list(self.preroll);self.trailing=0.0
            self.preceding=self._prior_quiet;self.peak=0.0;self.length=0.0
        result=None
        if self.active:
            self.length+=dt;self.peak=max(self.peak,level)
            if self.length<=self.max_speech+self.tail:self.frames.append(pcm)
            self.trailing=0.0 if voiced else self.trailing+dt
            if self.trailing+1e-6>=self.tail:
                result=Utterance(b''.join(self.frames),self.preceding,self.peak,self.length-self.trailing>self.max_speech)
                self.active=False;self.frames=[];self.length=0.0
        self.preroll.append(pcm)
        self._prior_quiet=self.quiet
        return voiced,result
