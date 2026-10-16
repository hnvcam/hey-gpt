import asyncio
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from audio_control import Utterance
from daemon import Listener
from wav2vec_recognizer import ctc_words, wake_match


def result(text, score=.95):
    return {'text': text, 'result': [{'word': w, 'conf': score} for w in text.split()]}


class Tokenizer:
    word_delimiter_token_id = 4
    all_special_ids = [0, 9]
    def decode(self, ids, **kwargs):
        return ''.join({1:'h', 2:'ế', 3:'t', 4:'|'}[n] for n in ids)


class CTC(unittest.TestCase):
    def test_collapse_blank_delimiter_and_repeated_character(self):
        decoded = ctc_words([0,1,1,2,3,4,1,0,1,9], [.9]*10, Tokenizer(), 0)
        self.assertEqual(decoded['text'], 'hết hh')
        self.assertAlmostEqual(decoded['result'][0]['conf'], .9)

    def test_peak_score_per_run_not_blank_confidence(self):
        decoded = ctc_words([0,1,1,2,3,0], [1,.4,.9,.8,.85,1], Tokenizer(), 0)
        self.assertAlmostEqual(decoded['result'][0]['conf'], .85)

    def test_full_phrase_only_no_substring_or_low_score(self):
        for text in ['Hey GPT!', 'hây gi pi ti', 'hay gờ pê tê', 'hê gê bê tê']:
            self.assertTrue(wake_match(result(text)))
        for text in ['gpt', 'hey', 'tôi nói hey gpt', 'hey gờ pi', 'hôm nay trời đẹp']:
            self.assertFalse(wake_match(result(text)))
        self.assertFalse(wake_match(result('hey gpt', .5)))
        self.assertFalse(wake_match(result('hey gpt', float('nan'))))


class ParallelRecognition(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {'XDG_RUNTIME_DIR':self.temp.name})
        self.env.start()
        self.listener = Listener(Path('missing'))
        self.listener.enabled = self.listener.mic = True
        self.listener.phase_since = 100
        self.writer = Mock()
        self.writer.is_closing.return_value = False
        self.unlock = patch('daemon.unlocked_session', AsyncMock(return_value='7'))
        self.unlock.start()
        self.utterance = Utterance(b'\0'*3200, 1.2, 1000, False)

    async def asyncTearDown(self):
        jobs = list(self.listener.recognition_jobs)
        if jobs: await asyncio.gather(*jobs)
        self.unlock.stop()
        self.env.stop()
        self.temp.cleanup()

    def actions(self, kind):
        return [json.loads(call.args[0]) for call in self.writer.write.call_args_list
                if json.loads(call.args[0]).get('type') == kind]

    async def drain(self):
        await asyncio.gather(*list(self.listener.recognition_jobs))

    async def test_either_engine_can_trigger_without_the_other(self):
        context = self.listener.recognition_context()
        await self.listener.recognize('vosk', lambda _: result('không khớp'),
                                      self.utterance, self.writer, '7', context)
        await self.listener.recognize('wav2vec2', lambda _: result('hey gpt'),
                                      self.utterance, self.writer, '7', context)
        self.assertEqual(len(self.actions('wake')), 1)
        self.assertEqual(self.listener.last_recognizer, 'wav2vec2')

    async def test_both_match_emit_only_one_wake(self):
        self.listener.submit_recognition('vosk', lambda _: result('hây gi pi ti'), self.utterance,self.writer,'7')
        self.listener.submit_recognition('wav2vec2', lambda _: result('hey gpt'), self.utterance,self.writer,'7')
        await self.drain()
        self.assertEqual(len(self.actions('wake')), 1)
        self.assertEqual(self.listener.wake_matches, 1)

    async def test_microphone_loop_stays_responsive_while_one_engine_is_busy(self):
        release, entered = threading.Event(), threading.Event()
        def slow(_):
            entered.set()
            release.wait(2)
            return result('hey gpt')
        self.listener.submit_recognition('wav2vec2',slow,self.utterance,self.writer,'7')
        await asyncio.to_thread(entered.wait, 1)
        try:
            # No queued duplicate audio, no blocking the event loop.
            self.listener.submit_recognition('wav2vec2',slow,self.utterance,self.writer,'7')
            self.assertEqual(self.listener.engines['wav2vec2']['skipped'], 1)
            self.listener.submit_recognition('vosk',lambda _:result('hây gi pi ti'),self.utterance,self.writer,'7')
            for _ in range(100):
                if self.listener.phase == 'opening': break
                await asyncio.sleep(.005)
            self.assertEqual(len(self.actions('wake')), 1)
        finally:
            release.set()
        await self.drain()
        self.assertEqual(len(self.actions('wake')), 1)

    async def test_stale_result_after_disable_enable_is_ignored(self):
        context = self.listener.recognition_context()
        await self.listener.disarm()
        self.listener.enabled = True
        await self.listener.recognize('wav2vec2',lambda _:result('hey gpt'),self.utterance,self.writer,'7',context)
        self.assertEqual(self.actions('wake'), [])

    async def test_stop_requires_whole_utterance_and_pause_on_either_engine(self):
        self.listener.phase = 'conversation'
        self.listener.session = 'session-token'
        context = self.listener.recognition_context()
        await self.listener.recognize('wav2vec2',lambda _:result('dấu chấm hết'),self.utterance,self.writer,'7',context)
        short = Utterance(self.utterance.pcm,.3,1000,False)
        await self.listener.recognize('wav2vec2',lambda _:result('hết'),short,self.writer,'7',context)
        self.assertEqual(self.actions('stop'), [])
        self.listener.submit_recognition('wav2vec2',lambda _:result('hết'),self.utterance,self.writer,'7')
        self.listener.submit_recognition('vosk',lambda _:result('hết'),self.utterance,self.writer,'7')
        await self.drain()
        self.assertEqual(len(self.actions('stop')), 1)

    async def test_model_missing_visible_not_silently_claimed_as_ready(self):
        with patch('daemon.Wav2VecVietnamese', side_effect=FileNotFoundError):
            await self.listener.prepare_wav2vec()
        self.assertEqual(self.listener.snapshot()['recognizers']['wav2vec2']['state'], 'model-missing')
        self.assertTrue(self.listener.enabled)

    async def test_branch_failure_preserves_other_engine(self):
        def broken(_): raise RuntimeError('private transcript must not be logged')
        context = self.listener.recognition_context()
        await self.listener.recognize('wav2vec2',broken,self.utterance,self.writer,'7',context)
        self.assertEqual(self.listener.engines['wav2vec2']['state'], 'decode-error')
        self.assertTrue(self.listener.enabled)
        await self.listener.recognize('vosk',lambda _:result('hây gi pi ti'),self.utterance,self.writer,'7',context)
        self.assertEqual(len(self.actions('wake')), 1)

    async def test_expired_result_does_not_operate_browser(self):
        context = self.listener.recognition_context()
        self.assertTrue(self.listener.result_is_current(context, time.monotonic()))
        self.assertFalse(self.listener.result_is_current(context, time.monotonic()-6))


if __name__ == '__main__': unittest.main()
