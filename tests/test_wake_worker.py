"""Real child-process lifecycle with a simulated model; no CUDA or microphone."""
from concurrent.futures import ThreadPoolExecutor
import time
import unittest
from unittest.mock import patch

from wake_worker import WakeModels


def fake_models(connection, mode):
    if mode == 'slow-load':
        time.sleep(30)
        return
    connection.send({'device_name':'simulated GPU', 'templates':True, 'typing_templates':True})
    try:
        while True:
            action, args = connection.recv()
            if mode == 'error':
                connection.send({'error':'wake-operation-failed'})
                continue
            if action == 'decode' and mode == 'slow-decode':
                time.sleep(30)
            result = ({'text':'hey gpt','result':[]} if action == 'decode' else
                      2 if action == 'reload_typing_templates' else True)
            connection.send({'result':result,'speech':action == 'feed',
                             'probability':.9 if action == 'feed' else 0., 'typing_templates':True})
    except EOFError:
        pass


class WorkerLifecycle(unittest.TestCase):
    def wait_until(self, condition):
        deadline=time.monotonic()+5
        while not condition() and time.monotonic()<deadline:
            time.sleep(.01)
        self.assertTrue(condition())

    def test_proxy_and_complete_process_exit_then_reload(self):
        with patch('wake_worker.serve', fake_models):
            for _ in range(2):
                worker=WakeModels('ready')
                try:
                    worker.load()
                    self.assertEqual(worker.device_name,'simulated GPU')
                    self.assertEqual(worker.decode(b'\0'*3200)['text'],'hey gpt')
                    self.assertTrue(worker.vad.feed(b'\0'*3200))
                    self.assertEqual(worker.vad.probability,.9)
                    worker.vad.reset()
                    self.assertFalse(worker.vad.speech)
                    self.assertTrue(worker.match_typing(b'\0'*3200,'trigger'))
                    self.assertEqual(worker.reload_typing_templates(),2)
                finally:
                    worker.close()
                self.assertFalse(worker.proc.is_alive())
                worker.close()

    def test_close_interrupts_loading_and_inference(self):
        for mode in ('slow-load','slow-decode'):
            with self.subTest(mode=mode), patch('wake_worker.serve', fake_models), ThreadPoolExecutor() as pool:
                worker=WakeModels(mode)
                try:
                    if mode=='slow-load':
                        pending=pool.submit(worker.load)
                        self.wait_until(lambda:worker.proc is not None and worker.proc.pid is not None)
                    else:
                        worker.load()
                        pending=pool.submit(worker.decode,b'\0'*3200)
                        self.wait_until(worker.requests.locked)
                    worker.close()
                    with self.assertRaises((RuntimeError, EOFError, OSError)):
                        pending.result(timeout=3)
                    self.assertFalse(worker.proc.is_alive())
                finally:
                    worker.close()

    def test_cancel_before_load_cannot_start_late_worker(self):
        worker=WakeModels('unused')
        worker.close()
        with self.assertRaisesRegex(RuntimeError,'wake-worker-closed'):
            worker.load()
        self.assertIsNone(worker.proc)

    def test_failed_request_closes_worker_before_another_request(self):
        with patch('wake_worker.serve',fake_models):
            worker=WakeModels('error')
            try:
                worker.load()
                with self.assertRaisesRegex(RuntimeError,'wake-operation-failed'):
                    worker.decode(b'\0'*3200)
                self.assertFalse(worker.proc.is_alive())
                with self.assertRaisesRegex(RuntimeError,'wake-worker-closed'):
                    worker.vad.feed(b'\0'*3200)
            finally:
                worker.close()
