#!/usr/bin/env python3
"""Explicit, bounded local enrollment; replay never connects to Chrome.

No microphone opens until the user clicks Record. All audio and reports stay in
recordings/ (ignored by Git). Only the public reading script belongs in Git.
"""
import argparse
from array import array
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import selectors
import subprocess
import sys
import threading
import time
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
RATE = 16000
FRAME = 3200


def reading_plan():
    rows = [('noise', '', 'Giữ yên lặng; để tiếng quạt/ồn phòng như bình thường.', 'dev', 10)]
    for n in range(5):
        rows.append(('wake', 'Hey GPT', 'Đọc bằng giọng thường ngày, không cần cố phát âm tiếng Anh.',
                     'dev' if n < 3 else 'test', 6))
    for word in ('hết', 'kết thúc', 'dừng lại', 'done'):
        for split in ('dev', 'test'):
            rows.append(('stop', word, 'Chờ tín hiệu xanh, nói riêng câu lệnh rồi nghỉ.', split, 6))
    for n, text in enumerate(('Tôi vẫn chưa nói hết.', 'Câu này có dấu chấm hết.',
                              'Đừng dừng lại, tôi đang nói.', 'Kết thúc bài này bằng một ví dụ.',
                              'Hôm nay trời đẹp, tôi muốn hỏi một câu.')):
        rows.append(('negative', text, 'Đọc liền cả câu tự nhiên; không nghỉ riêng trước từ cuối.',
                     'dev' if n < 2 else 'test', 6))
    rows.append(('noise', '', 'Giữ yên lặng; có thể gõ bàn phím vài giây như khi làm việc.', 'test', 10))
    return [dict(id=f'{n:02d}', kind=kind, text=text, hint=hint, split=split, seconds=seconds)
            for n, (kind, text, hint, split, seconds) in enumerate(rows, 1)]


def typing_plan(language='en'):
    if language=='vi':
        rows=[('noise','','Giữ yên lặng; để tiếng ồn phòng như bình thường.','dev',8)]
        phrases=[('typing','nhập lệnh'),('typing','gõ câu'),('typing-stop','dừng nhập'),
                 ('typing-stop','ngừng nhập'),('typing-stop','hết'),('typing-stop','kết thúc')]
        for take in range(5):
            for kind,text in phrases:
                rows.append((kind,text,'Chờ READ NOW, nói một lần bằng giọng thường ngày rồi nghỉ.',
                             'dev' if take<3 else 'test',6))
        for index,text in enumerate(('Tôi chưa nói hết.', 'Kết thúc câu này bằng một ví dụ.',
                                    'Tôi muốn nhập lệnh sau khi đọc hướng dẫn.', 'Bạn gõ câu này vào đâu?',
                                    'Đừng dừng nhập khi tôi vẫn đang nói.', 'Tôi chưa muốn ngừng nhập văn bản.',
                                    'Hôm nay tôi có một câu hỏi.', 'Hey GPT')):
            rows.append(('negative',text,'Đọc liền cả câu tự nhiên; không tách riêng từ khóa.',
                         'dev' if index<4 else 'test',6))
        rows.append(('noise','','Giữ yên lặng; gõ bàn phím vài giây như khi làm việc.','test',8))
        return [dict(id=f'{i:02d}',kind=kind,text=text,hint=hint,split=split,seconds=seconds)
                for i,(kind,text,hint,split,seconds) in enumerate(rows,1)]
    rows=[('noise','','Keep the usual room noise; do not speak.','dev',8)]
    phrases=[('typing','typing this'),('typing','type this'),('typing-stop','stop typing'),
             ('typing-stop','end typing'),('typing-stop','typing end')]
    for take in range(5):
        for kind,text in phrases:
            rows.append((kind,text,'Say it once in your everyday voice, then stay quiet.',
                         'dev' if take<3 else 'test',6))
    for index,text in enumerate(('I am typing this sentence.', 'Please type this address for me.',
                                 "Do not stop typing yet.", 'We can end typing after lunch.',
                                 'The phrase typing end is unusual.', 'Hey GPT')):
        rows.append(('negative',text,'Read the whole sentence naturally, without a separate command.',
                     'dev' if index<3 else 'test',6))
    rows.append(('noise','','Stay quiet; type on your keyboard briefly if you like.','test',8))
    return [dict(id=f'{i:02d}',kind=kind,text=text,hint=hint,split=split,seconds=seconds)
            for i,(kind,text,hint,split,seconds) in enumerate(rows,1)]


