"""Shared command policy and real controller routing with simulated decoders."""
import asyncio
import json
import unittest
from unittest.mock import AsyncMock, Mock, patch

from audio_control import Utterance
from commands import STOP_PHRASES, recognize_command
from dictation import Recording, terminal_stop
import test_dictation as fixtures
from test_dictation import result


class CommandPolicy(unittest.TestCase):
    def test_every_end_alias_has_the_same_meaning_for_both_decoders_and_active_modes(self):
        for phrase in STOP_PHRASES:
            for language in ('en', 'vi'):
                for phase in ('conversation', 'typing-recording'):
                    with self.subTest(phrase=phrase, language=language, phase=phase):
                        self.assertEqual(recognize_command(result(phrase), language, phase, .35).action, 'stop')
                        self.assertIsNone(recognize_command(result(phrase), language, phase, .2))
                        self.assertIsNone(recognize_command(result('please '+phrase), language, phase, 2))
                        self.assertIsNone(recognize_command(result(phrase, .2), language, phase, 2))
                        self.assertIsNone(recognize_command(result(phrase), language, 'wake', 2))

    def test_final_cleanup_uses_the_same_bilingual_end_vocabulary(self):
        for language in ('en','vi'):
            for phrase in STOP_PHRASES:
                self.assertEqual(terminal_stop('Keep this. '+phrase,language),('Keep this.',phrase))

    def test_all_personal_stop_banks_share_the_policy(self):
        for evidence in ({'acoustic':{'stop':True}}, {'vietnamese_acoustic':{'typing-stop':True}}):
            for language in ('en','vi'):
                for phase in ('conversation','typing-recording'):
                    self.assertEqual(recognize_command(evidence,language,phase,.4).action,'stop')
        self.assertEqual(recognize_command({},'en','conversation',.4,personal=True).action,'stop')


class SharedCommandRouting(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=fixtures.Lifecycle.asyncSetUp
    asyncTearDown=fixtures.Lifecycle.asyncTearDown

    async def test_both_decoders_receive_each_utterance_in_voice_and_both_dictation_languages(self):
        listener=self.listener
        listener.browser=self.writer
        listener.wav2vec=Mock(typing_templates=False)
        listener.wav2vec.decode.return_value=result('ordinary speech')
        listener.english=Mock()
        listener.english.decode.return_value=result('ordinary speech')
        listener.engines['wav2vec2']['state']='ready'
        for phase,language in [('wake','en'),('conversation','en'),('typing-recording','en'),('typing-recording','vi')]:
            listener.phase=phase;listener.session='voice-one';listener.dictation_language=language
            listener.recording=Recording() if phase=='typing-recording' else None
            listener.wav2vec.decode.reset_mock();listener.english.decode.reset_mock()
            utterance=Utterance(b'x'*32000,.4,500,False)
            listener.submit_commands(utterance,self.writer,'7')
            await asyncio.gather(*listener.recognition_jobs)
            listener.wav2vec.decode.assert_called_once_with(utterance.pcm)
            listener.english.decode.assert_called_once_with(utterance.pcm)

    async def test_end_aliases_interrupt_voice_and_finish_either_dictation_only_once(self):
        listener=self.listener;listener.browser=self.writer
        listener.wav2vec=Mock(typing_templates=False);listener.english=Mock()
        listener.engines['wav2vec2']['state']='ready'
        for phase,language in [('conversation','en'),('typing-recording','en'),('typing-recording','vi')]:
            for phrase in STOP_PHRASES:
                with self.subTest(phase=phase,language=language,phrase=phrase):
                    listener.phase=phase;listener.session='voice-one';listener.dictation_language=language
                    listener.voice_events={'playback_state':'busy'}
                    listener.recording=Recording() if phase=='typing-recording' else None
                    if listener.recording:
                        listener.recording.feed(b'a'*32000,True)
                        listener.recording.feed(b'c'*32000,True)
                    # Both decoders can finish together; only one may act.
                    listener.wav2vec.decode.return_value=result(phrase)
                    listener.english.decode.return_value=result(phrase)
                    self.writer.write.reset_mock()
                    with patch.object(listener,'transcribe_and_type',AsyncMock()) as finish:
                        listener.submit_commands(Utterance(b'c'*32000,.4,500,False),self.writer,'7')
                        await asyncio.gather(*listener.recognition_jobs)
                        if phase=='conversation':
                            stops=[json.loads(c.args[0]) for c in self.writer.write.call_args_list
                                   if json.loads(c.args[0]).get('type')=='stop']
                            self.assertEqual(len(stops),1)
                            self.assertEqual(listener.phase,'closing')
                            finish.assert_not_called()
                        else:
                            await listener.dictation_job
                            finish.assert_awaited_once_with(b'a'*32000)

    async def test_old_stop_cannot_end_a_new_voice_session_or_survive_screen_lock(self):
        listener=self.listener;listener.browser=self.writer
        listener.phase='conversation';listener.session='old-session'
        context=listener.recognition_context()
        listener.session='new-session'
        utterance=Utterance(b'x'*32000,.4,500,False)
        await listener.recognize('wav2vec2',lambda _:result('hết'),utterance,self.writer,'7',context)
        self.assertEqual(listener.phase,'conversation')
        with patch('daemon.unlocked_session',AsyncMock(return_value=None)):
            await listener.recognize('wav2vec2',lambda _:result('hết'),utterance,self.writer,'7',listener.recognition_context())
        self.assertFalse(listener.enabled)
        self.assertFalse(any(json.loads(c.args[0]).get('type')=='stop' for c in self.writer.write.call_args_list))
