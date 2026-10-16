import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request
import wave

path = Path(__file__).resolve().parents[1] / 'tools/keyword_dataset.py'
spec = importlib.util.spec_from_file_location('keyword_dataset', path)
dataset = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dataset)


class RecordingTests(unittest.TestCase):
    def test_plan_repeats_each_keyword_and_has_unseen_negatives(self):
        plan = dataset.reading_plan()
        self.assertEqual(len(plan), 20)
        self.assertEqual(sum(r['text'] == 'Hey GPT' for r in plan), 5)
        for word in ('hết', 'kết thúc', 'dừng lại', 'done'):
            self.assertEqual({r['split'] for r in plan if r['text'] == word}, {'dev', 'test'})
        self.assertEqual(sum(r['kind'] == 'negative' for r in plan), 5)
        self.assertEqual(sum(r['kind'] == 'noise' for r in plan), 2)

    def test_capture_only_after_start_and_retakes_preserve_original_audio(self):
        with tempfile.TemporaryDirectory() as directory:
            studio = dataset.Studio(Path(directory), {'filtered': 'test-source', 'raw': 'raw-source'})
            self.assertIsNone(studio.session)
            pcm = b'\0\0' * (dataset.RATE * 6)
            with patch.object(studio, 'check_disarmed'), patch.object(dataset, 'capture', return_value=pcm), \
                 patch.object(studio.stop, 'wait', return_value=False):
                studio.session = Path(directory)
                studio.manifest = {'clips': []}
                studio.record('02')
                original = {c['file'] for c in studio.manifest['clips']}
                studio.record('02')
            self.assertEqual(studio.state['phase'], 'done')
            self.assertEqual(len(studio.manifest['clips']), 2)
            self.assertEqual(len(list(Path(directory).glob('*.wav'))), 4)
            self.assertTrue(all((Path(directory)/filename).exists() for filename in original))
            for clip in studio.manifest['clips']:
                file = Path(directory)/clip['file']
                self.assertEqual(file.stat().st_mode & 0o777, 0o600)
                self.assertEqual(dataset.read_wav(file), pcm)

    def test_cancel_does_not_save_partial_sentence(self):
        with tempfile.TemporaryDirectory() as directory:
            studio = dataset.Studio(Path(directory), {'raw': 'source'})
            studio.session = Path(directory)
            studio.manifest = {'clips': []}
            studio.stop.set()
            with patch.object(studio, 'check_disarmed'), patch.object(dataset, 'capture') as capture:
                studio.record('02')
            capture.assert_not_called()
            self.assertEqual(studio.state['phase'], 'error')
            self.assertFalse(list(Path(directory).glob('*.wav')))

    def test_reject_invalid_audio_format(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory)/'bad.wav'
            with wave.open(str(file), 'wb') as handle:
                handle.setnchannels(2)
                handle.setsampwidth(2)
                handle.setframerate(48000)
                handle.writeframes(b'\0'*100)
            with self.assertRaises(ValueError):
                dataset.read_wav(file)

    def test_web_requests_require_secret_host_and_origin(self):
        with tempfile.TemporaryDirectory() as directory:
            studio = dataset.Studio(Path(directory), {'raw': 'source'})
            server = dataset.ThreadingHTTPServer(('127.0.0.1', 0), dataset.make_handler(studio, 'secret', '<p>test</p>'))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f'http://127.0.0.1:{server.server_port}'
            try:
                with urllib.request.urlopen(base+'/secret/status') as response:
                    self.assertEqual(json.load(response)['phase'], 'idle')
                for request in (
                    urllib.request.Request(base+'/wrong/status'),
                    urllib.request.Request(base+'/secret/status', headers={'Host': 'attacker.invalid'}),
                    urllib.request.Request(base+'/secret/record', data=b'{"selection":"all"}',
                                           headers={'Origin': 'https://attacker.invalid', 'Content-Type': 'application/json'}),
                    urllib.request.Request(base+'/secret/record', data=b'{"selection":"../file"}',
                                           headers={'Origin': base, 'Content-Type': 'application/json'}),
                ):
                    with self.assertRaises(urllib.error.HTTPError):
                        urllib.request.urlopen(request)
                self.assertIsNone(studio.session)
            finally:
                server.shutdown()
                server.server_close()


if __name__ == '__main__':
    unittest.main()
