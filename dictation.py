"""Local dictation state, bounded in-memory audio and isolated workers."""
import asyncio
import base64
import contextlib
import json
import os
import re
import sys
from pathlib import Path
import time
import unicodedata
from commands import (ENGLISH_TRIGGERS, ENGLISH_STOPS, VIETNAMESE_TRIGGERS,
                      VIETNAMESE_STOPS, STOP_PHRASES, STOP_PAUSE, command_text,
                      command_match, vietnamese_command_match)

RATE_BYTES = 32000
MAX_SECONDS = 180


def settings_path():
    return Path(os.environ.get('XDG_CONFIG_HOME', Path.home()/'.config'))/'hey-gpt/dictation.json'


def validate_settings(value):
    if not isinstance(value, dict) or set(value)-{'auto_listen', 'autoload', 'silence_seconds', 'show_transcript'}:
        raise ValueError('invalid-dictation-settings')
    # Migrate the former dictation-only preload preference into the single
    # startup preference. Never keep two independent model/listening switches.
    auto_listen=value.get('auto_listen', value.get('autoload', True))
    silence=value.get('silence_seconds', 5)
    show_transcript=value.get('show_transcript', True)
    if (type(auto_listen) is not bool or ('autoload' in value and type(value['autoload']) is not bool)
            or type(show_transcript) is not bool
            or type(silence) is not int or not 2<=silence<=30):
        raise ValueError('invalid-dictation-settings')
    return {'auto_listen':auto_listen, 'silence_seconds':silence, 'show_transcript':show_transcript}


def load_settings():
    try:
        return validate_settings(json.loads(settings_path().read_text()))
    except (OSError, ValueError):
        return validate_settings({})


def save_settings(value):
    value=validate_settings(value)
    path=settings_path()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temp=path.with_suffix('.tmp')
    temp.write_text(json.dumps(value)+'\n');temp.chmod(0o600);temp.replace(path)
    return value


def terminal_stop(text, language='en'):
    """A final command sentence, never a phrase inside an ordinary sentence."""
    phrases=STOP_PHRASES
    pattern=r'(?:^|(?<=[.!?])\s+)('+ '|'.join(re.escape(p) for p in sorted(phrases)) +r')[.!?\s]*$'
    match=re.search(pattern,text,re.IGNORECASE)
    return (text[:match.start()].rstrip(),match.group(1).lower()) if match else (text,None)


def keyboard_text(text):
    """Single-line Unicode text for pasting; preserve Vietnamese accents."""
    if not isinstance(text,str) or len(text)>20000:
        raise ValueError('invalid-dictation-text')
    text=text.translate(str.maketrans({'’':"'", '‘':"'", '“':'"', '”':'"', '—':'-', '–':'-', '…':'...'}))
    if any(unicodedata.category(c).startswith('C') and c not in '\n\r\t' for c in text):
        raise ValueError('unsupported-dictation-character')
    return unicodedata.normalize('NFC',' '.join(text.split()))


class Recording:
    def __init__(self, silence_seconds=5):
        self.silence_seconds=silence_seconds
        self.audio=bytearray();self.quiet=0.;self.elapsed=0.;self.spoke=False;self.first_speech=None
        self.last_speech_start=None;self.last_pause=0.
    def feed(self, pcm, voiced):
        if voiced and (self.last_speech_start is None or self.quiet+1e-6>=STOP_PAUSE):
            self.last_speech_start=len(self.audio);self.last_pause=self.quiet
        if voiced and self.first_speech is None:self.first_speech=len(self.audio)
        remaining=MAX_SECONDS*RATE_BYTES-len(self.audio)
        self.audio.extend(pcm[:max(0,remaining)])
        dt=len(pcm)/RATE_BYTES;self.elapsed+=dt
        self.quiet=0. if voiced else self.quiet+dt
        self.spoke=self.spoke or voiced
        return self.quiet+1e-6>=self.silence_seconds or self.elapsed+1e-6>=MAX_SECONDS

    def stop_candidate(self):
        """Final isolated short phrase, retained for a missed/busy stop check."""
        if self.last_speech_start is None or self.last_pause+1e-6<STOP_PAUSE:return None
        speech_end=len(self.audio)-round(self.quiet*RATE_BYTES)
        if not 0<speech_end-self.last_speech_start<=6*RATE_BYTES:return None
        cut=max(0,self.last_speech_start-3200)
        return cut,bytes(self.audio[cut:min(len(self.audio),speech_end+12800)])
    def take(self, end=None):
        audio=bytes(self.audio if end is None else self.audio[:max(0,end)])
        self.audio.clear()
        return audio


