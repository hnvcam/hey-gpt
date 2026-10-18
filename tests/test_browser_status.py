import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from daemon import Listener

class BrowserStatus(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.env=patch.dict(os.environ,{'XDG_RUNTIME_DIR':self.temp.name});self.env.start()
        self.listener=Listener()
        self.browser=Mock();self.browser.is_closing.return_value=False
        self.listener.browser=self.browser
    async def asyncTearDown(self):
        self.env.stop();self.temp.cleanup()
    async def test_popup_register_preserves_the_real_failure_reason(self):
        await self.listener.dispatch({'cmd':'disarm','reason':'voice-end-unconfirmed'},self.browser)
        await self.listener.dispatch({'cmd':'report','state':'NEEDS_ACTION','detail':'voice-end-unconfirmed'},self.browser)
        await self.listener.dispatch({'cmd':'register'},self.browser)
        status=self.listener.snapshot()
        self.assertEqual(status['detail'],'voice-end-unconfirmed')
        self.assertEqual(status['browser_detail'],'voice-end-unconfirmed')
        self.assertEqual(status['last_error']['code'],'voice-end-unconfirmed')
    async def test_existing_voice_can_attach_only_from_registered_browser_after_enable(self):
        msg={'cmd':'session','session':'existing-session','existing':True}
        await self.listener.dispatch(msg,self.browser)
        self.assertEqual(self.listener.phase,'wake')
        self.listener.enabled=True
        await self.listener.dispatch(msg,Mock())
        self.assertEqual(self.listener.phase,'wake')
        await self.listener.dispatch(msg,self.browser)
        self.assertEqual(self.listener.phase,'conversation')
        self.assertEqual(self.listener.browser_state,'VOICE')
    async def test_plain_session_cannot_fabricate_a_voice_while_waiting(self):
        self.listener.enabled=True
        await self.listener.dispatch({'cmd':'session','session':'existing-session'},self.browser)
        self.assertEqual(self.listener.phase,'wake')
    async def test_arbitrary_content_cannot_be_saved_as_error_diagnostics(self):
        await self.listener.dispatch({'cmd':'report','state':'NEEDS_ACTION','detail':'private chat content'},self.browser)
        self.assertIsNone(self.listener.last_error)
        self.assertEqual(self.listener.browser_detail,'')

if __name__=='__main__':unittest.main()
