#!/usr/bin/env python3
"""Offline wake listener and status hub. No HTTP client or saved audio."""
import argparse
import asyncio
import contextlib
import json
import os
from pathlib import Path
import secrets
import signal
import shutil
import socket
import struct
import time
from wav2vec_recognizer import wake_match, load_wake_profile
from wake_worker import WakeModels
from audio_control import PersonalSpeechGate, SpeechGate, stop_command, rms
from acoustic_keywords import acoustic_accept
from conversation_idle import ConversationIdle
from dictation import ENGLISH_TRIGGERS, ENGLISH_STOPS, VIETNAMESE_TRIGGERS, VIETNAMESE_STOPS, STOP_PAUSE, command_text, terminal_stop, MAX_SECONDS, Parakeet, EnglishCommands, Recording, command_match, keyboard_text, load_settings, save_settings
from vietnamese_dictation import VietnameseDictation
from diagnostics import trace, trace_error

BASE = Path(__file__).resolve().parent
MAX_FRAME = 4096
BROWSER_ERRORS = frozenset({
    'browser-operation-failed','voice-end-failed','rearm-failed',
    'voice-ended-unexpectedly','voice-end-unconfirmed','browser-notice',
    'browser-already-recording','composer-has-draft','composer-not-found',
    'voice-button-missing-or-ambiguous','setup-required','target-tab-changed',
    'voice-not-open','voice-transition-pending','wrong-origin','no-page-result',
    'review-browser-permission-limit-or-start-button','another-chrome-connected',
    'browser-start-failed','browser-transition-timeout','voice-not-ready',
})


def runtime_dir():
    return Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")) / "hey-gpt"


async def command(*args):
    proc = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), 2)
    except BaseException:
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
        await proc.wait()
        raise
    if proc.returncode:
        raise RuntimeError("session-check-failed")
    return out.decode()


async def unlocked_session(expected=None):
    """Fail closed if logind cannot establish one local unlocked Wayland session."""
    try:
        rows = (await command("loginctl", "list-sessions", "--no-legend")).splitlines()
        candidates = []
        for row in rows:
            fields = row.split()
            if len(fields) < 2 or fields[1] != str(os.getuid()):
                continue
            sid = fields[0]
            info = await command("loginctl", "show-session", sid, "-p", "Active",
                                 "-p", "Remote", "-p", "Type", "-p", "LockedHint")
            props = dict(line.split("=", 1) for line in info.splitlines() if "=" in line)
            if props == {"Active": "yes", "Remote": "no", "Type": "wayland", "LockedHint": "no"}:
                candidates.append(sid)
        return candidates[0] if len(candidates) == 1 and (expected is None or candidates[0] == expected) else None
    except (OSError, RuntimeError, asyncio.TimeoutError):
        return None


