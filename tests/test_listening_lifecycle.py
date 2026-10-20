"""Simulated startup/model/microphone lifecycle; no real audio or Chrome."""
import asyncio
import json
import os
import tempfile
import threading
import unittest
from unittest.mock import AsyncMock, Mock, patch

from daemon import Listener
from dictation import load_settings, save_settings, settings_path


class ListeningLifecycle(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {'XDG_RUNTIME_DIR': self.folder.name,
                                           'XDG_CONFIG_HOME': self.folder.name})
        self.env.start()
        self.listener = Listener()
        self.listener.parakeet = Mock(state='unloaded', error=None)
        self.listener.parakeet.snapshot.side_effect = lambda: {'state': self.listener.parakeet.state}
        async def load():
            self.listener.parakeet.state = 'ready'
        async def unload():
            self.listener.parakeet.state = 'unloaded'
        self.listener.parakeet.load = AsyncMock(side_effect=load)
        self.listener.parakeet.unload = AsyncMock(side_effect=unload)
        self.listener.vietnamese=Mock(state='unloaded',error=None)
        self.listener.vietnamese.snapshot.side_effect=lambda:{'state':self.listener.vietnamese.state}
        async def load_vi():self.listener.vietnamese.state='ready'
        async def unload_vi():self.listener.vietnamese.state='unloaded'
        self.listener.vietnamese.load=AsyncMock(side_effect=load_vi)
        self.listener.vietnamese.unload=AsyncMock(side_effect=unload_vi)
        self.worker = Mock(device_name='simulated GPU', templates=False)
        self.worker.vad.speech = False
        self.worker.vad.probability = 0.
        self.worker.vad.feed.return_value = False
        self.proc = Mock(returncode=None)
        self.proc.wait = AsyncMock(return_value=0)
        self.capturing = asyncio.Event()
        async def read(_):
            self.capturing.set()
            await asyncio.Event().wait()
        self.proc.stdout.readexactly = read
        self.spawn = AsyncMock(return_value=self.proc)
        self.wake_factory = Mock(return_value=self.worker)
        self.english_factory = Mock(return_value=Mock())
        self.patches = [patch('daemon.unlocked_session', AsyncMock(return_value='7')),
                        patch('daemon.WakeModels', self.wake_factory),
                        patch('daemon.EnglishCommands', self.english_factory),
                        patch('daemon.asyncio.create_subprocess_exec', self.spawn)]
        for item in self.patches:
            item.start()
        self.writer = Mock()
        self.writer.is_closing.return_value = False

    async def asyncTearDown(self):
        await self.listener.disarm()
        for item in reversed(self.patches):
            item.stop()
        self.env.stop()
        self.folder.cleanup()

    def assert_unloaded(self):
        self.assertFalse(self.listener.enabled or self.listener.mic)
        self.assertIsNone(self.listener.wav2vec)
        self.assertIsNone(self.listener.vad)
        self.assertIsNone(self.listener.english)
        self.assertEqual(self.listener.parakeet.state, 'unloaded')
        self.assertEqual(self.listener.vietnamese.state, 'unloaded')

    async def wait_for_capture(self):
        await asyncio.wait_for(self.capturing.wait(), 2)

    async def test_startup_off_does_not_load_any_models_or_open_microphone(self):
        self.listener.dictation_settings = save_settings({'auto_listen': False})
        await self.listener.startup()
        await asyncio.sleep(0)
        self.assert_unloaded()
        self.wake_factory.assert_not_called()
        self.english_factory.assert_not_called()
        self.listener.parakeet.load.assert_not_called()
        self.spawn.assert_not_called()
        self.assertFalse(Listener().dictation_settings['auto_listen'])

    async def test_startup_on_loads_all_models_before_capturing_and_disable_unloads(self):
        await self.listener.startup()
        await self.wait_for_capture()
        self.wake_factory.assert_called_once()
        self.english_factory.assert_called_once()
        self.listener.parakeet.load.assert_awaited_once()
        self.assertIs(self.listener.wav2vec, self.worker)
        self.assertIsNotNone(self.listener.english)
        await self.listener.dispatch({'cmd':'disable'}, self.writer)
        self.assert_unloaded()
        self.worker.close.assert_called_once()
        self.proc.terminate.assert_called_once()

    async def test_manual_enable_with_startup_off_loads_everything(self):
        self.listener.dictation_settings = save_settings({'auto_listen': False})
        await self.listener.dispatch({'cmd':'enable'}, self.writer)
        await self.wait_for_capture()
        self.assertTrue(self.listener.enabled)
        self.assertEqual(self.listener.parakeet.state, 'ready')
        self.assertFalse(load_settings()['auto_listen'])

    async def test_changing_one_setting_starts_and_stops_and_persists(self):
        self.listener.dictation_settings = save_settings({'auto_listen': False})
        await self.listener.dispatch({'cmd':'settings','settings':{'auto_listen':True}}, self.writer)
        await self.wait_for_capture()
        self.assertTrue(load_settings()['auto_listen'])
        self.listener.browser = Mock()
        self.listener.browser.is_closing.return_value = False
        await self.listener.dispatch({'cmd':'settings','settings':{'auto_listen':False}}, self.writer)
        self.assert_unloaded()
        self.assertFalse(load_settings()['auto_listen'])
        self.assertIn(b'"action":"disable"', self.listener.browser.write.call_args.args[0])

    async def test_other_preferences_do_not_restart_a_manually_disabled_listener(self):
        await self.listener.dispatch({'cmd':'settings','settings':{
            'auto_listen':True,'show_transcript':False,'silence_seconds':10}}, self.writer)
        self.spawn.assert_not_called()
        self.wake_factory.assert_not_called()

    async def test_microphone_failure_unloads_all_models_without_retry(self):
        self.proc.stdout.readexactly = AsyncMock(side_effect=asyncio.IncompleteReadError(b'',3200))
        await self.listener.startup()
        await asyncio.wait_for(self.listener.task, 2)
        self.assert_unloaded()
        self.assertEqual(self.listener.detail, 'microphone-unavailable')
        self.spawn.assert_awaited_once()
        self.worker.close.assert_called_once()

    async def test_model_failure_cleans_up_without_opening_microphone(self):
        self.worker.load.side_effect = RuntimeError('model-missing')
        await self.listener.startup()
        await asyncio.wait_for(self.listener.task, 2)
        self.assert_unloaded()
        self.assertEqual(self.listener.detail, 'models-not-ready')
        self.spawn.assert_not_called()

    async def test_vietnamese_decoder_failure_unloads_gpu_workers_before_listening(self):
        self.listener.vietnamese.load.side_effect=RuntimeError('missing-language-model')
        await self.listener.startup()
        await asyncio.wait_for(self.listener.task,2)
        self.assert_unloaded()
        self.listener.parakeet.unload.assert_awaited_once()
        self.listener.vietnamese.unload.assert_awaited_once()
        self.spawn.assert_not_called()

    async def test_disable_during_model_loading_cannot_leave_a_late_model(self):
        entered = asyncio.Event()
        async def loading():
            entered.set()
            await asyncio.Event().wait()
        self.listener.parakeet.load.side_effect = loading
        await self.listener.startup()
        await asyncio.wait_for(entered.wait(), 2)
        await self.listener.disarm()
        await asyncio.sleep(0)
        self.assert_unloaded()
        self.spawn.assert_not_called()
        self.assertTrue(self.listener.model_task.cancelled())

    async def test_disable_waits_for_cpu_model_construction_and_discards_it(self):
        entered = threading.Event()
        finish = threading.Event()
        def build(*_):
            entered.set()
            finish.wait(2)
            return Mock()
        self.english_factory.side_effect = build
        await self.listener.startup()
        await asyncio.wait_for(asyncio.to_thread(entered.wait, 2), 3)
        stopping = asyncio.create_task(self.listener.disarm())
        try:
            await asyncio.sleep(.01)
            self.assertFalse(stopping.done())
        finally:
            finish.set()
        await asyncio.wait_for(stopping, 2)
        self.assert_unloaded()
        self.spawn.assert_not_called()

    async def test_old_preload_setting_migrates_to_one_saved_startup_setting(self):
        settings_path().parent.mkdir(parents=True)
        settings_path().write_text(json.dumps({'autoload':False,'silence_seconds':7}))
        migrated = load_settings()
        self.assertEqual(migrated, {'auto_listen':False,'silence_seconds':7,'show_transcript':True})
        save_settings(migrated)
        self.assertNotIn('autoload', json.loads(settings_path().read_text()))
        self.listener = Listener()
        await self.listener.startup()
        self.wake_factory.assert_not_called()
