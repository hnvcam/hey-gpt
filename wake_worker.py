"""Disposable local GPU process for Vietnamese recognition and Silero VAD.

Only this child imports CUDA. Exiting it releases weights, allocator caches and
the CUDA context; the control service can remain connected to Chrome and the tray.
Audio travels through a private pipe and is never written to disk.
"""
import multiprocessing
from pathlib import Path
import threading


def serve(connection, model_path):
    from wav2vec_recognizer import Wav2VecVietnamese
    from voice_activity import VoiceActivity
    try:
        model = Wav2VecVietnamese(model_path)
        vad = VoiceActivity(Path(__file__).resolve().parent / 'models/silero-vad/silero_vad.jit',
                            model.torch, model.np, model.device)
        connection.send({'device_name': model.device_name, 'templates': bool(model.templates),
                         'typing_templates': bool(model.typing_templates)})
    except Exception as exc:
        allowed = {'gpu-not-configured', 'cuda-unavailable', 'wrong-cuda-gpu'}
        state = ('model-missing' if isinstance(exc, FileNotFoundError) else
                 'dependencies-missing' if isinstance(exc, ImportError) else
                 str(exc) if str(exc) in allowed else 'load-error')
        connection.send({'error': state})
        connection.close()
        return
    try:
        while True:
            action, args = connection.recv()
            try:
                if action == 'feed':
                    result = vad.feed(*args)
                elif action == 'reset':
                    result = vad.reset()
                elif action in {'decode', 'ctc_logits', 'match_typing', 'reload_typing_templates'}:
                    result = getattr(model, action)(*args)
                else:
                    raise ValueError('unknown-wake-operation')
                connection.send({'result': result, 'speech': vad.speech,
                                 'probability': vad.probability,
                                 'typing_templates': bool(model.typing_templates)})
            except Exception:
                connection.send({'error': 'wake-operation-failed'})
    except (EOFError, BrokenPipeError, ConnectionResetError):
        pass
    finally:
        connection.close()


class RemoteVoiceActivity:
    def __init__(self, worker):
        self.worker = worker
        self.speech = False
        self.probability = 0.

    def feed(self, pcm):
        return self.worker.request('feed', pcm)

    def reset(self):
        return self.worker.request('reset')


class WakeModels:
    def __init__(self, model_path):
        self.model_path = str(model_path)
        self.proc = None
        self.connection = None
        self.closed = False
        self.lifecycle = threading.Lock()
        self.requests = threading.Lock()
        self.vad = RemoteVoiceActivity(self)
        self.device_name = None
        self.templates = False
        self.typing_templates = False

    def load(self):
        # Publish the process before waiting for CUDA so Unload can interrupt a
        # slow load. close() also prevents a cancelled thread from starting later.
        with self.lifecycle:
            if self.closed:
                raise RuntimeError('wake-worker-closed')
            context = multiprocessing.get_context('spawn')
            self.connection, child = context.Pipe()
            self.proc = context.Process(target=serve, args=(child, self.model_path), daemon=True)
            try:
                self.proc.start()
            finally:
                child.close()
        try:
            reply = self.receive(180)
            with self.lifecycle:
                if self.closed:
                    raise RuntimeError('wake-worker-closed')
                self.device_name = reply['device_name']
                self.templates = reply['templates']
                self.typing_templates = reply['typing_templates']
        except BaseException:
            self.close()
            raise

    def receive(self, timeout):
        connection = self.connection
        if connection is None or not connection.poll(timeout):
            raise RuntimeError('wake-worker-timeout')
        reply = connection.recv()
        if 'error' in reply:
            raise RuntimeError(reply['error'])
        return reply

    def request(self, action, *args):
        with self.requests:
            if self.closed:
                raise RuntimeError('wake-worker-closed')
            try:
                self.connection.send((action, args))
                reply = self.receive(10)
            except Exception:
                # Never consume a late timed-out response as the answer to the
                # next VAD/recognition request. A fresh explicit load is needed.
                self.close()
                raise
            self.vad.speech = reply['speech']
            self.vad.probability = reply['probability']
            self.typing_templates = reply['typing_templates']
            return reply['result']

    def decode(self, pcm):
        return self.request('decode', pcm)

    def ctc_logits(self, pcm):
        return self.request('ctc_logits',pcm)

    def match_typing(self, pcm, kind):
        return self.request('match_typing', pcm, kind)

    def reload_typing_templates(self):
        return self.request('reload_typing_templates')

    def close(self):
        # Do not acquire the request lock: an in-flight load or inference must
        # never delay Unload. Process death interrupts its pipe read too.
        with self.lifecycle:
            self.closed = True
            if self.proc and self.proc.pid:
                if self.proc.is_alive():
                    self.proc.terminate()
                self.proc.join(2)
                if self.proc.is_alive():
                    self.proc.kill()
                    self.proc.join()
            if self.connection:
                self.connection.close()