class EnglishCommands:
    """Unrestricted small vocabulary decoder avoids forced-grammar false wakes."""
    def __init__(self, path):
        import vosk
        vosk.SetLogLevel(-1)
        self.vosk=vosk;self.model=vosk.Model(str(path))
    def decode(self, pcm):
        result=self._decode(pcm)
        text=command_text(result['text'])
        # Vosk's English vocabulary cannot encode Vietnamese. Both decoders
        # still feed the shared policy; grammar confirmation uses supported words.
        phrases={p for p in ENGLISH_TRIGGERS|STOP_PHRASES if p.isascii()}
        if text in phrases and not command_match(result,{text}):
            checked=self._decode(pcm,[*sorted(phrases),'[unk]'])
            if command_match(checked,{text},minimum=.85):result['grammar_confirmed']=text
        return result
    def _decode(self, pcm, grammar=None):
        args=(self.model,16000) if grammar is None else (self.model,16000,json.dumps(grammar))
        rec=self.vosk.KaldiRecognizer(*args);rec.SetWords(True)
        pieces=[]
        for start in range(0,len(pcm),6400):
            if rec.AcceptWaveform(pcm[start:start+6400]):pieces.append(json.loads(rec.Result()))
        pieces.append(json.loads(rec.FinalResult()))
        return {'text':' '.join(p.get('text','') for p in pieces).strip(),
                'result':[w for p in pieces for w in p.get('result',[])]}



class Parakeet:
    """A disposable process makes Unload release the entire CUDA allocation."""
    def __init__(self, root):
        self.root=Path(root);self.proc=None;self.lock=asyncio.Lock()
        self.state='unloaded';self.device=None;self.error=None;self.latency_ms=None
    worker='parakeet_worker.py'
    engine='parakeet-v2-q8_0'
    def snapshot(self):
        return {'state':self.state,'device':self.device,'error':self.error,'latency_ms':self.latency_ms,'engine':self.engine}
    async def load(self):
        async with self.lock:
            if self.proc and self.proc.returncode is None and self.state=='ready':return
            self.state='loading';self.error=None
            try:
                self.proc=await asyncio.create_subprocess_exec(
                    sys.executable,'-B',str(self.root/self.worker),
                    stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL, limit=1024*1024)
                reply=json.loads(await asyncio.wait_for(self.proc.stdout.readline(),180))
                if reply.get('state')!='ready':raise RuntimeError(reply.get('error','parakeet-load-failed'))
                self.device=reply['device'];self.state='ready'
            except BaseException as exc:
                await self._close()
                self.state='error';self.error=str(exc) if isinstance(exc,RuntimeError) else 'parakeet-load-failed'
                raise
    async def transcribe(self, pcm):
        async with self.lock:
            if not self.proc or self.state!='ready':raise RuntimeError('parakeet-not-loaded')
            self.state='transcribing';started=time.monotonic()
            try:
                payload=await self.payload(pcm)
                self.proc.stdin.write(json.dumps(payload).encode()+b'\n')
                await self.proc.stdin.drain()
                line=await asyncio.wait_for(self.proc.stdout.readline(),90)
                reply=json.loads(line)
                if 'text' not in reply:raise RuntimeError('parakeet-transcription-failed')
                self.latency_ms=round((time.monotonic()-started)*1000)
                self.state='ready'
                return reply['text']
            except BaseException:
                await self._close();self.state='error';self.error='parakeet-transcription-failed'
                raise
    async def payload(self, pcm):
        return {'audio':base64.b64encode(pcm).decode()}
    async def _close(self):
        proc,self.proc=self.proc,None
        if proc and proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):proc.terminate()
            try:await asyncio.wait_for(proc.wait(),3)
            except asyncio.TimeoutError:
                with contextlib.suppress(ProcessLookupError):proc.kill()
                await proc.wait()
    async def unload(self):
        # Callers cancel their load/transcription task first. Do not wait behind
        # a three-minute model load just to process an Unload request.
        await self._close();self.state='unloaded';self.device=None;self.error=None
