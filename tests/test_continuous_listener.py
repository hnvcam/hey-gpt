import asyncio
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, Mock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from audio_control import SpeechGate
from daemon import Listener


class ContinuousListener(unittest.IsolatedAsyncioTestCase):
    async def test_voice_phase_changes_reuse_one_capture_and_one_vad_stream(self):
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,{'XDG_RUNTIME_DIR':directory}):
            listener=Listener()
            listener.enabled=True
            listener.wav2vec=Mock()
            listener.vad=Mock(speech=False,probability=0.)
            listener.vad.feed.return_value=False
            browser=Mock();browser.is_closing.return_value=False
            listener.browser=browser
            proc=Mock(returncode=None)
            proc.wait=AsyncMock(return_value=0)
            frames=0
            async def read(_):
                nonlocal frames
                frames+=1
                if frames==2:listener.phase='opening';listener.phase_since=time.monotonic()
                if frames==3:
                    listener.phase='conversation';listener.session='session-one';listener.last_activity=time.monotonic()
                if frames==4:listener.phase='closing';listener.phase_since=time.monotonic()
                if frames==5:
                    await listener.dispatch({'cmd':'resume','session':'session-one'},browser)
                    self.assertEqual(listener.phase,'wake')
                    self.assertTrue(listener.mic)
                if frames==6:raise asyncio.IncompleteReadError(b'',3200)
                return b'\0'*3200
            proc.stdout.readexactly=read
            with patch('daemon.unlocked_session',AsyncMock(return_value='7')), \
                 patch('daemon.asyncio.create_subprocess_exec',AsyncMock(return_value=proc)) as spawn:
                await listener.listen(browser,'7')
            self.assertEqual(spawn.await_count,1)
            self.assertEqual(listener.capture_starts,1)
            listener.vad.reset.assert_called_once()
            self.assertEqual(listener.vad.feed.call_count,5)

    async def test_busy_wake_is_deferred_without_cancelling_microphone_task(self):
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,{'XDG_RUNTIME_DIR':directory}):
            listener=Listener()
            browser=Mock();listener.browser=browser
            listener.enabled=listener.mic=True;listener.phase='opening'
            listener.task=asyncio.create_task(asyncio.Event().wait())
            task=listener.task
            try:
                await listener.dispatch({'cmd':'defer'},browser)
                self.assertEqual(listener.phase,'wake')
                self.assertTrue(listener.mic and listener.enabled)
                self.assertIs(listener.task,task)
                self.assertFalse(task.cancelled())
            finally:
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):await task


class ActivityGate(unittest.TestCase):
    def test_activity_signal_overrides_loud_noise_and_keeps_soft_speech(self):
        gate=SpeechGate()
        for _ in range(20):
            self.assertFalse(gate.feed(b'\xff\x7f'*1600,voiced=False)[0])
        for _ in range(3):
            self.assertTrue(gate.feed(b'\x01\0'*1600,voiced=True)[0])
        for _ in range(8):_,utterance=gate.feed(b'\0'*3200,voiced=False)
        self.assertIsNotNone(utterance)


if __name__=='__main__':unittest.main()
