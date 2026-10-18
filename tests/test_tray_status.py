"""Panel presentation simulation; no desktop session needed."""
import unittest
from pathlib import Path
from tray_status import display, panel_label


class TrayStatus(unittest.TestCase):
    def test_readable_labels_for_listener_and_speech(self):
        status={'enabled':True,'local_mic_open':True}
        self.assertEqual(panel_label(status),'GPT · Listening')
        status['voice_activity']={'speech':True}
        self.assertEqual(panel_label(status),'GPT · Hearing')
        for phase,label in [('typing-loading','Loading'),('typing-recording','Dictating'),
                            ('typing-transcribing','Finishing'),('typing-inserting','Typing')]:
            status['dictation']={'phase':phase}
            self.assertEqual(panel_label(status),'GPT · '+label)

    def test_offline_off_voice_and_error_are_distinct(self):
        self.assertEqual(panel_label(None),'GPT · Offline')
        self.assertEqual(panel_label({'enabled':False}),'GPT · Off')
        self.assertEqual(panel_label({'enabled':True,'browser_state':'VOICE'}),'GPT · Voice')
        self.assertEqual(panel_label({'browser_state':'NEEDS_ACTION'}),'GPT · Attention')
        status={'dictation':{'error':'failure'},'local_mic_open':True}
        self.assertEqual(panel_label(status),'GPT · Error')
        self.assertEqual(display(status)[0],'error')

    def test_raster_icons_are_available_to_desktop(self):
        root=Path(__file__).resolve().parents[1]
        for name in ('off','listening','hearing','dictating','typing','voice','waiting','error'):
            self.assertEqual((root/'icons'/f'{name}.png').read_bytes()[:8],b'\x89PNG\r\n\x1a\n')

    def test_accessible_shapes_distinguish_listening_speech_and_dictation(self):
        status={'enabled':True,'local_mic_open':True}
        self.assertEqual(display(status)[0],'listening')
        status['voice_activity']={'speech':True}
        self.assertEqual(display(status)[0],'hearing')
        status['dictation']={'phase':'typing-recording'}
        self.assertEqual(display(status)[0],'dictating')
        status['dictation']['phase']='typing-inserting'
        self.assertEqual(display(status)[0],'typing')
