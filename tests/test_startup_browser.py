"""Simulated lifecycle/desktop-launch tests; no microphone or browser is opened."""
import asyncio
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, Mock, patch

import daemon
from native_host import clean_message


class IndependentWakeListener(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {'XDG_RUNTIME_DIR': self.temp.name})
        self.env.start()
        self.listener = daemon.Listener(Path('unused'), engine_mode='wav2vec2')
        self.browser = Mock()
        self.browser.is_closing.return_value = False

    async def asyncTearDown(self):
        await self.listener.disarm()
        self.env.stop()
        self.temp.cleanup()

    async def test_local_arm_needs_only_an_unlocked_session_not_a_browser(self):
        async def capture(*args):
            self.listener.mic = True
            await asyncio.Event().wait()
        with patch.object(daemon, 'unlocked_session', AsyncMock(return_value='7')), \
             patch.object(self.listener, 'listen', side_effect=capture):
            await self.listener.arm()
            await asyncio.sleep(0)
            task = self.listener.task
            self.assertTrue(self.listener.enabled and self.listener.mic)
            self.assertIsNone(self.listener.browser)
            await self.listener.arm(self.browser)
            self.assertIs(task, self.listener.task)

    async def test_browser_disconnect_keeps_capture_and_cancels_old_session(self):
        self.listener.enabled = self.listener.mic = True
        self.listener.browser = self.browser
        self.listener.phase = 'conversation'
        self.listener.session = 'old-session'
        task = self.listener.task = asyncio.create_task(asyncio.Event().wait())
        self.listener.browser_disconnected()
        self.assertTrue(self.listener.enabled and self.listener.mic)
        self.assertIs(self.listener.task, task)
        self.assertFalse(task.cancelled())
        self.assertEqual(self.listener.phase, 'wake')
        self.assertIsNone(self.listener.session)

    async def test_cold_wake_launches_once_and_delivers_when_extension_registers(self):
        self.listener.enabled = self.listener.mic = True
        with patch.object(self.listener, 'launch_browser', AsyncMock()) as launch:
            await self.listener.begin_wake()
            await self.listener.launch_task
            launch.assert_awaited_once()
        wake_id = self.listener.wake_id
        await self.listener.dispatch({'cmd': 'register'}, self.browser)
        events = [json.loads(call.args[0]) for call in self.browser.write.call_args_list]
        wakes = [e for e in events if e.get('type') == 'wake']
        self.assertEqual(len(wakes), 1)
        self.assertEqual(wakes[0]['id'], wake_id)
        self.assertGreater(wakes[0]['expires'], time.time())
        self.assertTrue(self.listener.mic)

    async def test_disabled_pending_wake_is_never_delivered_on_late_connect(self):
        self.listener.enabled = self.listener.mic = True
        with patch.object(self.listener, 'launch_browser', AsyncMock()):
            await self.listener.begin_wake()
            await self.listener.disarm()
        await self.listener.dispatch({'cmd': 'register'}, self.browser)
        events = [json.loads(c.args[0]) for c in self.browser.write.call_args_list]
        self.assertFalse(any(e.get('type') == 'wake' for e in events))

    async def test_browser_launch_stays_outside_audio_service_sandbox(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(daemon, 'BASE', Path(folder)), \
             patch.object(daemon.shutil, 'which', return_value='/usr/bin/google-chrome'), \
             patch.object(daemon, 'command', AsyncMock()) as run:
            (Path(folder) / 'browser.local.json').write_text('{"profile":"Profile 2"}')
            await self.listener.launch_browser()
            args = run.await_args.args
            self.assertEqual(args[:2], ('systemd-run', '--user'))
            self.assertIn('--profile-directory=Profile 2', args)
            self.assertEqual(args[-1], 'https://chatgpt.com/')
            self.assertNotIn('--no-sandbox', args)

    async def test_failed_launch_returns_to_local_listening_without_retry(self):
        self.listener.enabled = self.listener.mic = True
        self.listener.phase = 'opening'
        with patch.object(daemon.shutil, 'which', return_value=None):
            await self.listener.launch_browser()
        self.assertEqual(self.listener.phase, 'wake')
        self.assertTrue(self.listener.enabled and self.listener.mic)
        self.assertEqual(self.listener.last_error['code'], 'browser-start-failed')

    async def test_stale_wake_cannot_claim_new_voice_session(self):
        self.listener.enabled = True
        self.listener.browser = self.browser
        self.listener.phase = 'opening'
        self.listener.wake_id = 'a' * 32
        await self.listener.dispatch(clean_message({'cmd': 'session', 'session': 'session-one',
                                                   'wake_id': 'b' * 32}), self.browser)
        self.assertEqual(self.listener.phase, 'opening')
        await self.listener.dispatch(clean_message({'cmd': 'session', 'session': 'session-one',
                                                   'wake_id': 'a' * 32}), self.browser)
        self.assertEqual(self.listener.phase, 'conversation')

    async def test_chime_requires_current_registered_ready_session_and_plays_once(self):
        self.listener.enabled = self.listener.mic = True
        self.listener.browser = self.browser
        self.listener.phase = 'conversation'
        self.listener.session = 'session-one'
        self.listener.wake_id = 'a' * 32
        with patch.object(self.listener, 'play_ready_chime', AsyncMock()) as play, \
             patch.object(daemon, 'unlocked_session', AsyncMock(return_value='7')):
            for writer, token in [(Mock(), 'session-one'), (self.browser, 'stale-session')]:
                await self.listener.dispatch({'cmd': 'voice-ready', 'session': token}, writer)
            play.assert_not_called()
            message = clean_message({'cmd': 'voice-ready', 'session': 'session-one'})
            await self.listener.dispatch(message, self.browser)
            await self.listener.chime_task
            await self.listener.dispatch(message, self.browser)
            play.assert_awaited_once()

    async def test_locked_or_disabled_session_never_chimes(self):
        self.listener.browser = self.browser
        self.listener.phase = 'conversation'
        self.listener.session = 'session-one'
        self.listener.wake_id = 'a' * 32
        with patch.object(self.listener, 'play_ready_chime', AsyncMock()) as play, \
             patch.object(daemon, 'unlocked_session', AsyncMock(return_value=None)):
            await self.listener.dispatch({'cmd': 'voice-ready', 'session': 'session-one'}, self.browser)
            self.listener.enabled = True
            await self.listener.dispatch({'cmd': 'voice-ready', 'session': 'session-one'}, self.browser)
            play.assert_not_called()
            self.assertFalse(self.listener.enabled)

    async def test_pending_wake_timeout_preserves_listener_but_discards_request(self):
        self.listener.enabled = self.listener.mic = True
        self.listener.wake_id = 'a' * 32
        self.listener.return_to_wake('browser-transition-timeout')
        self.assertTrue(self.listener.enabled and self.listener.mic)
        self.assertIsNone(self.listener.wake_id)
        await self.listener.dispatch({'cmd': 'register'}, self.browser)
        events = [json.loads(c.args[0]) for c in self.browser.write.call_args_list]
        self.assertFalse(any(e.get('type') == 'wake' for e in events))


if __name__ == '__main__':
    unittest.main()
