import asyncio
import json
import os
from pathlib import Path
import sys
import time
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from audio_control import Utterance
from daemon import Listener


class AcousticLifecycle(unittest.IsolatedAsyncioTestCase):
    async def test_template_only_done_stops_once_and_respects_pause(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'XDG_RUNTIME_DIR':directory}), \
             patch('daemon.unlocked_session', AsyncMock(return_value='7')):
            listener=Listener()
            self.assertEqual(set(listener.engines),{'wav2vec2'})
            listener.enabled=listener.mic=True
            listener.phase='conversation'
            listener.session='voice-one'
            listener.voice_events={'playback_state':'quiet'}
            listener.remote_audio_updated=time.monotonic()
            browser=Mock();browser.is_closing.return_value=False
            decoder=lambda _: {'text':'đan','result':[{'word':'đan','conf':.5}], 'acoustic':{'wake':False,'stop':True}}
            await listener.recognize('wav2vec2',decoder,Utterance(b'\0'*16000,.8,500,False),browser,'7',listener.recognition_context())
            browser.write.assert_not_called()
            await listener.recognize('wav2vec2',decoder,Utterance(b'\0'*16000,1.2,500,False),browser,'7',listener.recognition_context())
            events=[json.loads(c.args[0]) for c in browser.write.call_args_list]
            self.assertEqual(sum(e.get('type')=='stop' for e in events),1)
            self.assertEqual(listener.phase,'closing')
            self.assertTrue(listener.mic)


if __name__=='__main__':unittest.main()