def control(command):
    result=subprocess.run(['/usr/bin/python3','-B',str(ROOT/'hey_gpt_ctl.py'),command],
                          stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=15)
    if result.returncode:raise RuntimeError('Could not update the Hey GPT background listener.')


def private_json(path, value):
    tmp = path.with_suffix(path.suffix + '.tmp')
    with open(tmp, 'w', encoding='utf-8') as handle:
        os.chmod(tmp, 0o600)
        json.dump(value, handle, ensure_ascii=False, indent=2)
    tmp.replace(path)


def read_wav(path):
    with wave.open(str(path), 'rb') as handle:
        if (handle.getnchannels(), handle.getsampwidth(), handle.getframerate()) != (1, 2, RATE):
            raise ValueError('Cần WAV mono PCM16 16000 Hz.')
        return handle.readframes(handle.getnframes())


def capture(source, seconds, stop, update):
    """Bounded Pulse capture, including cancellation while the source stalls."""
    proc = subprocess.Popen(['parec', '--raw', '--format=s16le', '--rate=16000', '--channels=1',
                             '--latency-msec=100', '--client-name=Hey GPT keyword recording',
                             f'--device={source}'], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    target = int(seconds * RATE * 2)
    frames = bytearray()
    selector = selectors.DefaultSelector()
    selector.register(proc.stdout, selectors.EVENT_READ)
    deadline = time.monotonic() + seconds + 5
    try:
        while len(frames) < target:
            if stop.is_set():
                raise RuntimeError('Đã dừng thu; câu đang thu không được lưu.')
            if time.monotonic() > deadline or proc.poll() is not None:
                raise RuntimeError('Nguồn micro không trả đủ âm thanh; kiểm tra nguồn thu.')
            if not selector.select(.1):
                continue
            chunk = os.read(proc.stdout.fileno(), min(FRAME, target - len(frames)))
            if not chunk:
                raise RuntimeError('Micro đã ngắt kết nối.')
            frames.extend(chunk)
            update(len(frames) / (RATE * 2))
        return bytes(frames)
    finally:
        selector.close()
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        proc.stdout.close()


class Studio:
    def __init__(self, root, sources, profile='voice'):
        self.root, self.sources = root, sources
        self.profile=profile
        self.paused=False
        self.plan = typing_plan('vi' if profile=='typing-vi' else 'en') if profile in {'typing','typing-vi'} else reading_plan()
        self.lock = threading.RLock()
        self.stop = threading.Event()
        self.session = None
        self.manifest = None
        self.state = dict(phase='idle', message='Chưa mở micro.', current=None, elapsed=0,
                          completed=[], report=None, session=None)

    def resume(self, session):
        session=session.resolve()
        if session.parent!=(self.root/'recordings').resolve():raise ValueError('Invalid recording session.')
        manifest=json.loads((session/'manifest.json').read_text())
        if manifest.get('profile','voice')!=self.profile:raise ValueError('Recording profile mismatch.')
        self.session,self.manifest=session,manifest
        self.plan=manifest['plan'];self.paused=self.profile in {'typing','typing-vi'}
        report=session/'typing-report.json'
        self.set(phase='done',session=str(session),completed=sorted({c['prompt'] for c in manifest['clips']}),
                 report=json.loads(report.read_text()) if report.exists() else None,message='Your saved recordings are ready.')

    def snapshot(self):
        with self.lock:
            return dict(self.state, plan=self.plan, sources=self.sources, profile=self.profile)

    def set(self, **values):
        with self.lock:
            self.state.update(values)

    def check_disarmed(self):
        status_path = Path(os.environ.get('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}')) / 'hey-gpt/status.json'
        if status_path.exists() and json.loads(status_path.read_text()).get('enabled'):
            raise RuntimeError('Tắt trợ lý Hey GPT trước khi thu để tránh mở Voice do từ khóa.')

    def begin(self, selection):
        with self.lock:
            if self.state['phase'] in ('preparing', 'recording', 'evaluating'):
                raise ValueError('Đang bận, hãy đợi hoặc dừng lượt hiện tại.')
            ids = [row['id'] for row in self.plan]
            if selection != 'all' and selection not in ids:
                raise ValueError('Câu đọc không hợp lệ.')
            if self.profile in {'typing','typing-vi'} and not self.paused:
                control('disable');self.paused=True
            self.check_disarmed()
            if self.session is None:
                parent = self.root / 'recordings'
                parent.mkdir(mode=0o700, exist_ok=True)
                self.session = parent / (datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + secrets.token_hex(3))
                self.session.mkdir(mode=0o700)
                self.manifest = dict(schema=1, profile=self.profile, created=datetime.now().astimezone().isoformat(),
                                     rate=RATE, sources=self.sources, plan=self.plan, clips=[],
                                     note='Local consented keyword recordings; no ChatGPT connection.')
                self.set(session=str(self.session))
            self.stop.clear()
            self.set(phase='preparing', message='Chuẩn bị thu.', report=None)
            threading.Thread(target=self.record, args=(selection,), daemon=True).start()

    def record(self, selection):
        rows = self.plan if selection == 'all' else [r for r in self.plan if r['id'] == selection]
        try:
            for row in rows:
                self.check_disarmed()
                self.set(phase='preparing', current=row, elapsed=0, message='Chuẩn bị: chờ tín hiệu xanh.')
                if self.stop.wait(2):
                    raise RuntimeError('Đã dừng thu. Các câu đã hoàn tất vẫn được giữ.')
                self.set(phase='recording', message='MIC ĐANG THU · im lặng 1,5 giây đầu, rồi đọc khi chữ chuyển xanh.')
                start = time.monotonic()
                with ThreadPoolExecutor(max_workers=len(self.sources)) as pool:
                    futures = {name: pool.submit(capture, source, row['seconds'], self.stop,
                                                (lambda elapsed: self.set(elapsed=round(elapsed, 1)))
                                                if name == next(iter(self.sources)) else lambda _: None)
                               for name, source in self.sources.items()}
                    audio = {name: future.result() for name, future in futures.items()}
                clips = []
                for source, pcm in audio.items():
                    filename = f'{row["id"]}-{source}-{secrets.token_hex(3)}.wav'
                    path = self.session / filename
                    with open(path, 'wb') as output:
                        os.chmod(path, 0o600)
                        with wave.open(output, 'wb') as handle:
                            handle.setnchannels(1)
                            handle.setsampwidth(2)
                            handle.setframerate(RATE)
                            handle.writeframes(pcm)
                    clips.append(dict(prompt=row['id'], source=source, file=filename,
                                      sha256=hashlib.sha256(pcm).hexdigest(),
                                      seconds=len(pcm)/(RATE*2), elapsed=round(time.monotonic()-start, 2)))
                # Retakes retain old audio; only the manifest's active clip changes.
                self.manifest['clips'] = [c for c in self.manifest['clips'] if c['prompt'] != row['id']] + clips
                private_json(self.session / 'manifest.json', self.manifest)
                completed = sorted({c['prompt'] for c in self.manifest['clips']})
                self.set(completed=completed)
            self.set(phase='done', elapsed=0, message='Đã đóng micro và lưu WAV. Bấm Chạy kiểm tra để thử lại bộ ghi âm.')
        except Exception as exc:
            self.stop.set()
            self.set(phase='error', message=str(exc), elapsed=0)

    def evaluate(self):
        with self.lock:
            if self.session is None or not self.manifest['clips']:
                raise ValueError('Chưa có bản ghi để kiểm tra.')
            if self.state['phase'] in ('preparing', 'recording', 'evaluating'):
                raise ValueError('Đang bận.')
            self.set(phase='evaluating', message='Micro đóng · Wav2Vec2 RTX 4060 + mẫu giọng đang đọc WAV.')
            threading.Thread(target=self.run_evaluation, daemon=True).start()

    def run_evaluation(self):
        if self.profile in {'typing','typing-vi'}:return self.run_typing_training()
        try:
            command = [str(self.root / '.venv/bin/python'), '-B', str(Path(__file__).resolve()),
                       'evaluate', str(self.session)]
            result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=600)
            if result.returncode:
                raise RuntimeError('Kiểm tra lỗi: ' + result.stderr.decode(errors='replace')[-700:])
            report = json.loads((self.session / 'report.json').read_text())
            self.set(phase='done', message='Đã kiểm tra và lưu report.json; không điều khiển Chrome.', report=report)
        except Exception as exc:
            self.set(phase='error', message=str(exc))

    def run_typing_training(self):
        try:
            self.check_disarmed()
            result=subprocess.run([str(self.root/'.venv/bin/python'),'-B',str(self.root/'tools/enroll_typing.py'),str(self.session)],
                                  stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,timeout=600)
            if result.returncode:raise RuntimeError(result.stderr.decode(errors='replace')[-1000:])
            report=json.loads((self.session/'typing-report.json').read_text())
            if report['installed']:
                # Recording disabled/unloaded all workers. Enable loads both
                # banks from disk; hot reload cannot run while they are absent.
                control('enable');self.paused=False
            message=('Your voice samples are active. The assistant is listening again.' if report['installed']
                     else ('Recording issues are listed below. Retry only those recordings.' if any(i.get('retry_recommended') for i in report.get('issues',[])) else 'Your recordings are saved. Recognition needs adjustment; no retake is required.'))
            self.set(phase='done',message=message,report=report)
        except Exception as exc:self.set(phase='error',message=str(exc))


