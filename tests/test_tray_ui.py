"""Real GTK widgets with simulated service state; run explicitly under Xvfb."""
import copy
import os
import unittest
from unittest.mock import Mock, patch

GTK_TEST = os.environ.get('HEY_GPT_TEST_GTK') == '1'
if GTK_TEST:
    import tray
    from gi.repository import Gtk, Gdk


@unittest.skipUnless(GTK_TEST, 'Run explicitly with HEY_GPT_TEST_GTK=1 under Xvfb')
class TrayUI(unittest.TestCase):
    def setUp(self):
        self.patches=[patch('tray.Indicator.Indicator.new',return_value=Mock()),
                      patch('tray.App.poll',return_value=True),
                      patch('tray.GLib.timeout_add_seconds',return_value=1),
                      patch('tray.panel_output',return_value=None)]
        for item in self.patches:item.start()
        self.app=tray.App()
        self.app.action=Mock()
        self.status={'enabled':False,'state':'DISARMED','detail':'models-unloaded',
                     'dictation':{'state':'unloaded','commands':'ready',
                                  'settings':{'auto_listen':True,'silence_seconds':5,'show_transcript':True}},
                     'recognizers':{'wav2vec2':{'state':'unloaded'}}}
        self.app.update(self.status)

    def tearDown(self):
        self.app.hide_board()
        if self.app.window:self.app.window.destroy()
        self.app.menu.destroy()
        for item in reversed(self.patches):item.stop()

    def test_menu_has_only_quick_actions(self):
        labels=[item.get_label() for item in self.app.menu.get_children() if isinstance(item,Gtk.MenuItem)]
        self.assertEqual([label for label in labels[1:] if label],
                         ['Bật trợ lý','Mở ChatGPT','Cài đặt…','Ẩn biểu tượng (không tắt trợ lý)'])
        self.app.enabled_item.set_active(True)
        self.app.action.assert_called_once_with('enable')
        self.app.action.reset_mock()
        self.app.update(self.status)
        self.app.action.assert_not_called()

    def test_one_startup_switch_replaces_independent_model_controls(self):
        self.app.show_window()
        self.assertTrue(self.app.auto_listen.get_sensitive())
        self.assertFalse(hasattr(self.app, 'load_button'))
        self.assertFalse(hasattr(self.app, 'unload_button'))
        self.app.auto_listen.set_active(False)
        self.app.action.assert_called_once_with('settings', {'settings':{
            'auto_listen':False,'silence_seconds':5,'show_transcript':True}})

    def test_transcript_setting_is_editable_and_sent_with_other_preferences(self):
        self.app.show_window()
        self.assertTrue(self.app.transcript.get_sensitive())
        self.app.transcript.set_active(False)
        self.app.action.assert_called_once_with('settings',{'settings':{
            'auto_listen':True,'silence_seconds':5,'show_transcript':False}})

    def test_transcript_visibility_follows_saved_preference(self):
        status=copy.deepcopy(self.status)
        status['dictation']['phase']='typing-recording'
        self.app.update(status)
        self.assertIsNotNone(self.app.board)
        status['dictation']['settings']['show_transcript']=False
        self.app.update(status)
        self.assertIsNone(self.app.board)

    def test_offline_settings_show_connection_state(self):
        self.app.update(None);self.app.show_window()
        self.assertFalse(self.app.enabled_item.get_sensitive())
        self.assertFalse(self.app.auto_listen.get_sensitive())
        self.assertFalse(self.app.transcript.get_sensitive())
        self.assertIn('kết nối',self.app.dictation_label.get_text())

    def test_settings_layout_preview(self):
        self.app.show_window()
        while Gtk.events_pending():Gtk.main_iteration_do(False)
        path=os.environ.get('HEY_GPT_UI_PREVIEW')
        if path:
            window=self.app.window
            pixbuf=Gdk.pixbuf_get_from_window(window.get_window(),0,0,
                                            window.get_allocated_width(),window.get_allocated_height())
            pixbuf.savev(path,'png',[],[])
