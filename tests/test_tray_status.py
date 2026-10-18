"""Panel presentation simulation; no desktop session needed."""
import unittest
from pathlib import Path
from tray_status import display, panel_label, recognizer_text


class TrayStatus(unittest.TestCase):
    def test_active_english_detector_is_described_separately_from_gpu_models(self):
        status={'recognizers':{'wav2vec2':{'state':'ready'}},
                'dictation':{'state':'unloaded','commands':'ready'},
                'voice_activity':{'state':'ready'}}
        text=recognizer_text(status)
        self.assertIn('Vosk tiếng Anh (CPU): sẵn sàng',text)
        self.assertIn('Parakeet (GPU): chưa nạp',text)
        self.assertNotIn('Vosk đã tắt',text)

    def test_unloaded_status_is_visible(self):
        status={'detail':'models-unloaded','enabled':False,'local_mic_open':False,
                'browser_state':'NEEDS_ACTION'}
        self.assertEqual(panel_label(status),'GPT · Đã gỡ')
        self.assertEqual(display(status)[0],'off')
        self.assertIn('GPU',display(status)[1])

    def test_readable_labels_for_listener_and_speech(self):
        status={'enabled':True,'local_mic_open':True}
        self.assertEqual(panel_label(status),'GPT · Đang nghe')
        status['voice_activity']={'speech':True}
        self.assertEqual(panel_label(status),'GPT · Có giọng nói')
        for phase,label in [('typing-loading','Đang nạp'),('typing-recording','Đang nhập'),
                            ('typing-transcribing','Đang xử lý'),('typing-inserting','Đang gõ')]:
            status['dictation']={'phase':phase}
            self.assertEqual(panel_label(status),'GPT · '+label)

    def test_offline_off_voice_and_error_are_distinct(self):
        self.assertEqual(panel_label(None),'GPT · Mất kết nối')
        self.assertEqual(panel_label({'enabled':False}),'GPT · Đã tắt')
        self.assertEqual(panel_label({'enabled':True,'browser_state':'VOICE'}),'GPT · Trò chuyện')
        self.assertEqual(panel_label({'browser_state':'NEEDS_ACTION'}),'GPT · Cần kiểm tra')
        status={'dictation':{'error':'failure'},'local_mic_open':True}
        self.assertEqual(panel_label(status),'GPT · Lỗi')
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
