"""Simulated lifecycle: no microphone, CUDA or real keystrokes."""
import asyncio
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch
from audio_control import Utterance
from dictation import Parakeet, Recording, command_match, keyboard_text, validate_settings, save_settings, load_settings
import daemon
from native_host import clean_message


def result(text, conf=.99):
    return {'text':text,'result':[{'word':w,'conf':conf} for w in text.split()]}


class AudioAndSettings(unittest.TestCase):
    def test_silence_5_and_10_and_bounded_recording(self):
        for timeout in (5,10):
            record=Recording(timeout);record.feed(b'1'*3200,True)
            for _ in range(timeout*10-1):self.assertFalse(record.feed(b'\0'*3200,False))
            self.assertTrue(record.feed(b'\0'*3200,False))
        record=Recording()
        for _ in range(1799):self.assertFalse(record.feed(b'1'*3200,True))
        self.assertTrue(record.feed(b'1'*3200,True))
        for _ in range(50):record.feed(b'1'*3200,True)
        self.assertLessEqual(len(record.audio),180*32000)

    def test_only_complete_confident_phrases_match(self):
        for phrase in ('typing this','type this','stop typing'):
            self.assertTrue(command_match(result(phrase),{phrase}))
            for value in (result('please '+phrase),result(phrase,.5),result(phrase,float('nan'))):
                self.assertFalse(command_match(value,{phrase}))

    def test_no_enter_or_control_characters(self):
        self.assertEqual(keyboard_text('  Hello.\nNext line\t“yes”—it’s fine. '),'Hello. Next line "yes"-it\'s fine.')
        for bad in ('x\x1by','x\0y','你好'):
            with self.assertRaises(ValueError):keyboard_text(bad)

    def test_settings_persist_and_reject_bad_types(self):
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{'XDG_CONFIG_HOME':folder}):
            self.assertEqual(load_settings(),{'autoload':True,'silence_seconds':5})
            save_settings({'autoload':False,'silence_seconds':10})
            self.assertEqual(load_settings(),{'autoload':False,'silence_seconds':10})
        for bad in ({'autoload':'no'},{'silence_seconds':True},{'silence_seconds':0},{'extra':1}):
            with self.assertRaises(ValueError):validate_settings(bad)


