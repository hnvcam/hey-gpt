"""Simulated language routing, CTC window stitching, cancellation and accents."""
import asyncio
import base64
import json
from pathlib import Path
import unittest
from unittest.mock import AsyncMock,Mock,patch
from audio_control import Utterance
from dictation import Recording,terminal_stop
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
        self.assertEqual(terminal_stop('giữ câu này. dừng nhập','vi'),('giữ câu này.','dừng nhập'))
        text='tôi nói dừng nhập trong câu'
        self.assertEqual(terminal_stop(text,'vi'),(text,None))
