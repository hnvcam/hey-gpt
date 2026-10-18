"""Regression coverage for false idle and speaker-echo stop commands."""
import asyncio
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, Mock, patch

from audio_control import Utterance
from daemon import Listener
from native_host import clean_message


class StopActivity(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.env=patch.dict(os.environ,{'XDG_RUNTIME_DIR':self.temp.name});self.env.start()
        self.listener=Listener()
        self.listener.enabled=self.listener.mic=True
        self.listener.phase='conversation';self.listener.session='session-one'
        self.browser=Mock();self.browser.is_closing.return_value=False
        self.listener.browser=self.browser
        self.unlock=patch('daemon.unlocked_session',AsyncMock(return_value='7'));self.unlock.start()
    async def asyncTearDown(self):
        await self.listener.disarm()
        self.unlock.stop();self.env.stop();self.temp.cleanup()
    async def activity(self,state,playback=None):
        msg={'cmd':'activity','session':'session-one','ui_state':state}
        if playback is not None:msg['voice_events']={'playback_state':playback}
        await self.listener.dispatch(clean_message(msg),self.browser)
    async def test_old_ui_idle_and_missing_audio_proof_cannot_start_countdown(self):
        await self.activity('idle')
        self.assertIsNone(self.listener.reply_guard.idle_since)
        await self.activity('idle','busy')
        self.assertEqual(self.listener.reply_guard.state,'busy')
        await self.activity('idle','quiet')
        self.assertEqual(self.listener.reply_guard.state,'idle')
    async def test_long_playback_never_requests_silence_stop_even_if_text_is_final(self):
        for second in range(100,165):
            with patch('daemon.time.monotonic',return_value=second):
                await self.activity('idle','busy')
                self.listener.check_inactivity(self.browser,second)
        events=[json.loads(c.args[0]) for c in self.browser.write.call_args_list]
        self.assertFalse(any(e.get('type')=='stop' for e in events))
    async def test_local_keyword_during_or_overlapping_remote_speech_does_not_hang_up(self):
        result={'text':'hết','result':[{'word':'hết','conf':.99}],'acoustic':{'stop':True}}
        utterance=Utterance(b'\0'*64000,1.5,500,False)
        for playback,overlap in [('busy',False),('unknown',False),('quiet',True)]:
            self.listener.voice_events={'playback_state':playback}
            self.listener.remote_audio_updated=time.monotonic()
            self.listener.last_remote_audio=time.monotonic()-1 if overlap else None
            await self.listener.recognize('wav2vec2',lambda _:result,utterance,None,'7',self.listener.recognition_context())
            self.assertEqual(self.listener.phase,'conversation')
        self.assertEqual(self.listener.stop_echo_suppressed,3)
    async def test_personal_done_command_still_works_after_verified_quiet(self):
        result={'text':'đan','result':[{'word':'đan','conf':.5}],'acoustic':{'stop':True}}
        self.listener.voice_events={'playback_state':'quiet'}
        self.listener.remote_audio_updated=time.monotonic()
        self.listener.last_remote_audio=time.monotonic()-10
        await self.listener.recognize('wav2vec2',lambda _:result,Utterance(b'\0'*32000,1.5,500,False),None,'7',self.listener.recognition_context())
        self.assertEqual(self.listener.phase,'closing')
        self.assertEqual(self.listener.last_voice_stop['reason'],'spoken-stop-command')
    async def test_page_veto_resumes_same_call_without_reopening_or_disarming(self):
        self.listener.request_voice_stop(self.browser,'silence-timeout')
        task=self.listener.task=asyncio.create_task(asyncio.Event().wait())
        await self.listener.dispatch(clean_message({'cmd':'stop-vetoed','session':'wrong-session'}),self.browser)
        self.assertEqual(self.listener.phase,'closing')
        await self.listener.dispatch(clean_message({'cmd':'stop-vetoed','session':'session-one'}),self.browser)
        self.assertEqual(self.listener.phase,'conversation')
        self.assertTrue(self.listener.enabled and self.listener.mic)
        self.assertIs(task,self.listener.task)
        self.assertIsNone(self.listener.reply_guard.idle_since)