class Lifecycle(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.env=patch.dict(os.environ,{'XDG_RUNTIME_DIR':self.temp.name,'XDG_CONFIG_HOME':self.temp.name});self.env.start()
        self.listener=daemon.Listener(Path('unused'))
        self.listener.enabled=self.listener.mic=True
        self.unlock=patch('daemon.unlocked_session',AsyncMock(return_value='7'));self.unlock.start()
        self.listener.parakeet=Mock(state='ready',error=None)
        self.listener.parakeet.snapshot.return_value={'state':'ready','error':None}
        self.listener.parakeet.load=AsyncMock(side_effect=lambda:setattr(self.listener.parakeet,'state','ready'))
        self.listener.parakeet.unload=AsyncMock()
        self.listener.parakeet.transcribe=AsyncMock(return_value='Hello world.')
        self.writer=Mock();self.writer.is_closing.return_value=False

    async def asyncTearDown(self):
        await self.listener.disarm()
        self.unlock.stop();self.env.stop();self.temp.cleanup()

    async def test_ready_chime_precedes_recording_without_chrome(self):
        async def cue(*args):
            self.assertEqual(self.listener.phase,'typing-loading')
            self.assertIsNone(self.listener.recording)
        with patch('daemon.command',side_effect=cue),patch.object(self.listener,'ensure_keyboard',AsyncMock()),patch.object(self.listener,'launch_browser',AsyncMock()) as chrome:
            self.listener.begin_dictation();await self.listener.dictation_job
            self.assertEqual(self.listener.phase,'typing-recording')
            chrome.assert_not_called()

    async def test_stop_command_audio_is_removed(self):
        self.listener.phase='typing-recording';self.listener.recording=Recording()
        for pcm,voice in ((b'a'*32000,True),(b'b'*32000,False),(b'c'*32000,True)):
            self.listener.recording.feed(pcm,voice)
        self.listener.english=Mock();self.listener.english.decode.return_value=result('stop typing')
        with patch.object(self.listener,'transcribe_and_type',AsyncMock()) as finish:
            self.listener.submit_english(Utterance(b'c'*32000,1.2,500,False),'7')
            await asyncio.gather(*self.listener.recognition_jobs);await self.listener.dictation_job
            self.assertEqual(finish.await_args.args[0],b'a'*32000+b'b'*32000)

    async def test_stop_command_alone_produces_no_text(self):
        self.listener.phase='typing-recording';self.listener.recording=Recording()
        self.listener.recording.feed(b'0'*32000,False)
        self.listener.recording.feed(b'c'*32000,True)
        with patch.object(self.listener,'transcribe_and_type',AsyncMock()) as finish:
            self.listener.finish_dictation(32000);await self.listener.dictation_job
            self.assertEqual(finish.await_args.args[0],b'')

    async def test_stop_inside_a_sentence_is_dictated(self):
        self.listener.phase='typing-recording';self.listener.recording=Recording()
        self.listener.english=Mock();self.listener.english.decode.return_value=result('please stop typing this word')
        self.listener.submit_english(Utterance(b'x'*32000,2,500,False),'7')
        await asyncio.gather(*self.listener.recognition_jobs)
        self.assertEqual(self.listener.phase,'typing-recording')

    async def test_disable_cancels_transcription(self):
        self.listener.phase='typing-transcribing';entered=asyncio.Event()
        async def slow(*args):entered.set();await asyncio.Event().wait()
        self.listener.parakeet.transcribe.side_effect=slow
        self.listener.dictation_job=asyncio.create_task(self.listener.transcribe_and_type(b'x'*32000))
        await entered.wait();await self.listener.disarm()
        self.assertFalse(self.listener.enabled);self.assertIsNone(self.listener.dictation_job)

    async def test_stale_english_result_cannot_trigger(self):
        self.listener.english=Mock();self.listener.english.decode.return_value=result('typing this')
        context=self.listener.recognition_context();self.listener.recognition_epoch+=1
        await self.listener.recognize_english(Utterance(b'x',1,500,False),'7',context,None)
        self.assertEqual(self.listener.phase,'wake')

    async def test_browser_disconnect_preserves_recording(self):
        self.listener.phase='typing-recording';self.listener.recording=Recording();self.listener.browser=self.writer
        self.listener.browser_disconnected()
        self.assertEqual(self.listener.phase,'typing-recording')

    async def test_unload_cancels_recording_and_releases_worker(self):
        self.listener.phase='typing-recording';self.listener.recording=Recording()
        await self.listener.dispatch({'cmd':'model-unload'},self.writer)
        self.listener.parakeet.unload.assert_awaited_once()
        self.assertIsNone(self.listener.recording);self.assertEqual(self.listener.phase,'wake')

    async def test_browser_cannot_send_local_dictation_commands(self):
        for cmd in ('typing','model-load','model-unload','dictation-settings'):
            with self.assertRaises(ValueError):clean_message({'cmd':cmd})

    async def test_insert_text_and_return_to_wake_without_exposing_transcript(self):
        self.listener.phase='typing-transcribing';keyboard=Mock(returncode=None)
        keyboard.stdin.drain=AsyncMock();keyboard.stdout.readline=AsyncMock(return_value=b'{"state":"typed"}\n')
        self.listener.keyboard=keyboard
        with patch.object(self.listener,'ensure_keyboard',AsyncMock()):
            await self.listener.transcribe_and_type(b'x'*32000)
        self.assertEqual(json.loads(keyboard.stdin.write.call_args.args[0]),{'text':'Hello world.','session':'7'})
        self.assertEqual(self.listener.phase,'wake');self.assertEqual(self.listener.dictation_count,1)
        self.assertNotIn('Hello world',json.dumps(self.listener.snapshot()))
        self.listener.keyboard=None

    async def test_screen_lock_discards_transcript(self):
        self.listener.phase='typing-transcribing'
        with patch('daemon.unlocked_session',AsyncMock(return_value=None)),patch.object(self.listener,'ensure_keyboard',AsyncMock()) as keyboard:
            await self.listener.transcribe_and_type(b'x'*32000);keyboard.assert_not_called()
        self.assertEqual(self.listener.phase,'wake')


class WorkerLifecycle(unittest.IsolatedAsyncioTestCase):
    def worker(self):
        proc=Mock(returncode=None)
        proc.stdout.readline=AsyncMock(return_value=b'{"state":"ready","device":"RTX 4060"}\n')
        proc.stdin.drain=AsyncMock();proc.wait=AsyncMock(return_value=0)
        return proc
    async def test_load_is_idempotent_and_unload_terminates_process(self):
        proc=self.worker();model=Parakeet(Path('unused'))
        with patch('dictation.asyncio.create_subprocess_exec',AsyncMock(return_value=proc)) as spawn:
            await model.load();await model.load()
            spawn.assert_awaited_once()
            self.assertEqual(model.state,'ready')
            await model.unload();await model.unload()
        proc.terminate.assert_called_once()
        self.assertEqual(model.state,'unloaded');self.assertIsNone(model.proc)
    async def test_decode_failure_closes_worker_and_requires_new_load(self):
        proc=self.worker();model=Parakeet(Path('unused'));model.proc=proc;model.state='ready'
        proc.stdout.readline.return_value=b'{"error":"transcription-failed"}\n'
        with self.assertRaises(RuntimeError):await model.transcribe(b'00')
        self.assertEqual(model.state,'error');self.assertIsNone(model.proc)
        proc.terminate.assert_called_once()


class TriggerReliability(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=Lifecycle.asyncSetUp
    asyncTearDown=Lifecycle.asyncTearDown
    async def test_parakeet_recovers_a_trigger_vosk_misheard(self):
        self.listener.english=Mock();self.listener.english.decode.return_value=result('type nice',.4)
        self.listener.parakeet.transcribe.return_value='Typing this.'
        with patch.object(self.listener,'begin_dictation') as begin:
            await self.listener.recognize_english(Utterance(b'x'*32000,1,500,False),'7',self.listener.recognition_context(),None)
            begin.assert_called_once()
        self.assertEqual(self.listener.english_stats['parakeet_matches'],1)
    async def test_exact_lower_confidence_phrase_needs_grammar_agreement(self):
        weak=result('typing this',.6)
        self.assertFalse(command_match(weak,{'typing this'}))
        weak['grammar_confirmed']='typing this'
        self.assertTrue(command_match(weak,{'typing this'}))
        weak['text']='please typing this'
        self.assertFalse(command_match(weak,{'typing this'}))
    async def test_unloaded_model_is_never_loaded_for_keyword_scanning(self):
        self.listener.english=Mock();self.listener.english.decode.return_value=result('other words')
        self.listener.parakeet.state='unloaded'
        await self.listener.recognize_english(Utterance(b'x'*32000,1,500,False),'7',self.listener.recognition_context(),None)
        self.listener.parakeet.transcribe.assert_not_called();self.listener.parakeet.load.assert_not_called()
    async def test_ordinary_sentence_cannot_trigger_even_with_keyword_inside(self):
        self.listener.english=Mock();self.listener.english.decode.return_value=result('I am typing this sentence')
        self.listener.parakeet.transcribe.return_value='I am typing this sentence.'
        with patch.object(self.listener,'begin_dictation') as begin:
            await self.listener.recognize_english(Utterance(b'x'*32000,1,500,False),'7',self.listener.recognition_context(),None)
            begin.assert_not_called()
    async def test_stale_parakeet_trigger_cannot_start_after_unload_or_disable(self):
        self.listener.english=Mock();self.listener.english.decode.return_value=result('type nice')
        async def late(_):
            self.listener.recognition_epoch+=1
            return 'Typing this.'
        self.listener.parakeet.transcribe.side_effect=late
        with patch.object(self.listener,'begin_dictation') as begin:
            await self.listener.recognize_english(Utterance(b'x'*32000,1,500,False),'7',self.listener.recognition_context(),None)
            begin.assert_not_called()
    async def test_status_counters_never_include_the_transcript(self):
        self.listener.english=Mock();self.listener.english.decode.return_value=result('sensitive words')
        self.listener.parakeet.transcribe.return_value='Sensitive words.'
        await self.listener.recognize_english(Utterance(b'x'*32000,1,500,False),'7',self.listener.recognition_context(),None)
        self.assertNotIn('sensitive',json.dumps(self.listener.snapshot()).lower())
        self.assertEqual(self.listener.english_stats['checks'],1)

    async def test_parakeet_recovers_stop_and_excludes_its_audio(self):
        self.listener.phase='typing-recording';self.listener.recording=Recording()
        self.listener.recording.feed(b'a'*32000,True)
        self.listener.recording.feed(b'c'*32000,True)
        self.listener.english=Mock();self.listener.english.decode.return_value=result('stopped typing',.6)
        self.listener.parakeet.transcribe.return_value='Stop typing.'
        with patch.object(self.listener,'transcribe_and_type',AsyncMock()) as finish:
            await self.listener.recognize_english(Utterance(b'c'*32000,1.2,500,False),'7',self.listener.recognition_context(),64000)
            await self.listener.dictation_job
            self.assertEqual(finish.await_args.args[0],b'a'*32000)
        self.assertEqual(self.listener.english_stats['parakeet_matches'],1)
