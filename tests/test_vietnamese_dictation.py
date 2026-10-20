"""Simulated language routing, CTC window stitching, cancellation and accents."""
import asyncio
import base64
import json
from pathlib import Path
import unittest
from unittest.mock import AsyncMock,Mock,patch
from audio_control import Utterance
from dictation import Recording,terminal_stop,VIETNAMESE_STOPS,vietnamese_command_match
from vietnamese_dictation import VietnameseDictation,acoustic_windows
import test_dictation as fixtures
from test_dictation import result


class VietnameseLifecycle(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=fixtures.Lifecycle.asyncSetUp
    asyncTearDown=fixtures.Lifecycle.asyncTearDown

    async def test_vietnamese_phrases_select_vietnamese_only(self):
        listener=self.listener
        for phrase in ('nhập lệnh','gõ câu'):
            with patch.object(listener,'begin_dictation') as begin:
                await listener.recognize('wav2vec2',lambda _:result(phrase),Utterance(b'x'*32000,1,500,False),self.writer,'7',listener.recognition_context())
                begin.assert_called_once_with('vi')
        listener.parakeet.transcribe.assert_not_called()

    async def test_embedded_or_weak_phrases_cannot_start_dictation(self):
        listener=self.listener
        for text,conf in [('tôi muốn nhập lệnh hôm nay',.99),('gõ câu',.5)]:
            with patch.object(listener,'begin_dictation') as begin:
                await listener.recognize('wav2vec2',lambda _:result(text,conf),Utterance(b'x'*32000,1,500,False),self.writer,'7',listener.recognition_context())
                begin.assert_not_called()

    async def test_vietnamese_paste_preserves_accents_and_uses_no_parakeet(self):
        listener=self.listener;listener.dictation_language='vi';listener.phase='typing-transcribing'
        keyboard=listener.keyboard=Mock(returncode=None)
        keyboard.stdin.drain=AsyncMock();keyboard.stdout.readline=AsyncMock(return_value=b'{"state":"typed"}\n')
        with patch.object(listener,'ensure_keyboard',AsyncMock()):await listener.transcribe_and_type(b'x'*32000)
        self.assertEqual(json.loads(keyboard.stdin.write.call_args.args[0])['text'],'Xin chào thế giới')
        listener.parakeet.transcribe.assert_not_called()
        self.assertEqual(listener.phase,'wake')
        self.assertNotIn('Xin chào',json.dumps(listener.snapshot(),ensure_ascii=False))
        listener.keyboard=None

    async def test_spoken_stop_cuts_audio_at_submission_not_completion(self):
        listener=self.listener;listener.dictation_language='vi';listener.phase='typing-recording'
        listener.recording=Recording();listener.recording.feed(b'a'*32000,True);listener.recording.feed(b'c'*32000,True)
        def decode(_):return result('dừng nhập')
        context=listener.recognition_context()
        # More audio can arrive while the decoder runs. It must not move the cut.
        listener.recording.feed(b'd'*32000,True)
        with patch.object(listener,'transcribe_and_type',AsyncMock()) as finish:
            await listener.recognize('wav2vec2',decode,Utterance(b'c'*32000,.4,500,False),self.writer,'7',context,64000)
            await listener.dictation_job
            self.assertEqual(finish.await_args.args[0],b'a'*32000)

    async def test_het_and_ket_thuc_finish_vietnamese_only_after_a_pause(self):
        listener=self.listener
        for phrase in ('hết','kết thúc'):
            for pause in (.2,.4):
                listener.dictation_language='vi';listener.phase='typing-recording'
                listener.recording=Recording();listener.recording.feed(b'a'*32000,True);listener.recording.feed(b'c'*32000,True)
                with patch.object(listener,'transcribe_and_type',AsyncMock()) as finish:
                    await listener.recognize('wav2vec2',lambda _:result(phrase),Utterance(b'c'*32000,pause,500,False),self.writer,'7',listener.recognition_context(),64000)
                    if pause<.35:finish.assert_not_called()
                    else:
                        await listener.dictation_job
                        self.assertEqual(finish.await_args.args[0],b'a'*32000)

    async def test_personal_start_recovers_with_full_4gram_confirmation(self):
        listener=self.listener
        decoded=result('nhập lệch',.5);decoded['vietnamese_acoustic']={'typing':True}
        listener.vietnamese.transcribe.return_value='nhập lệnh'
        with patch.object(listener,'begin_dictation') as begin:
            await listener.recognize('wav2vec2',lambda _:decoded,Utterance(b'x'*32000,1,500,False),self.writer,'7',listener.recognition_context())
            begin.assert_called_once_with('vi')

    async def test_strict_personal_start_survives_misspelling_in_both_decoders(self):
        decoded=result('ngập lạn',.5)
        decoded['vietnamese_acoustic']={'typing':True,'typing_confirmed':True}
        with patch.object(self.listener,'begin_dictation') as begin:
            await self.listener.recognize('wav2vec2',lambda _:decoded,Utterance(b'x'*32000,1,500,False),self.writer,'7',self.listener.recognition_context())
            begin.assert_called_once_with('vi')
        self.listener.vietnamese.transcribe.assert_not_called()

    async def test_personal_start_cannot_override_a_longer_confirmed_sentence(self):
        listener=self.listener
        decoded=result('nhập lệch',.5);decoded['vietnamese_acoustic']={'typing':True}
        listener.vietnamese.transcribe.return_value='tôi muốn nhập lệnh sau'
        with patch.object(listener,'begin_dictation') as begin:
            await listener.recognize('wav2vec2',lambda _:decoded,Utterance(b'x'*32000,1,500,False),self.writer,'7',listener.recognition_context())
            begin.assert_not_called()

    async def test_stale_vietnamese_command_cannot_start_after_disable(self):
        listener=self.listener
        def decode(_):listener.recognition_epoch+=1;return result('nhập lệnh')
        with patch.object(listener,'begin_dictation') as begin:
            await listener.recognize('wav2vec2',decode,Utterance(b'x'*32000,1,500,False),self.writer,'7',listener.recognition_context())
            begin.assert_not_called()

    async def test_disable_cancels_vietnamese_transcription(self):
        listener=self.listener;listener.dictation_language='vi';listener.phase='typing-transcribing'
        entered=asyncio.Event()
        async def slow(_):entered.set();await asyncio.Event().wait()
        listener.vietnamese.transcribe.side_effect=slow
        listener.dictation_job=asyncio.create_task(listener.transcribe_and_type(b'x'*32000))
        await entered.wait();await listener.disarm()
        listener.vietnamese.unload.assert_awaited_once()
        self.assertFalse(listener.enabled)


class Windows(unittest.IsolatedAsyncioTestCase):
    async def test_long_audio_keeps_windows_bounded_and_stitches_every_frame_once(self):
        import numpy as np
        pcm=b'x'*32000*23
        model=VietnameseDictation(Path('.'));model.acoustic=Mock()
        def logits(audio):
            n=(len(audio)//2-400)//320+1
            return {'shape':[n,110],'data':np.zeros((n,110),dtype='<f4').tobytes()}
        model.acoustic.ctc_logits.side_effect=logits
        payload=await model.payload(pcm)
        self.assertLessEqual(max(len(c.args[0]) for c in model.acoustic.ctc_logits.call_args_list),8*32000)
        self.assertEqual(len(base64.b64decode(payload['logits'])),payload['shape'][0]*110*4)
        self.assertEqual(payload['shape'][0],(23*16000-400)//320+1)

    def test_short_tail_has_a_valid_receptive_field(self):
        self.assertGreaterEqual(len(list(acoustic_windows(b'x'*200))[0][0]),800)

    def test_terminal_vietnamese_commands_only_removed_as_complete_sentence(self):
        self.assertEqual(VIETNAMESE_STOPS,{'hết','kết thúc','dừng nhập','ngừng nhập'})
        for phrase in VIETNAMESE_STOPS:
            self.assertEqual(terminal_stop('giữ câu này. '+phrase,'vi'),('giữ câu này.',phrase))
        text='tôi nói dừng nhập trong câu'
        self.assertEqual(terminal_stop(text,'vi'),(text,None))

    def test_vietnamese_personal_samples_do_not_accept_embedded_start_commands(self):
        decoded=result('tôi muốn gõ câu này',.4);decoded['vietnamese_acoustic']={'typing':True}
        self.assertFalse(vietnamese_command_match(decoded,True))
        decoded=result('nhập lệnh',.4);decoded['vietnamese_acoustic']={'typing':True}
        self.assertTrue(vietnamese_command_match(decoded,True))
        decoded=result('không rõ',.4);decoded['vietnamese_acoustic']={'typing-stop':True}
        self.assertTrue(vietnamese_command_match(decoded,False))
