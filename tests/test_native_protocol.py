import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from native_host import clean_message
from daemon import Listener

class NativeProtocol(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.env=patch.dict(os.environ,{'XDG_RUNTIME_DIR':self.temp.name});self.env.start()
        self.listener=Listener();self.browser=Mock();self.browser.is_closing.return_value=False
    async def asyncTearDown(self):
        self.env.stop();self.temp.cleanup()
    async def forward(self,msg):
        await self.listener.dispatch(clean_message(msg),self.browser)
    async def test_registration_existing_session_and_activity_cross_the_native_filter(self):
        await self.forward({'cmd':'register','extension_version':'0.6.0'})
        self.assertEqual(self.listener.extension_version,'0.6.0')
        self.listener.enabled=True;self.listener.mic=True
        await self.forward({'cmd':'session','session':'existing-session','existing':True})
        self.assertEqual(self.listener.phase,'conversation')
        with patch('daemon.time.monotonic',return_value=100):
            await self.forward({'cmd':'activity','session':'existing-session','ui_state':'idle','voice_events':{'playback_state':'quiet'}})
        self.assertEqual(self.listener.reply_guard.state_at(100),'idle')
        with patch('daemon.time.monotonic',return_value=101):
            await self.forward({'cmd':'activity','session':'existing-session','ui_state':'busy'})
        self.assertEqual(self.listener.reply_guard.state_at(101),'busy')
    async def test_busy_composer_defers_without_disconnect_or_capture_restart(self):
        await self.forward({'cmd':'register'})
        self.listener.enabled=True;self.listener.mic=True;self.listener.phase='opening'
        await self.forward({'cmd':'defer'})
        self.assertEqual(self.listener.phase,'wake');self.assertTrue(self.listener.mic)
    async def test_diagnostics_are_bounded_and_drop_private_message_fields(self):
        msg=clean_message({'cmd':'activity','session':'existing-session','ui_state':'idle',
            'voice_events':{'event_count':4,'connected':True,'supported':True,
                            'event_types':['response.created','private text'], 'transcript':'private text'},
            'cookie':'private cookie'})
        self.assertNotIn('private',str(msg));self.assertEqual(msg['voice_events']['event_types'],['response.created'])
        self.assertEqual(clean_message({'cmd':'activity','session':'existing-session','busy':False})['ui_state'],'unknown')
        with self.assertRaises(ValueError):clean_message({'cmd':'fetch','url':'https://example.com'})
    async def test_error_reason_reaches_the_service(self):
        await self.forward({'cmd':'register'})
        await self.forward({'cmd':'disarm','reason':'voice-end-unconfirmed'})
        self.assertEqual(self.listener.snapshot()['detail'],'voice-end-unconfirmed')
