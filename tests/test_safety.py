import asyncio
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import daemon
import native_host
from wav2vec_recognizer import wake_match


class Recognition(unittest.TestCase):
    def result(self,text,confidence=0.95):
        return {"text":text,"result":[{"word":w,"conf":confidence} for w in text.split()]}

    def test_full_vietnamese_wake(self):
        self.assertTrue(wake_match(self.result("hây gi pi ti")))

    def test_rejects_partial_low_confidence_and_normal_speech(self):
        for text,confidence in [("gi pi ti",1),("hây gi pi ti",0.7),("hôm nay trời đẹp",1),("hey gee pee",1)]:
            self.assertFalse(wake_match(self.result(text,confidence)))

    def test_native_fragmented_read(self):
        class Fragment(io.BytesIO):
            def read(self,n): return super().read(min(n,1))
        self.assertEqual(native_host.exact(Fragment(b"test"),4),b"test")
        with self.assertRaises(EOFError): native_host.exact(io.BytesIO(b"a"),2)


class Lifecycle(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.env=patch.dict(os.environ,{"XDG_RUNTIME_DIR":self.temp.name})
        self.env.start()
        self.listener=daemon.Listener()

    async def asyncTearDown(self):
        await self.listener.disarm()
        self.env.stop();self.temp.cleanup()

    async def test_startup_and_status_do_not_open_mic(self):
        self.listener.publish("DISARMED","ready")
        self.assertFalse(self.listener.snapshot()["local_mic_open"])
        self.assertEqual((daemon.runtime_dir()/"status.json").stat().st_mode & 0o777,0o600)

    async def test_locked_session_refuses_arm(self):
        with patch.object(daemon,"unlocked_session",AsyncMock(return_value=None)):
            await self.listener.arm(object())
        self.assertIsNone(self.listener.task)
        self.assertFalse(self.listener.mic)

    async def test_disarm_cancels_capture_before_publishing(self):
        stopped=asyncio.Event()
        async def fake_capture():
            try: await asyncio.Event().wait()
            finally: stopped.set()
        self.listener.task=asyncio.create_task(fake_capture())
        await asyncio.sleep(0)
        self.listener.mic=True
        await self.listener.disarm()
        self.assertTrue(stopped.is_set())
        self.assertFalse(self.listener.mic)

    async def test_session_detection_fails_closed(self):
        with patch.object(daemon,"command",AsyncMock(side_effect=OSError)):
            self.assertIsNone(await daemon.unlocked_session())

    async def test_only_registered_browser_can_arm(self):
        from unittest.mock import Mock
        writer=Mock()
        writer.is_closing.return_value=False
        with patch.object(self.listener,"arm",AsyncMock()) as arm:
            await self.listener.dispatch({"cmd":"arm"},writer)
            arm.assert_not_called()
            await self.listener.dispatch({"cmd":"register"},writer)
            await self.listener.dispatch({"cmd":"arm"},writer)
            arm.assert_awaited_once_with(writer)

    async def test_tray_enable_starts_local_listener_without_requiring_chrome(self):
        from unittest.mock import Mock
        with patch.object(self.listener, 'arm', AsyncMock()) as arm:
            await self.listener.dispatch({'cmd': 'enable'}, Mock())
            arm.assert_awaited_once_with()
        self.assertIsNone(self.listener.browser)

    async def test_disable_stops_local_and_requests_voice_end(self):
        from unittest.mock import Mock
        self.listener.browser=Mock()
        self.listener.browser.is_closing.return_value=False
        self.listener.enabled=True
        await self.listener.dispatch({"cmd":"disable"},Mock())
        self.assertFalse(self.listener.enabled)
        self.assertFalse(self.listener.mic)
        self.assertIn(b'"action":"disable"',self.listener.browser.write.call_args[0][0])

    async def test_fifteen_second_idle_sends_one_stop_keeps_local_microphone(self):
        from unittest.mock import Mock
        browser=Mock();browser.is_closing.return_value=False
        self.listener.phase='conversation';self.listener.session='session-token'
        self.listener.last_activity=100;self.listener.mic=True;self.listener.enabled=True
        for t in (100,103,106,109,112,114.9):self.listener.reply_guard.update('idle',t)
        self.listener.check_inactivity(browser,114.9)
        browser.write.assert_not_called()
        self.listener.check_inactivity(browser,115)
        self.assertEqual(self.listener.phase,'closing')
        self.assertTrue(self.listener.mic)
        self.assertTrue(self.listener.enabled)
        self.assertIn(b'"type":"stop"',browser.write.call_args[0][0])
        browser.write.reset_mock()
        self.listener.check_inactivity(browser,140)
        browser.write.assert_not_called()

    async def test_verified_resume_reuses_capture_without_manual_arm(self):
        from unittest.mock import Mock
        browser=Mock();browser.is_closing.return_value=False
        self.listener.browser=browser;self.listener.phase='closing'
        self.listener.session='session-token';self.listener.enabled=True;self.listener.mic=True
        with patch.object(self.listener,'arm',AsyncMock()) as arm:
            await self.listener.dispatch({'cmd':'resume','session':'wrong-session'},browser)
            self.assertEqual(self.listener.phase,'closing')
            await self.listener.dispatch({'cmd':'resume','session':'session-token'},browser)
            self.assertEqual(self.listener.phase,'wake')
            self.assertTrue(self.listener.mic)
            arm.assert_not_called()

    async def test_browser_busy_activity_delays_idle_end(self):
        from unittest.mock import Mock
        browser=Mock();self.listener.browser=browser
        self.listener.phase='conversation';self.listener.session='session-token'
        self.listener.last_activity=0
        await self.listener.dispatch({'cmd':'activity','session':'wrong-token','busy':True},browser)
        self.assertEqual(self.listener.last_activity,0)
        await self.listener.dispatch({'cmd':'activity','session':'session-token','busy':True},browser)
        self.assertGreater(self.listener.last_activity,0)

    async def test_shutdown_rejects_new_arm_and_registration(self):
        from unittest.mock import Mock
        writer=Mock();writer.is_closing.return_value=False
        self.listener.stopping=True
        with patch.object(self.listener,'arm',AsyncMock()) as arm:
            await self.listener.dispatch({'cmd':'register'},writer)
            await self.listener.dispatch({'cmd':'arm'},writer)
            arm.assert_not_called()
            self.assertIsNone(self.listener.browser)

if __name__ == "__main__": unittest.main()
