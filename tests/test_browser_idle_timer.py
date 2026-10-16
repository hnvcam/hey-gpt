import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from daemon import Listener


class BrowserIdleTimer(unittest.IsolatedAsyncioTestCase):
    async def test_no_busy_flag_is_not_treated_as_explicit_idle(self):
        listener=Listener(Path('missing'))
        writer=Mock();listener.browser=writer
        listener.phase='conversation';listener.session='session-one'
        listener.last_activity=0
        await listener.dispatch({'cmd':'activity','session':'session-one','busy':False},writer)
        listener.request_voice_stop=Mock()
        listener.check_inactivity(writer,99999)
        listener.request_voice_stop.assert_not_called()

    async def test_processing_then_idle_counts_full_interval_in_daemon(self):
        listener=Listener(Path('missing'))
        listener.phase='conversation';listener.last_activity=0
        listener.request_voice_stop=Mock()
        for t in range(60):
            listener.reply_guard.update('busy',t)
            listener.check_inactivity(None,t)
        listener.request_voice_stop.assert_not_called()
        for t in range(60,75):
            listener.reply_guard.update('idle',t)
            listener.check_inactivity(None,t)
        listener.request_voice_stop.assert_not_called()
        listener.reply_guard.update('idle',75)
        listener.check_inactivity(None,75)
        listener.request_voice_stop.assert_called_once_with(None,'silence-timeout')
