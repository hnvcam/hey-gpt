#!/usr/bin/env python3
"""Offline wake listener and status hub. No HTTP client or saved audio."""
import argparse
import asyncio
import contextlib
import json
import math
from wake_words import PHRASES, wake_identity
import os
from pathlib import Path
import secrets
import signal
import socket
import struct
import time
from wav2vec_recognizer import Wav2VecVietnamese, wake_match, load_wake_profile
from audio_control import SpeechGate, STOP_PHRASES, stop_command, rms
from acoustic_keywords import acoustic_accept
from voice_activity import VoiceActivity
from conversation_idle import ConversationIdle

BASE = Path(__file__).resolve().parent
MAX_FRAME = 4096
BROWSER_ERRORS = frozenset({
    'browser-operation-failed','voice-end-failed','rearm-failed',
    'voice-ended-unexpectedly','voice-end-unconfirmed','browser-notice',
    'browser-already-recording','composer-has-draft','composer-not-found',
    'voice-button-missing-or-ambiguous','setup-required','target-tab-changed',
    'voice-not-open','voice-transition-pending','wrong-origin','no-page-result',
    'review-browser-permission-limit-or-start-button','another-chrome-connected',
})


def runtime_dir():
    return Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")) / "hey-gpt"


def matched(result, minimum=0.85, minimum_word=0.55):
    """Complete phonetic wake phrase with a strong whole-phrase score.

    One weaker syllable is normal in live speech. Missing syllables, unknown words
    or an overall weak result still fail; no substring/fuzzy trigger is used.
    """
    words = result.get("result", [])
    if not wake_identity(result.get("text", "")) or not words:
        return False
    scores = [word.get("conf", 0) for word in words]
    return (all(math.isfinite(score) for score in scores) and min(scores) >= minimum_word
            and sum(scores) / len(scores) >= minimum)



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
    def __init__(self, model_path, max_seconds=0, source=None, silence_seconds=15, engine_mode="both", wav2vec_path=None):
        self.model_path = model_path
        self.model = None
        self.wake_grammar = None
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
        self.enabled = False
        self.stopping = False
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
        self.engine_mode = engine_mode
        self.wav2vec_path = wav2vec_path or BASE / "models/wav2vec2-base-vietnamese-250h"
        self.wav2vec = None
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
        self.engines = {name: {"state": "not-loaded" if engine_mode in {"both", name} else "disabled",
                               "checks": 0, "matches": 0, "skipped": 0, "latency_ms": 0}
                        for name in ("vosk", "wav2vec2")}


    def snapshot(self):
        return {"type": "status", "state": self.state, "detail": self.detail,
                "local_mic_open": self.mic, "enabled": self.enabled,
                "browser_connected": self.browser is not None,
                "browser_state": self.browser_state, "browser_detail": self.browser_detail,
                "last_error": self.last_error, "listen_mode": self.phase,
                "silence_seconds": self.silence_seconds,
                "reply_ui_state": self.reply_guard.state_at(time.monotonic()),
                "idle_remaining": self.reply_guard.remaining(time.monotonic(),self.last_activity,self.silence_seconds),
                "recognizers": self.engines, "last_recognizer": self.last_recognizer,
                "engine_mode": self.engine_mode, "personal_wake_phrases": len(self.wake_profile),
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
        self.reply_guard.reset()
        self.enabled = False
        self.recognition_epoch += 1
        if self.task:
            self.task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.task
        self.task, self.owner = None, None
        self.phase, self.session = "wake", None
        if detail in BROWSER_ERRORS:
            self.last_error = {"code": detail, "at": int(time.time())}
            print(json.dumps({"event":"browser-error", **self.last_error}), flush=True)
        self.publish("DISARMED", detail)

    async def arm(self, writer):
        if self.task and not self.task.done():
            self.send(writer, {"type": "error", "detail": "already-armed"})
            return
        sid = await unlocked_session()
        if not sid:
            self.publish("ERROR", "screen-locked-or-session-unavailable")
            return
        self.owner = writer
        self.enabled = True
        self.browser_detail = ""
        self.browser_state = "IDLE"
        self.phase, self.session = "wake", None
        self.phase_since = time.monotonic()
        self.task = asyncio.create_task(self.listen(writer, sid))

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
        elif action == "arm" and writer is self.browser:
            await self.arm(writer)
        elif action in {"disarm", "disable"}:
            reason = msg.get("reason") if writer is self.browser else None
            await self.disarm(reason if reason in BROWSER_ERRORS else "user-disarmed")
            if self.browser and action == "disable":
                self.send(self.browser, {"type": "control", "action": "disable"})
        elif action == "enable":
            if self.browser:
                self.send(self.browser, {"type": "control", "action": "enable"})
            else:
                self.publish("DISARMED", "chrome-extension-required")
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
            if (self.phase == "opening" or (self.phase == "wake" and msg.get("existing") is True)) and isinstance(token, str) and 8 <= len(token) <= 64:
                self.session = token
                self.phase = "conversation"
                self.reply_guard.reset()
                self.voice_events = {}
                self.phase_since = self.last_activity = time.monotonic()
                self.browser_state = "VOICE"
                self.publish("CONVERSATION", "listening-for-stop-commands", self.mic)
        elif action == "activity" and writer is self.browser:
            if self.phase == "conversation" and msg.get("session") == self.session:
                now=time.monotonic()
                from native_host import clean_voice_events
                self.voice_events=clean_voice_events(msg.get('voice_events'))
                state=msg.get('ui_state')
                # An older adapter's absence of a busy flag is not proof of idle.
                if state not in {'idle','busy','unknown'}:
                    state='busy' if msg.get('busy') is True else 'unknown'
                self.reply_guard.update(state,now)
                if state=='busy':self.last_activity=now
        elif action == "resume" and writer is self.browser:
            if self.enabled and self.phase in {"conversation", "closing"} and msg.get("session") == self.session:
                self.phase, self.session = "wake", None
                self.phase_since = time.monotonic()
                self.browser_state = "IDLE"
                self.publish("LISTENING", "offline-hey-gpt-only", self.mic)
        elif action == 'defer' and writer is self.browser:
            # A fresh wake met a busy composer. Keep the same local capture;
            # do not queue/retry opening Voice or turn off either model.
            if self.enabled and self.phase == 'opening':
                self.recognition_epoch += 1
                self.phase,self.session = 'wake',None
                self.phase_since = time.monotonic()
                self.browser_state = 'WAITING'
                self.publish('LISTENING','chrome-busy-local-still-listening',self.mic)
        elif action == "status":
            self.send(writer, self.snapshot())
        else:
            self.send(writer, {"type": "error", "detail": "unsupported-command"})

    def request_voice_stop(self, writer, reason):
        if self.phase != "conversation" or not self.session:
            return
        self.phase = "closing"
        self.phase_since = time.monotonic()
        self.publish("CLOSING", reason, self.mic)
        self.send(writer, {"type": "stop", "id": secrets.token_hex(16),
                           "session": self.session, "reason": reason, "at": int(time.time())})

    def check_inactivity(self, writer, now):
        if self.phase == "conversation" and self.reply_guard.expired(now,self.last_activity,self.silence_seconds):
            self.request_voice_stop(writer, "silence-timeout")

    def decode(self, vosk, pcm, kind):
        if kind == "wake":
            if self.wake_grammar is None:
                lookup = getattr(self.model, "vosk_model_find_word", None)
                known = {w for phrase in PHRASES for w in phrase.split()
                         if lookup is None or lookup(w) >= 0}
                self.wake_grammar = [phrase for phrase in PHRASES
                                     if all(w in known for w in phrase.split())]
            rec = vosk.KaldiRecognizer(self.model, 16000, json.dumps([*self.wake_grammar, "[unk]"], ensure_ascii=False))
        else:
            # Full Vietnamese vocabulary preserves the surrounding sentence.
            # A constrained stop-word grammar could turn ordinary speech into 'hết'.
            rec = vosk.KaldiRecognizer(self.model, 16000)
        rec.SetWords(True)
        pieces = []
        for offset in range(0, len(pcm), 6400):
            if rec.AcceptWaveform(pcm[offset:offset+6400]):
                pieces.append(json.loads(rec.Result()))
        pieces.append(json.loads(rec.FinalResult()))
        return {"text": " ".join(p.get("text", "") for p in pieces).strip(),
                "result": [word for p in pieces for word in p.get("result", [])]}

    async def prepare_wav2vec(self):
        self.engines["wav2vec2"]["state"] = "loading"
        try:
            self.wav2vec = await asyncio.to_thread(Wav2VecVietnamese, self.wav2vec_path)
            self.vad = await asyncio.to_thread(VoiceActivity, BASE/'models/silero-vad/silero_vad.jit',
                                              self.wav2vec.torch,self.wav2vec.np,self.wav2vec.device)
            self.engines["wav2vec2"]["state"] = "ready"
            self.engines["wav2vec2"]["device"] = self.wav2vec.device_name
            self.engines["wav2vec2"]["templates"] = bool(self.wav2vec.templates)
        except FileNotFoundError:
            self.engines["wav2vec2"]["state"] = "model-missing"
        except ImportError:
            self.engines["wav2vec2"]["state"] = "dependencies-missing"
        except RuntimeError as exc:
            self.engines["wav2vec2"]["state"] = (str(exc) if str(exc) in {
                "gpu-not-configured", "cuda-unavailable", "wrong-cuda-gpu"} else "load-error")
        except Exception:
            self.engines["wav2vec2"]["state"] = "load-error"
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
        job = asyncio.create_task(self.recognize(engine, decoder, utterance, writer, sid, context))
        self.recognition_jobs.add(job)
        job.add_done_callback(self.recognition_jobs.discard)

    async def recognize(self, engine, decoder, utterance, writer, sid, context):
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
            accepted = ((matched(result) if engine == "vosk" else wake_match(result, self.wake_profile))
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
            stats["matches"] += 1
            self.last_recognizer = engine
            if kind == "wake" and time.monotonic() - self.last_wake >= 1:
                self.wake_matches += 1
                self.phase = "opening"
                self.phase_since = self.last_wake = time.monotonic()
                self.publish("OPENING", "opening-chrome-voice-local-still-listening", True)
                self.send(writer, {"type": "wake", "id": secrets.token_hex(16), "at": int(time.time())})
            elif kind == "conversation":
                self.request_voice_stop(writer, "spoken-stop-command")
        except asyncio.CancelledError:
            raise
        except Exception:
            # Only this branch fails. The other recognizer keeps listening.
            self.engines[engine]["state"] = "decode-error"
        finally:
            self.engine_busy.discard(engine)
            self.publish(self.state, self.detail, self.mic)

    async def listen(self, writer, sid):
        proc = None
        try:
            self.publish("ARMING", "loading-offline-model")
            vosk = None
            if self.engine_mode in {"both", "wav2vec2"}:
                if self.wav2vec is not None and self.vad is not None:
                    self.engines["wav2vec2"]["state"] = "ready"
                if self.wav2vec is None and (not self.wav2vec_loading or self.wav2vec_loading.done()):
                    self.wav2vec_loading = asyncio.create_task(self.prepare_wav2vec())
            if self.engine_mode in {"both", "vosk"}:
                try:
                    import vosk
                    vosk.SetLogLevel(-1)
                    if self.model is None:
                        self.model = await asyncio.to_thread(vosk.Model, str(self.model_path))
                    self.engines["vosk"]["state"] = "ready"
                except Exception:
                    self.engines["vosk"]["state"] = "load-error"
                    vosk = None
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
            gate, gate_phase = SpeechGate(), self.phase
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
                    gate, gate_phase = SpeechGate(), self.phase
                activity = await asyncio.to_thread(self.vad.feed,data) if self.vad else None
                voiced, utterance = gate.feed(data,voiced=activity)
                self.audio_level = round(rms(data))
                now = time.monotonic()
                if now >= status_at:
                    self.publish(self.state, self.detail, self.mic)
                    status_at = now + 1
                if self.phase == "conversation" and voiced:
                    self.last_activity = now
                if self.phase in {"opening", "closing"}:
                    if now - self.phase_since > 20:
                        raise RuntimeError("browser-transition-timeout")
                    continue
                if utterance and not utterance.too_long:
                    kind = self.phase
                    if kind == "wake" or (kind == "conversation" and utterance.preceding_silence + 1e-6 >= 1.0):
                        if vosk and self.engines["vosk"]["state"] == "ready":
                            self.submit_recognition("vosk", lambda pcm, mode=kind: self.decode(vosk, pcm, mode),
                                                    utterance, writer, sid)
                        if self.wav2vec and self.engines["wav2vec2"]["state"] == "ready":
                            self.submit_recognition("wav2vec2", self.wav2vec.decode, utterance, writer, sid)
                if not any(v["state"] in {"ready", "loading"} for v in self.engines.values()):
                    raise RuntimeError("recognizers-unavailable")
                self.check_inactivity(writer, now)
            self.detail = "listener-expired"
        except asyncio.CancelledError:
            self.detail = "cancelled"
            raise
        except Exception as exc:
            self.detail = str(exc) if str(exc) in {
                "microphone-unavailable", "screen-locked-or-session-unavailable",
                "browser-transition-timeout", "recognizers-unavailable"} else "model-or-audio-error"
        finally:
            if proc and proc.returncode is None:
                with contextlib.suppress(ProcessLookupError):
                    proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), 2)
                except asyncio.TimeoutError:
                    proc.kill()
                    await proc.wait()
            self.enabled = False
            self.phase, self.session = "wake", None
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
                if self.owner is writer or self.browser is writer:
                    if self.browser is writer:
                        self.browser = None
                        self.browser_state = "IDLE"
                    await self.disarm("browser-disconnected")
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
    listener = Listener(args.model, args.max_seconds, args.source, args.silence_seconds, args.engine_mode, args.wav2vec_model)
    listener.publish("DISARMED", "service-ready-microphone-closed")
    server = await asyncio.start_unix_server(listener.handle, path=str(path), limit=MAX_FRAME)
    path.chmod(0o600)
    # Warm up the requested GPU model without opening the microphone. Arming
    # remains exclusively a user action through the registered browser.
    if args.engine_mode in {"both", "wav2vec2"}:
        listener.wav2vec_loading = asyncio.create_task(listener.prepare_wav2vec())
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
    parser.add_argument("--model", type=Path, default=BASE / "models/vosk-model-small-vn-0.4")
    parser.add_argument("--source", help="PulseAudio/PipeWire source name; default source otherwise")
    parser.add_argument("--max-seconds", type=int, default=0, help="0: listen until disabled or locked")
    parser.add_argument("--silence-seconds", type=float, default=15, help="Voice inactivity timeout; 0 keeps Voice open until a stop command")
    parser.add_argument("--engine-mode", choices=("both", "vosk", "wav2vec2"), default="wav2vec2")
    parser.add_argument("--wav2vec-model", type=Path, default=BASE / "models/wav2vec2-base-vietnamese-250h")
    asyncio.run(main(parser.parse_args()))