def replay_segment(pcm, kind, wav, profile, vad=None):
    from audio_control import SpeechGate, stop_command
    from acoustic_keywords import acoustic_accept
    from wav2vec_recognizer import wake_match
    gate = SpeechGate()
    if vad is not None:vad.reset()
    # A replay represents one isolated command after a pause. Do not fake this
    # pause on real audio: the capture includes 1.5 s of instructed leading quiet.
    utterances = []
    for offset in range(0, len(pcm), FRAME):
        block=pcm[offset:offset+FRAME]
        _, utterance = gate.feed(block,voiced=vad.feed(block) if vad is not None else None)
        if utterance is not None:
            utterances.append(utterance)
    out = dict(wav2vec2=False, either=False, utterances=len(utterances), details=[])
    for utterance in utterances:
        if utterance.too_long:
            continue
        second = wav.decode(utterance.pcm)
        b = (wake_match(second, profile) if kind == 'wake' else stop_command(second, utterance.preceding_silence)) or acoustic_accept(second, kind, utterance.preceding_silence)
        out['wav2vec2'] |= bool(b)
        out['details'].append(dict(wav2vec2=second, preceding_silence=utterance.preceding_silence))
    out['either'] = out['wav2vec2']
    return out


def evaluate(session):
    from audio_control import rms
    from daemon import Listener
    from wav2vec_recognizer import Wav2VecVietnamese
    manifest = json.loads((session / 'manifest.json').read_text())
    listener = Listener()
    wav = Wav2VecVietnamese(ROOT / 'models/wav2vec2-base-vietnamese-250h')
    from voice_activity import VoiceActivity
    vad=VoiceActivity(ROOT/'models/silero-vad/silero_vad.jit',wav.torch,wav.np,wav.device)
    report = dict(vad='Silero CUDA', engines=['wav2vec2'], acoustic_templates=bool(wav.templates), created=datetime.now().astimezone().isoformat(), device=wav.device_name,
                  method='Actual SpeechGate, ASR and enrolled acoustic match rules; isolated clips, no Chrome. Dev clips overlap enrollment, test distances were previewed during development; not a blind evaluation.',
                  source_hashes={name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
                                 for name in ('audio_control.py', 'daemon.py', 'wake_words.py',
                                              'wav2vec_recognizer.py', 'acoustic_keywords.py', 'wake.local.json',
                                              'data/keyword-templates/templates.json',
                                              'data/keyword-templates/templates.npz', 'voice_activity.py', 'models/silero-vad/download.json') if (ROOT/name).exists()},
                  rows=[], summary={})
    prompts = {r['id']: r for r in manifest['plan']}
    for clip in manifest['clips']:
        row = prompts[clip['prompt']]
        path = (session / clip['file']).resolve()
        if path.parent != session.resolve():
            raise ValueError('Clip path escapes session.')
        pcm = read_wav(path)
        if hashlib.sha256(pcm).hexdigest() != clip['sha256']:
            raise ValueError('Clip hash mismatch.')
        wake = replay_segment(pcm, 'wake', wav, listener.wake_profile,vad)
        stop = replay_segment(pcm, 'stop', wav, listener.wake_profile,vad)
        samples = array('h', pcm)
        if sys.byteorder != 'little':
            samples.byteswap()
        report['rows'].append(dict(prompt=row['id'], source=clip['source'], split=row['split'],
                                   kind=row['kind'], expected=row['text'], file=clip['file'],
                                   rms=round(rms(pcm), 1),
                                   clipping_fraction=sum(abs(s) >= 32760 for s in samples)/max(1,len(samples)),
                                   wake=wake, stop=stop))
    for row in report['rows']:
        for mode in ('wake', 'stop'):
            for engine in ('wav2vec2', 'either'):
                key = f'{row["source"]}/{row["split"]}/{mode}/{engine}'
                totals = report['summary'].setdefault(key, dict(positive=0, hit=0, negative=0, false_trigger=0))
                positive = row['kind'] == mode
                totals['positive' if positive else 'negative'] += 1
                totals['hit' if positive else 'false_trigger'] += int(row[mode][engine])
    private_json(session / ('report-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '.json'), report)
    private_json(session / 'report.json', report)
    print(json.dumps(report['summary'], ensure_ascii=False))


def make_handler(studio, token, html):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def reply(self, code, data, mime='application/json'):
            encoded = data.encode() if isinstance(data, str) else json.dumps(data, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header('Content-Type', mime + '; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; form-action 'none'")
            self.send_header('Content-Length', str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def route(self):
            host = f'127.0.0.1:{self.server.server_port}'
            if self.headers.get('Host') != host:
                return None
            prefix = f'/{token}/'
            return self.path[len(prefix):] if self.path.startswith(prefix) else None

        def do_GET(self):
            route = self.route()
            if route == '':
                self.reply(200, html, 'text/html')
            elif route == 'status':
                self.reply(200, studio.snapshot())
            else:
                self.reply(404, {'error': 'Không tìm thấy.'})

        def do_POST(self):
            route = self.route()
            origin = f'http://127.0.0.1:{self.server.server_port}'
            if route not in ('record', 'stop', 'evaluate') or self.headers.get('Origin') != origin:
                return self.reply(403, {'error': 'Từ chối yêu cầu.'})
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 1024 or self.headers.get('Content-Type') != 'application/json':
                    raise ValueError('Yêu cầu không hợp lệ.')
                data = json.loads(self.rfile.read(size))
                if route == 'record':
                    studio.begin(data.get('selection'))
                elif route == 'stop':
                    studio.stop.set()
                else:
                    studio.evaluate()
                self.reply(200, studio.snapshot())
            except (ValueError, RuntimeError, TypeError, AttributeError) as exc:
                self.reply(400, {'error': str(exc)})
    return Handler


def serve(args):
    os.umask(0o077)
    sources = json.loads(subprocess.check_output(['pactl', '--format=json', 'list', 'sources']))
    names = {r['name'] for r in sources}
    selected = {'filtered': args.filtered, 'raw': args.raw}
    if any(value not in names or value.endswith('.monitor') for value in selected.values()):
        raise SystemExit('Không tìm thấy đúng hai nguồn micro; không tự đổi sang nguồn khác.')
    studio = Studio(ROOT, selected, args.profile)
    if args.session:studio.resume(args.session)
    token = secrets.token_urlsafe(24)
    is_typing=args.profile in {'typing','typing-vi'}
    html = Path(__file__).with_name('typing_studio.html' if is_typing else 'keyword_studio.html').read_text()
    if args.profile=='typing-vi':
        html=html.replace('Five recordings each of <b>typing this</b>, <b>type this</b>, <b>stop typing</b>, <b>end typing</b>, and <b>typing end</b>.',
                          'Five recordings each of <b>nhập lệnh</b>, <b>gõ câu</b>, <b>dừng nhập</b>, <b>ngừng nhập</b>, <b>hết</b>, and <b>kết thúc</b>.')
        html=html.replace('33 items','40 items').replace('Your voice · Dictation commands','Giọng của bạn · Lệnh nhập tiếng Việt')
    server = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(studio, token, html))
    server.daemon_threads = True
    url = f'http://127.0.0.1:{server.server_port}/{token}/'
    runtime = Path(os.environ.get('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}')) / 'hey-gpt'
    runtime.mkdir(mode=0o700,parents=True,exist_ok=True)
    info='vietnamese-typing-studio.json' if args.profile=='typing-vi' else 'typing-studio.json' if is_typing else 'recording-studio.json'
    private_json(runtime/info, {'url': url, 'pid': os.getpid()})
    print(url, flush=True)
    # A hard lifetime also bounds forgotten local servers. Captures are shorter.
    timer = threading.Timer(3600, server.shutdown)
    timer.daemon = True
    timer.start()
    try:
        server.serve_forever()
    finally:
        studio.stop.set()
        timer.cancel()
        server.server_close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Thu và thử lại từ khóa local, không mở ChatGPT.')
    commands = parser.add_subparsers(dest='command', required=True)
    recorder = commands.add_parser('serve')
    recorder.add_argument('--session',type=Path,help='Resume existing recordings without recording again')
    recorder.add_argument('--profile', choices=('voice','typing','typing-vi'), default='voice')
    recorder.add_argument('--filtered', default='mic_noise_suppressed')
    recorder.add_argument('--raw', default='alsa_input.pci-0000_00_1f.3.analog-stereo')
    replay = commands.add_parser('evaluate')
    replay.add_argument('session', type=Path)
    args = parser.parse_args()
    if args.command == 'serve':
        serve(args)
    else:
        evaluate(args.session.resolve())