class Listener:
    def __init__(self, max_seconds=0, source=None, silence_seconds=15, wav2vec_path=None):
        self.source = source
        self.max_seconds = max_seconds
        self.clients = set()
        self.owner = None
        self.task = None
        self.state = "DISARMED"
        self.detail = "local-microphone-closed"
        self.mic = False
        self.last_wake = 0
        self.control = asyncio.Lock()
        self.browser = None
        self.browser_state = "IDLE"
        self.browser_detail = ""
        self.last_error = None
        self.last_voice_stop = None
        self.last_remote_audio = None
        self.remote_audio_updated = None
        self.stop_echo_suppressed = 0
        self.enabled = False
        self.stopping = False
        self.wake_id = None
        self.chimed_session = None
        self.launch_task = None
        self.chime_task = None
        self.ready_sound = {"state": "idle", "count": 0}
        self.phase = "wake"
        self.phase_since = 0.0
        self.session = None
        self.last_activity = 0.0
        self.reply_guard = ConversationIdle()
        self.silence_seconds = silence_seconds
        self.audio_level = 0
        self.wake_checks = 0
        self.wake_matches = 0
        self.last_wake_check = "none"
        self.wav2vec_path = wav2vec_path or BASE / "models/wav2vec2-base-vietnamese-250h"
        self.wav2vec = None
        self.wake_worker = None
        self.vad = None
        self.capture_starts = 0
        self.extension_version = 'unknown'
        self.voice_events = {}
        self.wake_profile = load_wake_profile(BASE / 'wake.local.json')
        self.wav2vec_loading = None
        self.recognition_epoch = 0
        self.recognition_jobs = set()
        self.engine_busy = set()
        self.last_recognizer = "none"
        self.dictation_settings = load_settings()
        self.parakeet = Parakeet(BASE)
        self.vietnamese = VietnameseDictation(BASE)
        self.dictation_language = 'en'
        self.model_task = None
        self.dictation_job = None
        self.preview_job = None
        self.preview_at = 0.
        self.preview_text = ''
        self.preview_seconds = 0.
        self.preview_revision = 0
        self.recording = None
        self.english = None
        self.english_state = 'not-loaded'
        self.english_loading = None
        self.english_busy = False
        self.english_job = None
        self.english_stats = {'checks':0,'matches':0,'vosk_matches':0,'parakeet_matches':0,
                              'personal_matches':0,'errors':0,'last_engine':'none','latency_ms':0}
        self.keyboard = None
        self.dictation_error = None
        self.dictation_count = 0
        self.dictation_id=None
        self.final_stop_candidate=None
        self.last_finish_reason=None
        self.trace_state=None
        self.engines = {name: {"state": "not-loaded",
                               "checks": 0, "matches": 0, "skipped": 0, "latency_ms": 0}
                        for name in ("wav2vec2",)}


    def snapshot(self):
        return {"type": "status", "state": self.state, "detail": self.detail,
                "local_mic_open": self.mic, "enabled": self.enabled,
                "browser_connected": self.browser is not None, "wake_id": self.wake_id,
                "browser_state": self.browser_state, "browser_detail": self.browser_detail,
                "last_error": self.last_error, "listen_mode": self.phase,
                "dictation": {**self.parakeet.snapshot(), "settings":dict(self.dictation_settings),
                              "vietnamese":self.vietnamese.snapshot(), "language":self.dictation_language,
                              "commands":self.english_state,
                              "personal_templates":bool(self.wav2vec and getattr(self.wav2vec,'typing_templates',None)),
                              "command_detection":dict(self.english_stats), "phase":self.phase if self.phase.startswith('typing') else 'idle',
                              "error":self.dictation_error or self.parakeet.error,
                              "completed":self.dictation_count,
                              "last_finish_reason":self.last_finish_reason,
                              "preview_revision":self.preview_revision,
                              "preview_seconds":self.preview_seconds,
                              "preview_busy":bool(self.preview_job and not self.preview_job.done()),
                              "recorded_seconds":round(self.recording.elapsed,1) if self.recording else 0},
                "ready_sound": dict(self.ready_sound), "last_voice_stop": self.last_voice_stop,
                "stop_echo_suppressed": self.stop_echo_suppressed,
                "silence_seconds": self.silence_seconds,
                "reply_ui_state": self.reply_guard.state_at(time.monotonic()),
                "idle_remaining": self.reply_guard.remaining(time.monotonic(),self.last_activity,self.silence_seconds),
                "recognizers": self.engines, "last_recognizer": self.last_recognizer,
                "personal_wake_phrases": len(self.wake_profile),
                "extension_version": self.extension_version,
                "voice_events": self.voice_events,
                "voice_activity": {"state": "ready" if self.vad else "not-loaded",
                                   "device": self.engines['wav2vec2'].get('device'),
                                   "speech": bool(self.vad and self.vad.speech),
                                   "probability": round(self.vad.probability,3) if self.vad else 0.,
                                   "capture_starts": self.capture_starts},
                "diagnostics": {"audio_level": self.audio_level,
                                "wake_checks": self.wake_checks, "wake_matches": self.wake_matches,
                                "last_wake_check": self.last_wake_check}, "at": int(time.time())}

    def send(self, writer, message):
        if not writer.is_closing():
            writer.write(json.dumps(message, separators=(",", ":")).encode() + b"\n")

    def publish(self, state, detail, mic=False):
        transition=(state,detail,mic)
        if transition!=self.trace_state:
            trace('daemon','state-changed',state=state,detail=detail,microphone_open=mic)
            self.trace_state=transition
        self.state, self.detail, self.mic = state, detail, mic
        payload = self.snapshot()
        folder = runtime_dir()
        folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        temp = folder / "status.tmp"
        temp.write_text(json.dumps(payload) + "\n")
        temp.chmod(0o600)
        temp.replace(folder / "status.json")
        for writer in tuple(self.clients):
            with contextlib.suppress(ConnectionError):
                self.send(writer, payload)

    async def disarm(self, detail="user-disarmed"):
        # Chrome acknowledges our disable by sending another disarm. Keep the
        # completed unload visible after that acknowledgement arrives.
        if detail == 'user-disarmed' and self.detail == 'models-unloaded':
            detail = 'models-unloaded'
        self.enabled = False
        self.recognition_epoch += 1
        await self.cancel_dictation()
        self.reply_guard.reset()
        self.wake_id = None
        for job in (self.launch_task, self.chime_task):
            if job and not job.done():
                job.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await job
        if self.task and self.task is not asyncio.current_task():
            self.task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.task
        self.task, self.owner = None, None
        self.phase, self.session = "wake", None
        self.publish("DISARMED", "unloading-models")
        await self.release_models()
        if detail in BROWSER_ERRORS:
            self.last_error = {"code": detail, "at": int(time.time())}
            print(json.dumps({"event":"browser-error", **self.last_error}), flush=True)
        self.publish("DISARMED", "models-unloaded" if detail in {
            "user-disarmed", "unloading-models", "models-unloaded"} else detail)

    async def startup(self):
        if self.dictation_settings['auto_listen']:
            await self.arm()

    async def arm(self, writer=None):
        if self.task and not self.task.done():
            return
        sid = await unlocked_session()
        if not sid:
            self.publish("ERROR", "screen-locked-or-session-unavailable")
            return
        self.owner = None
        self.enabled = True
        self.browser_detail = ""
        self.browser_state = "IDLE"
        self.phase, self.session = "wake", None
        self.phase_since = time.monotonic()
        self.publish("ARMING", "loading-offline-model")
        self.task = asyncio.create_task(self.listen(None, sid))

    async def launch_browser(self):
        """Launch in the desktop user's service manager, outside the audio sandbox."""
        try:
            chrome = shutil.which('google-chrome')
            if not chrome:
                raise RuntimeError('browser-start-failed')
            config = BASE / 'browser.local.json'
            profile = json.loads(config.read_text()).get('profile', 'Default') if config.exists() else 'Default'
            if not isinstance(profile, str) or not profile or '/' in profile or profile.startswith('-'):
                raise RuntimeError('browser-start-failed')
            await command('systemd-run', '--user', '--collect', '--quiet', '--no-block',
                          '--unit=hey-gpt-chrome-' + secrets.token_hex(6),
                          '--property=PartOf=graphical-session.target',
                          chrome, '--profile-directory=' + profile, 'https://chatgpt.com/')
        except asyncio.CancelledError:
            raise
        except Exception:
            if self.enabled and self.phase == 'opening':
                self.return_to_wake('browser-start-failed')

    def return_to_wake(self, detail):
        if self.chime_task and not self.chime_task.done():
            self.chime_task.cancel()
        self.recognition_epoch += 1
        self.wake_id = None
        self.phase, self.session = 'wake', None
        self.phase_since = time.monotonic()
        self.browser_state, self.browser_detail = 'IDLE', detail
        if detail in BROWSER_ERRORS:
            self.last_error = {'code': detail, 'at': int(time.time())}
        self.publish('LISTENING', detail, self.mic)

    def deliver_wake(self, writer):
        self.send(writer, {'type': 'wake', 'id': self.wake_id, 'at': int(time.time()),
                           'expires': int(time.time() + max(0, 90 - (time.monotonic() - self.phase_since)))})

    async def begin_wake(self, writer=None):
        self.wake_id = secrets.token_hex(16)
        self.phase = 'opening'
        self.phase_since = self.last_wake = time.monotonic()
        self.publish('OPENING', 'opening-chrome-voice-local-still-listening', self.mic)
        target = self.browser or writer
        if target:
            self.deliver_wake(target)
        else:
            self.launch_task = asyncio.create_task(self.launch_browser())

    async def play_ready_chime(self, token):
        if not self.enabled or self.phase != "conversation" or self.session != token:
            return
        try:
            await command('paplay', '--client-name=Hey GPT ready', str(BASE / 'sounds/ready.wav'))
            self.ready_sound.update(state='played', count=self.ready_sound['count'] + 1, at=int(time.time()))
            self.publish(self.state, self.detail, self.mic)
        except asyncio.CancelledError:
            raise
        except Exception:
            self.ready_sound['state'] = 'error'
            self.last_error = {'code': 'ready-sound-unavailable', 'at': int(time.time())}
            self.publish(self.state, self.detail, self.mic)

    def browser_disconnected(self):
        self.browser = None
        self.browser_state = 'IDLE'
        if self.phase.startswith('typing'):
            self.publish(self.state, self.detail, self.mic)
        elif self.enabled:
            # Closing Chrome is not an instruction to stop the local wake mic.
            self.return_to_wake('browser-disconnected-local-still-listening')
        else:
            self.publish(self.state, self.detail, self.mic)

    async def dispatch(self, msg, writer):
        action = msg.get("cmd")
        if self.stopping and action not in {"status", "disarm", "disable"}:
            self.send(writer, {"type": "error", "detail": "service-stopping"})
            return
        if action == "register":
            if self.browser is not None and self.browser is not writer:
                self.send(writer, {"type": "error", "detail": "another-chrome-connected"})
                return
            self.browser = writer
            version = msg.get('extension_version')
            if isinstance(version,str) and version and len(version)<=24 and all(c in '0123456789.' for c in version):
                self.extension_version=version
            # Popup polling must not erase the cause of an automatic shutdown.
            self.publish(self.state, self.detail, self.mic)
            if self.enabled and self.phase == "opening" and self.wake_id:
                self.deliver_wake(writer)
        elif action == "arm" and writer is self.browser:
            await self.arm(writer)
        elif action in {"disarm", "disable"}:
            reason = msg.get("reason") if writer is self.browser else None
            await self.disarm(reason if reason in BROWSER_ERRORS else "user-disarmed")
            if self.browser and action == "disable":
                self.send(self.browser, {"type": "control", "action": "disable"})
        elif action == "enable" or (action == 'model-load' and writer is not self.browser):
            await self.arm()
        elif action == 'model-unload' and writer is not self.browser:
            await self.unload_models()
        elif action == 'wake':
            # Same-user manual fallback follows the same fresh-wake rules. This
            # command is deliberately absent from the extension/native protocol.
            if (self.enabled and self.mic and self.phase == 'wake'
                    and await unlocked_session()):
                await self.begin_wake()
            else:
                self.send(writer, {'type': 'error', 'detail': 'assistant-not-listening'})
        elif action in {'typing', 'settings', 'dictation-settings', 'reload-typing-templates'} and writer is not self.browser:
            if action == 'reload-typing-templates':
                try:
                    if not self.wav2vec:raise RuntimeError('wake-model-not-ready')
                    await asyncio.to_thread(self.wav2vec.reload_typing_templates)
                    self.publish(self.state,self.detail,self.mic)
                except Exception:
                    self.send(writer,{'type':'error','detail':'typing-templates-reload-failed'})
            elif action in {'settings', 'dictation-settings'}:
                previous = self.dictation_settings['auto_listen']
                try:
                    self.dictation_settings = save_settings(msg.get('settings'))
                except (ValueError, OSError):
                    self.send(writer, {'type':'error','detail':'invalid-or-unwritable-dictation-settings'})
                    return
                if self.dictation_settings['auto_listen'] != previous:
                    if self.dictation_settings['auto_listen']:
                        await self.arm()
                    else:
                        await self.unload_models()
                self.publish(self.state,self.detail,self.mic)
            elif self.enabled and self.mic and self.phase=='wake' and await unlocked_session():
                self.begin_dictation()
            else:
                self.send(writer,{'type':'error','detail':'assistant-not-listening'})
        elif action == "report" and writer is self.browser:
            allowed = {"IDLE", "VOICE", "DICTATION", "WAITING", "NEEDS_ACTION", "STOPPED"}
            if msg.get("state") in allowed:
                self.browser_state = msg["state"]
                detail = msg.get("detail")
                if detail in BROWSER_ERRORS:
                    self.browser_detail = detail
                    if self.browser_state == "NEEDS_ACTION":
                        self.last_error = {"code": detail, "at": int(time.time())}
                elif self.browser_state in {"IDLE","VOICE"}:
                    self.browser_detail = ""
                elif self.browser_state == 'WAITING' and detail in {'response-generating','voice-start-unavailable'}:
                    self.browser_detail = detail
                self.publish(self.state, self.detail, self.mic)
        elif action == "session" and writer is self.browser and self.enabled:
            token = msg.get("session")
            fresh_wake = self.phase == "opening" and self.wake_id and msg.get("wake_id") == self.wake_id
            explicit_attach = self.phase == "wake" and msg.get("existing") is True
            if (fresh_wake or explicit_attach) and isinstance(token, str) and 8 <= len(token) <= 64:
                self.session = token
                self.chimed_session = None
                if msg.get("existing") is True and not self.wake_id:
                    self.wake_id = token
                self.phase = "conversation"
                self.reply_guard.reset()
                self.voice_events = {}
                self.last_remote_audio = self.remote_audio_updated = None
                self.phase_since = self.last_activity = time.monotonic()
                self.browser_state = "VOICE"
                self.publish("CONVERSATION", "listening-for-stop-commands", self.mic)
        elif action == 'voice-ready' and writer is self.browser:
            if (self.enabled and self.phase == 'conversation' and self.wake_id
                    and msg.get('session') == self.session and self.chimed_session != self.session):
                if await unlocked_session():
                    self.chimed_session = self.session
                    self.ready_sound["state"] = "pending"
                    self.chime_task = asyncio.create_task(self.play_ready_chime(self.session))
                else:
                    await self.disarm('screen-locked-or-session-unavailable')
        elif action == "activity" and writer is self.browser:
            if self.phase == "conversation" and msg.get("session") == self.session:
                now=time.monotonic()
                from native_host import clean_voice_events
                self.voice_events=clean_voice_events(msg.get('voice_events'))
                playback=self.voice_events.get('playback_state')
                self.remote_audio_updated=now
                if playback=='busy':self.last_remote_audio=now
                state=msg.get('ui_state')
                # An older adapter's absence of a busy flag is not proof of idle.
                if state not in {'idle','busy','unknown'}:
                    state='busy' if msg.get('busy') is True else 'unknown'
                if state=='idle' and playback!='quiet':state='unknown'
                if playback=='busy':state='busy'
                self.reply_guard.update(state,now)
                if state=='busy':self.last_activity=now
        elif action == 'stop-vetoed' and writer is self.browser:
            if self.enabled and self.phase=='closing' and msg.get('session')==self.session:
                self.phase='conversation'
                self.reply_guard.reset()
                self.last_activity=time.monotonic()
                if self.last_voice_stop:self.last_voice_stop['vetoed']=True
                self.publish('CONVERSATION','close-vetoed-activity-unverified',self.mic)
        elif action == "resume" and writer is self.browser:
            if self.enabled and self.phase in {"conversation", "closing"} and msg.get("session") == self.session:
                if self.chime_task and not self.chime_task.done():
                    self.chime_task.cancel()
                self.wake_id = None
                self.phase, self.session = "wake", None
                self.phase_since = time.monotonic()
                self.browser_state = "IDLE"
                self.publish("LISTENING", "offline-hey-gpt-only", self.mic)
        elif action == 'defer' and writer is self.browser:
            # A fresh wake met a busy composer. Keep the same local capture;
            # do not queue/retry opening Voice or turn off either model.
            if self.enabled and self.phase == 'opening':
                self.wake_id = None
                self.recognition_epoch += 1
                self.phase,self.session = 'wake',None
                self.phase_since = time.monotonic()
                self.browser_state = 'WAITING'
                self.publish('LISTENING','chrome-busy-local-still-listening',self.mic)
        elif action == 'detach' and writer is self.browser:
            if self.enabled and not self.phase.startswith('typing'):
                self.return_to_wake('browser-disconnected-local-still-listening')
        elif action == 'dictation-preview' and writer is not self.browser:
            # The transcript is sent only to this local requester, never to the
            # status broadcast, status.json, logs, or the Chrome native host.
            self.send(writer, {'type':'dictation-preview','text':self.preview_text})
        elif action == "status":
            self.send(writer, self.snapshot())
        else:
            self.send(writer, {"type": "error", "detail": "unsupported-command"})

    async def prepare_english(self):
        self.english_state='loading'
        loading = asyncio.create_task(asyncio.to_thread(EnglishCommands, BASE/'models/vosk-model-small-en-us-0.15'))
        try:
            self.english=await asyncio.shield(loading)
            self.english_state='ready'
        except asyncio.CancelledError:
            # A thread cannot be cancelled. Let construction finish and discard
            # its result before acknowledging Off, so Vosk cannot appear later.
            await asyncio.gather(loading, return_exceptions=True)
            raise
        except Exception:
            self.english_state='unavailable'
        self.publish(self.state,self.detail,self.mic)

    def start_model_load(self):
        if self.detail == 'models-unloaded':
            self.detail = 'local-microphone-closed'
        if not self.model_task or self.model_task.done():
            self.model_task=asyncio.create_task(self.load_dictation_model())
        return self.model_task

    async def load_dictation_model(self):
        self.publish(self.state,self.detail,self.mic)
        try:
            # Await both outcomes. An early failure must not leave its sibling
            # loading in the background after Off has released the workers.
            results=await asyncio.gather(self.parakeet.load(),self.vietnamese.load(),return_exceptions=True)
            for result in results:
                if isinstance(result,Exception):trace_error('daemon','model-load-error',result)
        except asyncio.CancelledError:raise
        except Exception as exc:trace_error('daemon','model-load-error',exc)
        self.publish(self.state,self.detail,self.mic)

    async def ensure_keyboard(self):
        if self.keyboard and self.keyboard.returncode is None:return
        self.keyboard=await asyncio.create_subprocess_exec(
            '/usr/bin/python3','-B',str(BASE/'keyboard_input.py'),
            stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.DEVNULL)
        try:
            reply=json.loads(await asyncio.wait_for(self.keyboard.stdout.readline(),5))
            if reply.get('state')!='ready':raise RuntimeError('keyboard-input-unavailable')
        except BaseException:
            await self.close_keyboard()
            raise

    async def close_keyboard(self):
        proc,self.keyboard=self.keyboard,None
        if proc and proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):proc.terminate()
            await proc.wait()

    def begin_dictation(self, language='en'):
        if not self.enabled or self.phase!='wake':return
        if language not in {'en','vi'}:return
        self.dictation_language=language
        self.recognition_epoch+=1
        self.phase='typing-loading';self.phase_since=time.monotonic()
        self.dictation_error=None
        self.dictation_id=secrets.token_hex(4)
        self.final_stop_candidate=None;self.last_finish_reason=None
        trace('daemon','dictation-start',dictation_id=self.dictation_id)
        self.preview_text='';self.preview_seconds=0.;self.preview_at=0.;self.preview_revision=0
        self.publish('TYPING_LOADING','preparing-'+('vietnamese' if language=='vi' else 'english')+'-dictation',self.mic)
        self.dictation_job=asyncio.create_task(self.prepare_dictation())

    async def prepare_dictation(self):
        try:
            await asyncio.shield(self.start_model_load())
            if self.parakeet.state!='ready':raise RuntimeError('parakeet-load-failed')
            if self.dictation_language=='vi' and (self.vietnamese.state!='ready' or self.wav2vec is None):
                raise RuntimeError('vietnamese-model-not-ready')
            await self.ensure_keyboard()
            if not self.enabled or self.phase!='typing-loading':return
            if not await unlocked_session():raise RuntimeError('screen-locked-or-session-unavailable')
            # Capture starts after the cue so its speaker audio cannot enter text.
            await command('paplay','--client-name=Hey GPT dictation ready',str(BASE/'sounds/ready.wav'))
            if not self.enabled or self.phase!='typing-loading':return
            if not await unlocked_session():raise RuntimeError('screen-locked-or-session-unavailable')
            self.ready_sound.update(state='played',count=self.ready_sound['count']+1,mode='dictation',at=int(time.time()))
            self.recording=Recording(self.dictation_settings['silence_seconds'])
            self.phase='typing-recording';self.phase_since=time.monotonic()
            self.publish('TYPING_RECORDING','speak-vietnamese-dung-nhap-or-silence' if self.dictation_language=='vi' else 'speak-english-stop-typing-or-silence',self.mic)
        except asyncio.CancelledError:raise
        except Exception as exc:
            trace_error('daemon','dictation-prepare-error',exc,dictation_id=self.dictation_id)
            self.dictation_failed('dictation-not-ready-check-model-keyboard-or-sound')

    def dictation_failed(self, code):
        trace('daemon','dictation-failed',dictation_id=self.dictation_id,code=code)
        self.dictation_error=code
        self.preview_text=''
        self.recording=None
        self.final_stop_candidate=None
        self.recognition_epoch+=1
        self.phase='wake';self.phase_since=time.monotonic()
        self.publish('LISTENING',code,self.mic)

    async def cancel_dictation(self):
        if self.phase.startswith('typing'):
            trace('daemon','dictation-cancelled',dictation_id=self.dictation_id,phase=self.phase)
        self.final_stop_candidate=None
        preview,self.preview_job=self.preview_job,None
        if preview and not preview.done():
            preview.cancel()
            with contextlib.suppress(asyncio.CancelledError):await preview
        self.preview_text=''
        job,self.dictation_job=self.dictation_job,None
        if job and job is not asyncio.current_task() and not job.done():
            job.cancel()
            with contextlib.suppress(asyncio.CancelledError):await job
        self.recording=None
        if self.phase.startswith('typing'):
            self.recognition_epoch+=1;self.phase='wake';self.phase_since=time.monotonic()
            self.publish('LISTENING','dictation-cancelled',self.mic)

    def finish_dictation(self, end=None):
        if self.phase!='typing-recording' or self.recording is None:return
        recording,self.recording=self.recording,None
        self.last_finish_reason='spoken-command' if end is not None else ('recording-limit' if recording.elapsed+1e-6>=MAX_SECONDS else 'silence-timeout')
        self.final_stop_candidate=recording.stop_candidate() if end is None else None
        trace('daemon','dictation-finish',dictation_id=self.dictation_id,reason=self.last_finish_reason,
              recorded_seconds=round(recording.elapsed,2),cut_seconds=round(end/32000,2) if end is not None else None,
              tail_check=bool(self.final_stop_candidate))
        # Stop-command-only recordings contain no dictated speech before the cut.
        has_content=recording.spoke and (end is None or recording.first_speech is not None and recording.first_speech<end)
        pcm=recording.take(end) if has_content else b''
        self.phase='typing-transcribing';self.phase_since=time.monotonic()
        self.publish('TYPING_TRANSCRIBING','transcribing-on-rtx-4060',self.mic)
        self.dictation_job=asyncio.create_task(self.transcribe_and_type(pcm))

    def maybe_preview_dictation(self):
        record=self.recording
        engine=self.vietnamese if self.dictation_language=='vi' else self.parakeet
        if (not record or not record.spoke or record.elapsed<self.preview_at+5 or
                self.english_busy or engine.state!='ready' or
                self.preview_job and not self.preview_job.done()):return
        self.preview_at=record.elapsed
        self.preview_job=asyncio.create_task(self.preview_dictation(record,bytes(record.audio),record.elapsed))

    async def transcribe_dictation(self, pcm):
        engine=self.vietnamese if self.dictation_language=='vi' else self.parakeet
        return await engine.transcribe(pcm)

    async def preview_dictation(self, record, pcm, seconds):
        started=time.monotonic()
        try:
            # Re-decode the entire bounded recording so later context can revise
            # earlier wording. No text is committed to the keyboard here.
            text,_=terminal_stop(keyboard_text(await self.transcribe_dictation(pcm)),self.dictation_language)
            if (self.enabled and self.phase=='typing-recording' and self.recording is record
                    and await unlocked_session()):
                self.preview_text=text;self.preview_seconds=round(seconds,1)
                self.preview_revision+=1
                trace('daemon','preview-ready',dictation_id=self.dictation_id,seconds=round(seconds,2),
                      revision=self.preview_revision,latency_ms=round((time.monotonic()-started)*1000))
                self.publish(self.state,self.detail,self.mic)
        except asyncio.CancelledError:raise
        except Exception as exc:
            trace_error('daemon','preview-error',exc,dictation_id=self.dictation_id)
            self.dictation_failed('dictation-preview-failed')

    async def transcribe_and_type(self, pcm):
        try:
            # Drain the partial reply before the final decode, which excludes
            # stop-command audio. A late preview cannot overwrite the final text.
            if self.preview_job:await self.preview_job
            if not self.enabled or self.phase!='typing-transcribing':return
            candidate,self.final_stop_candidate=self.final_stop_candidate,None
            if candidate and pcm:
                cut,tail=candidate
                tail_command=command_text(await self.transcribe_dictation(tail))
                matched=tail_command in (VIETNAMESE_STOPS if self.dictation_language=='vi' else ENGLISH_STOPS)
                trace('daemon','final-stop-check',dictation_id=self.dictation_id,matched=matched,
                      command=tail_command if matched else None)
                if matched:
                    pcm=pcm[:cut];self.last_finish_reason='spoken-command-final-check'
            text=keyboard_text(await self.transcribe_dictation(pcm)) if pcm else ''
            text,stop=terminal_stop(text,self.dictation_language)
            if stop:
                self.last_finish_reason='spoken-command-final-check'
                trace('daemon','terminal-command-removed',dictation_id=self.dictation_id,command=stop)
            pcm=b''
            if self.enabled and self.phase=='typing-transcribing' and text:
                sid=await unlocked_session()
                if not sid:raise RuntimeError('screen-locked-or-session-unavailable')
                await self.ensure_keyboard()
                self.phase='typing-inserting'
                self.publish('TYPING_INSERTING','pasting-into-focused-field',self.mic)
                self.keyboard.stdin.write(json.dumps({'text':text,'session':sid}).encode()+b'\n')
                await self.keyboard.stdin.drain()
                reply=json.loads(await asyncio.wait_for(self.keyboard.stdout.readline(),max(5,len(text)*.015)))
                if reply.get('state')!='typed':raise RuntimeError('keyboard-input-failed')
                self.dictation_count+=1
                trace('daemon','dictation-typed',dictation_id=self.dictation_id,characters=len(text),reason=self.last_finish_reason)
            text='';self.preview_text=''
            self.recognition_epoch+=1;self.phase='wake';self.phase_since=time.monotonic()
            self.publish('LISTENING','dictation-complete-waiting-for-wake',self.mic)
        except asyncio.CancelledError:
            # Kill pending keyboard work as well as inference. Never finish an
            # insertion after Disable, screen lock or Unload.
            await self.close_keyboard()
            raise
        except Exception as exc:
            trace_error('daemon','dictation-final-error',exc,dictation_id=self.dictation_id)
            await self.close_keyboard()
            self.dictation_failed('dictation-transcription-or-keyboard-failed')

    def submit_english(self, utterance, sid):
        if (not self.english and self.parakeet.state not in {'ready','transcribing'}) or self.english_busy:
            if self.phase=='typing-recording':trace('daemon','command-skipped',reason='recognizer-busy-or-unavailable',seconds=round(len(utterance.pcm)/32000,2))
            return
        self.english_busy=True
        context=self.recognition_context()
        end=len(self.recording.audio) if self.recording else None
        job=asyncio.create_task(self.recognize_english(utterance,sid,context,end))
        self.english_job=job
        self.recognition_jobs.add(job);job.add_done_callback(self.recognition_jobs.discard)

    async def recognize_english(self, utterance, sid, context, end):
        started=time.monotonic()
        outcome='stale';personal=False;engine='none';phrase=None
        try:
            if not self.result_is_current(context,started):return
            kind=context[1]
            phrases=ENGLISH_TRIGGERS if kind=='wake' else ENGLISH_STOPS
            if kind not in {'wake','typing-recording'}:return
            if kind=='typing-recording' and utterance.preceding_silence+1e-6<STOP_PAUSE:
                outcome='insufficient-pause';return
            self.english_stats['checks']+=1
            acoustic_kind='typing' if kind=='wake' else 'typing-stop'
            accepted=False
            engine='personal'
            if self.wav2vec and getattr(self.wav2vec,'typing_templates',None):
                personal=await asyncio.to_thread(self.wav2vec.match_typing,utterance.pcm,acoustic_kind)
                accepted=personal and kind!='wake'
            if not self.result_is_current(context,started):return
            if not accepted:
                result={}
                engine='vosk'
                if self.english:
                    result=await asyncio.wait_for(asyncio.to_thread(self.english.decode,utterance.pcm),3)
                accepted=command_match(result,phrases)
                # Personal acoustic similarity alone caused unintended starts.
                # Even an enrolled voice must say the exact lexical command.
                if personal and kind=='wake' and command_text(result.get('text','')) in phrases:
                    accepted=command_match(result,phrases,minimum=.35)
                if accepted:phrase=command_text(result['text'])
            if not self.result_is_current(context,started):return
            # Parakeet's full English vocabulary can recover words Vosk missed.
            # Never load it just to scan wake audio: Unload must stay unloaded.
            if not accepted and self.parakeet.state in {'ready','transcribing'}:
                text=await self.parakeet.transcribe(utterance.pcm)
                accepted=command_text(text) in phrases
                if accepted:phrase=command_text(text)
                engine='parakeet'
            if accepted and personal:engine='personal'
            outcome='no-match' if not accepted else 'stale'
            self.english_stats['last_engine']=engine
            if accepted and self.result_is_current(context,started) and await unlocked_session(sid) and self.result_is_current(context,started):
                self.english_stats['matches']+=1
                self.english_stats[engine+'_matches']+=1
                outcome='accepted'
                trace('daemon','command-accepted',phase=kind,engine=engine,personal_match=personal,command=phrase)
                if kind=='wake':self.begin_dictation()
                else:
                    self.preview_text=terminal_stop(self.preview_text)[0]
                    self.finish_dictation(max(0,end-len(utterance.pcm)))
        except asyncio.CancelledError:raise
        except Exception as exc:
            outcome='error'
            trace_error('daemon','command-error',exc,phase=context[1])
            self.english_stats['errors']+=1
        finally:
            self.english_stats['latency_ms']=round((time.monotonic()-started)*1000)
            trace('daemon','command-check',phase=context[1],outcome=outcome,engine=engine,personal_match=personal,
                  preceding_silence=round(utterance.preceding_silence,2),seconds=round(len(utterance.pcm)/32000,2),
                  latency_ms=self.english_stats['latency_ms'])
            self.english_busy=False
            self.publish(self.state,self.detail,self.mic)

    def request_voice_stop(self, writer, reason):
        if self.phase != "conversation" or not self.session:
            return
        now = time.monotonic()
        self.last_voice_stop = {"reason": reason, "at": int(time.time()),
                                "reply_state": self.reply_guard.state_at(now),
                                "idle_remaining": self.reply_guard.remaining(now, self.last_activity, self.silence_seconds),
                                "voice_events": self.voice_events}
        print(json.dumps({"event": "voice-stop-request", **self.last_voice_stop}), flush=True)
        self.phase = "closing"
        self.phase_since = now
        self.publish("CLOSING", reason, self.mic)
        self.send(self.browser or writer, {"type": "stop", "id": secrets.token_hex(16),
                           "session": self.session, "reason": reason, "idle_seconds": self.silence_seconds, "at": int(time.time())})

    def check_inactivity(self, writer, now):
        if self.phase == "conversation" and self.reply_guard.expired(now,self.last_activity,self.silence_seconds):
            self.request_voice_stop(writer, "silence-timeout")

    async def unload_models(self):
        await self.disarm('unloading-models')
        if self.browser:
            self.send(self.browser, {'type':'control', 'action':'disable'})

    async def release_models(self):
        # Invalidate and cancel every producer before terminating either worker.
        jobs = {job for job in (*self.recognition_jobs, self.english_job,
                                self.wav2vec_loading, self.english_loading, self.model_task)
                if job and job is not asyncio.current_task() and not job.done()}
        for job in jobs:
            job.cancel()
        if jobs:
            await asyncio.gather(*jobs, return_exceptions=True)
        if self.wake_worker:
            await asyncio.to_thread(self.wake_worker.close)
        self.wake_worker = self.wav2vec = self.vad = None
        self.wav2vec_loading = None
        self.english = self.english_loading = None
        self.english_state = 'not-loaded'
        self.engine_busy.clear()
        self.engines['wav2vec2'].update(state='unloaded',
                                         device=None, templates=False)
        await asyncio.gather(self.parakeet.unload(),self.vietnamese.unload())
        self.vietnamese.acoustic=None
        await self.close_keyboard()
        self.dictation_error = None

    async def prepare_wav2vec(self):
        self.engines["wav2vec2"]["state"] = "loading"
        worker = self.wake_worker = WakeModels(self.wav2vec_path)
        try:
            await asyncio.to_thread(worker.load)
            self.wav2vec, self.vad = worker, worker.vad
            self.vietnamese.acoustic=worker
            self.engines["wav2vec2"]["state"] = "ready"
            self.engines["wav2vec2"]["device"] = self.wav2vec.device_name
            self.engines["wav2vec2"]["templates"] = bool(self.wav2vec.templates)
        except asyncio.CancelledError:
            await asyncio.to_thread(worker.close)
            raise
        except FileNotFoundError:
            self.engines["wav2vec2"]["state"] = "model-missing"
        except ImportError:
            self.engines["wav2vec2"]["state"] = "dependencies-missing"
        except RuntimeError as exc:
            self.engines["wav2vec2"]["state"] = (str(exc) if str(exc) in {
                "gpu-not-configured", "cuda-unavailable", "wrong-cuda-gpu",
                "model-missing", "dependencies-missing"} else "load-error")
        except Exception:
            self.engines["wav2vec2"]["state"] = "load-error"
        if self.engines['wav2vec2']['state'] != 'ready':
            await asyncio.to_thread(worker.close)
        self.publish(self.state, self.detail, self.mic)

    def recognition_context(self):
        return (self.recognition_epoch, self.phase, self.phase_since, self.session)

    def result_is_current(self, context, started):
        return (self.enabled and context == self.recognition_context()
                and time.monotonic() - started <= 5)

    def submit_recognition(self, engine, decoder, utterance, writer, sid):
        # One in-flight utterance per engine. Never build a queue of old audio.
        if engine in self.engine_busy:
            self.engines[engine]["skipped"] += 1
            return
        self.engine_busy.add(engine)
        context = self.recognition_context()
        end=len(self.recording.audio) if self.recording else None
        job = asyncio.create_task(self.recognize(engine, decoder, utterance, writer, sid, context,end))
        self.recognition_jobs.add(job)
        job.add_done_callback(self.recognition_jobs.discard)

    async def recognize(self, engine, decoder, utterance, writer, sid, context, recording_end=None):
        started = time.monotonic()
        try:
            result = await asyncio.to_thread(decoder, utterance.pcm)
            elapsed = time.monotonic() - started
            stats = self.engines[engine]
            stats["latency_ms"] = round(elapsed * 1000)
            stats["checks"] += 1
            # A result from before disable/re-enable, a prior Voice session, or
            # over five seconds ago can never operate Chrome.
            if not self.result_is_current(context, started):
                return
            kind = context[1]
            # Vietnamese dictation is selected only by complete lexical commands.
            # Personal wake templates must never turn an unrelated phrase into
            # a dictation start, and an English decoder cannot switch its language.
            if engine=='wav2vec2' and (kind=='wake' or kind=='typing-recording' and self.dictation_language=='vi'):
                phrases=VIETNAMESE_TRIGGERS if kind=='wake' else VIETNAMESE_STOPS
                matched=command_match(result,phrases)
                if kind=='typing-recording' and utterance.preceding_silence+1e-6<STOP_PAUSE:matched=False
                if matched and await unlocked_session(sid) and self.result_is_current(context,started):
                    if kind=='wake':self.begin_dictation('vi')
                    elif self.recording and recording_end is not None:
                        cut=max(0,recording_end-len(utterance.pcm))
                        self.finish_dictation(cut)
                    return
                if kind=='typing-recording':return
            accepted = (wake_match(result, self.wake_profile)
                        if kind == "wake" else stop_command(result, utterance.preceding_silence))
            if engine == 'wav2vec2':
                accepted = accepted or acoustic_accept(result, 'wake' if kind == 'wake' else 'stop',
                                                       utterance.preceding_silence)
            if kind == "wake":
                self.wake_checks += 1
                self.last_wake_check = "matched" if accepted else "not-matched"
            if not accepted:
                return
            # Session checks await external state. Recheck the context afterward
            # so two simultaneous recognizers cannot both emit the same action.
            if not await unlocked_session(sid):
                await self.disarm("screen-locked-or-session-unavailable")
                return
            if not self.result_is_current(context, started):
                return
            if kind == 'conversation':
                now=time.monotonic()
                # An isolated keyword heard in ChatGPT's own playback must not
                # hang up the call. Accept speech stops only from a verified
                # quiet interval which did not overlap the captured utterance.
                began=started-len(utterance.pcm)/32000-.75
                quiet=(self.voice_events.get('playback_state')=='quiet' and
                       self.remote_audio_updated is not None and 0<=now-self.remote_audio_updated<2.5)
                overlap=self.last_remote_audio is not None and self.last_remote_audio>=began
                if not quiet or overlap:
                    self.stop_echo_suppressed += 1
                    print(json.dumps({'event':'stop-keyword-suppressed','reason':'remote-audio-active-or-unverified'}),flush=True)
                    return
            stats["matches"] += 1
            self.last_recognizer = engine
            if kind == "wake" and time.monotonic() - self.last_wake >= 1:
                self.wake_matches += 1
                await self.begin_wake(writer)
            elif kind == "conversation":
                self.request_voice_stop(writer, "spoken-stop-command")
        except asyncio.CancelledError:
            raise
        except Exception:
            # Failed or stale recognition never operates Chrome.
            self.engines[engine]["state"] = "decode-error"
        finally:
            self.engine_busy.discard(engine)
            self.publish(self.state, self.detail, self.mic)

    async def listen(self, writer, sid):
        proc = None
        cancelled = False
        try:
            self.publish("ARMING", "loading-offline-model")
            if self.english is None and (not self.english_loading or self.english_loading.done()):
                self.english_loading=asyncio.create_task(self.prepare_english())
            if self.wav2vec is not None and self.vad is not None:
                self.engines["wav2vec2"]["state"] = "ready"
            if self.wav2vec is None and (not self.wav2vec_loading or self.wav2vec_loading.done()):
                self.wav2vec_loading = asyncio.create_task(self.prepare_wav2vec())
            # Models and listening share one lifecycle, including manual Enable.
            loads = [job for job in (self.wav2vec_loading, self.english_loading,
                                     self.start_model_load()) if job]
            await asyncio.gather(*(asyncio.shield(job) for job in loads))
            if (self.wav2vec is None or self.vad is None or self.english is None
                    or self.parakeet.state != 'ready' or self.vietnamese.state != 'ready'):
                raise RuntimeError('models-not-ready')
            if not await unlocked_session(sid):
                raise RuntimeError("screen-locked-or-session-unavailable")
            args = ["parec", "--raw", "--format=s16le", "--rate=16000", "--channels=1",
                    "--client-name=Hey GPT local voice control"]
            if self.source:
                args += [f"--device={self.source}"]
            proc = await asyncio.create_subprocess_exec(
                *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
            self.capture_starts += 1
            if self.vad:
                await asyncio.to_thread(self.vad.reset)
            deadline = time.monotonic() + self.max_seconds if self.max_seconds else float("inf")
            check_at = 0
            status_at = 0
            gate, personal_gate, gate_phase = SpeechGate(), PersonalSpeechGate(), self.phase
            typing_gate=PersonalSpeechGate(tail=STOP_PAUSE,preroll_frames=2)
            while time.monotonic() < deadline:
                now = time.monotonic()
                if now >= check_at:
                    if not await unlocked_session(sid):
                        raise RuntimeError("screen-locked-or-session-unavailable")
                    check_at = now + 1
                try:
                    data = await asyncio.wait_for(proc.stdout.readexactly(3200), 3)
                except (asyncio.IncompleteReadError, asyncio.TimeoutError):
                    raise RuntimeError("microphone-unavailable") from None
                if not self.mic:
                    self.publish("CONVERSATION" if self.phase == "conversation" else "LISTENING",
                                 "listening-for-stop-commands" if self.phase == "conversation" else "offline-hey-gpt-only", True)
                if gate_phase != self.phase:
                    gate, personal_gate, gate_phase = SpeechGate(), PersonalSpeechGate(), self.phase
                    typing_gate=PersonalSpeechGate(tail=STOP_PAUSE,preroll_frames=2)
                activity = await asyncio.to_thread(self.vad.feed,data) if self.vad else None
                voiced, utterance = gate.feed(data,voiced=activity)
                english_voiced,english_utterance=voiced,utterance
                if self.phase in {'wake','typing-recording'} and self.wav2vec and getattr(self.wav2vec,'typing_templates',None):
                    english_voiced,english_utterance=personal_gate.feed(data,voiced=activity)
                if self.phase=='typing-recording':
                    english_voiced,english_utterance=typing_gate.feed(data,voiced=activity)
                self.audio_level = round(rms(data))
                now = time.monotonic()
                if now >= status_at:
                    self.publish(self.state, self.detail, self.mic)
                    status_at = now + 1
                if self.phase=='typing-recording' and self.recording:
                    ended=self.recording.feed(data,english_voiced)
                    if english_utterance and not english_utterance.too_long:
                        if self.dictation_language=='vi':
                            if self.wav2vec:self.submit_recognition('wav2vec2',self.wav2vec.decode,english_utterance,writer,sid)
                        else:self.submit_english(english_utterance,sid)
                    if ended and (not self.english_busy or self.recording.elapsed+1e-6>=MAX_SECONDS):self.finish_dictation()
                    elif self.recording:self.maybe_preview_dictation()
                    continue
                if self.phase.startswith('typing'):
                    continue
                if self.phase == "conversation" and voiced:
                    self.last_activity = now
                if self.phase in {"opening", "closing"}:
                    if self.phase == "opening" and now - self.phase_since > 90:
                        self.return_to_wake("browser-transition-timeout")
                    elif self.phase == "closing" and now - self.phase_since > 20:
                        raise RuntimeError("browser-transition-timeout")
                    continue
                if self.phase=='wake' and english_utterance and not english_utterance.too_long:
                    self.submit_english(english_utterance,sid)
                if utterance and not utterance.too_long:
                    kind = self.phase
                    if kind == "wake" or (kind == "conversation" and utterance.preceding_silence + 1e-6 >= 1.0):
                        if self.wav2vec and self.engines["wav2vec2"]["state"] == "ready":
                            self.submit_recognition("wav2vec2", self.wav2vec.decode, utterance, writer, sid)
                if not any(v["state"] in {"ready", "loading"} for v in self.engines.values()):
                    raise RuntimeError("recognizers-unavailable")
                self.check_inactivity(writer, now)
            self.detail = "listener-expired"
        except asyncio.CancelledError:
            cancelled = True
            self.detail = "cancelled"
            raise
        except Exception as exc:
            trace_error('daemon','listener-error',exc,phase=self.phase)
            self.detail = str(exc) if str(exc) in {
                "microphone-unavailable", "screen-locked-or-session-unavailable",
                "browser-transition-timeout", "recognizers-unavailable", "models-not-ready"} else "model-or-audio-error"
        finally:
            if proc and proc.returncode is None:
                with contextlib.suppress(ProcessLookupError):
                    proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), 2)
                except asyncio.TimeoutError:
                    proc.kill()
                    await proc.wait()
            await self.cancel_dictation()
            self.enabled = False
            self.phase, self.session = "wake", None
            if not cancelled:
                await self.release_models()
            self.publish("DISARMED", self.detail)
            self.owner = None

    async def handle(self, reader, writer):
        sock = writer.get_extra_info("socket")
        _, uid, _ = struct.unpack("3i", sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
        if uid != os.getuid():
            writer.close()
            return
        self.clients.add(writer)
        self.send(writer, self.snapshot())
        try:
            while line := await reader.readline():
                if len(line) > MAX_FRAME:
                    break
                msg = json.loads(line)
                if not isinstance(msg, dict):
                    break
                async with self.control:
                    await self.dispatch(msg, writer)
                    if isinstance(msg.get("request"), str):
                        self.send(writer, {"type": "ack", "request": msg["request"][:64]})
                await writer.drain()
        except (ValueError, ConnectionError, asyncio.LimitOverrunError):
            pass
        finally:
            async with self.control:
                if self.browser is writer:
                    self.browser_disconnected()
            self.clients.discard(writer)
            writer.close()
            with contextlib.suppress(ConnectionError):
                await writer.wait_closed()


async def main(args):
    folder = runtime_dir()
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    folder.chmod(0o700)
    # A lock prevents accidental duplicate daemons from unlinking a live socket.
    import fcntl
    lock = (folder / "daemon.lock").open("w")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    path = folder / "control.sock"
    path.unlink(missing_ok=True)
    listener = Listener(args.max_seconds, args.source, args.silence_seconds, args.wav2vec_model)
    listener.publish("DISARMED", "service-ready-microphone-closed")
    server = await asyncio.start_unix_server(listener.handle, path=str(path), limit=MAX_FRAME)
    path.chmod(0o600)
    await listener.startup()
    stop = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        asyncio.get_running_loop().add_signal_handler(sig, stop.set)
    async with server:
        await stop.wait()
        server.close()
        async with listener.control:
            listener.stopping = True
            await listener.disarm("service-stopped")
            listener.browser = None
            clients = list(listener.clients)
            for writer in clients:
                writer.close()
        # Server.wait_closed can wait for existing native messaging clients.
        # Close those explicitly instead of leaving restart stuck indefinitely.
        for writer in clients:
            with contextlib.suppress(ConnectionError, asyncio.TimeoutError):
                await asyncio.wait_for(writer.wait_closed(), 2)
    path.unlink(missing_ok=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    # Accepted for existing installed units. The saved preference is authoritative.
    parser.add_argument("--auto-listen", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--source", help="PulseAudio/PipeWire source name; default source otherwise")
    parser.add_argument("--max-seconds", type=int, default=0, help="0: listen until disabled or locked")
    parser.add_argument("--silence-seconds", type=float, default=15, help="Voice inactivity timeout; 0 keeps Voice open until a stop command")
    parser.add_argument("--wav2vec-model", type=Path, default=BASE / "models/wav2vec2-base-vietnamese-250h")
    asyncio.run(main(parser.parse_args()))
