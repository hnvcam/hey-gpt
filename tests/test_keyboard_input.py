"""Simulated clipboard and paste chord; no real clipboard or input device."""
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
from keyboard_input import write_text


class Keyboard(unittest.TestCase):
    def setUp(self):
        self.evdev=patch.dict(sys.modules,{'evdev':SimpleNamespace(ecodes=SimpleNamespace(EV_KEY=1,KEY_LEFTCTRL=29,KEY_LEFTSHIFT=42,KEY_V=47))})
        self.evdev.start();self.addCleanup(self.evdev.stop)
        self.focus=patch('keyboard_input.active_app_id',return_value=None)
        self.active_app=self.focus.start();self.addCleanup(self.focus.stop)

    def test_unicode_pastes_once_without_character_typing_or_enter(self):
        for text in ('Hello world.','Tiếng Việt: nhập lệnh, gõ câu.'):
            device=Mock()
            with patch('keyboard_input.unlocked',return_value=True),patch('keyboard_input.subprocess.run') as copy:
                write_text(device,text,'7',sleep=lambda _:None)
            self.assertEqual(copy.call_args.kwargs['input'],text.encode())
            self.assertNotIn(text,str(copy.call_args.args))
            self.assertEqual([c.args for c in device.write.call_args_list],[(1,29,1),(1,47,1),(1,47,0),(1,29,0)])

    def test_terminal_pastes_with_shift_and_focus_is_checked_each_time(self):
        self.active_app.side_effect=['tabby','com.system76.CosmicTerm','google-chrome']
        with patch('keyboard_input.unlocked',return_value=True),patch('keyboard_input.subprocess.run') as copy:
            for terminal in (True,True,False):
                device=Mock()
                write_text(device,'Tiếng Việt','7',sleep=lambda _:None)
                expected=([(1,29,1),(1,42,1),(1,47,1),(1,47,0),(1,42,0),(1,29,0)] if terminal else
                          [(1,29,1),(1,47,1),(1,47,0),(1,29,0)])
                self.assertEqual([c.args for c in device.write.call_args_list],expected)
            self.assertEqual(copy.call_count,3)
        self.assertEqual(self.active_app.call_count,3)

    def test_failed_terminal_paste_releases_modifiers_without_retry(self):
        self.active_app.return_value='tabby'
        device=Mock()
        def write(kind,key,value):
            if key==47 and value==1:raise OSError('input-failed')
        device.write.side_effect=write
        with patch('keyboard_input.unlocked',return_value=True),patch('keyboard_input.subprocess.run') as copy:
            with self.assertRaises(OSError):write_text(device,'test','7',sleep=lambda _:None)
        self.assertEqual(copy.call_count,1)
        self.assertEqual([c.args for c in device.write.call_args_list],
                         [(1,29,1),(1,42,1),(1,47,1),(1,42,0),(1,29,0)])

    def test_locked_session_never_copies_or_pastes(self):
        device=Mock()
        with patch('keyboard_input.unlocked',return_value=False),patch('keyboard_input.subprocess.run') as copy:
            with self.assertRaises(RuntimeError):write_text(device,'private text','7')
        copy.assert_not_called();device.write.assert_not_called()

    def test_lock_after_copy_prevents_paste(self):
        device=Mock()
        with patch('keyboard_input.unlocked',side_effect=[True,False]),patch('keyboard_input.subprocess.run'):
            with self.assertRaises(RuntimeError):write_text(device,'private text','7')
        device.write.assert_not_called()

    def test_copy_failure_never_pastes_old_clipboard(self):
        device=Mock()
        with patch('keyboard_input.unlocked',return_value=True),patch('keyboard_input.subprocess.run',side_effect=OSError):
            with self.assertRaises(OSError):write_text(device,'new text','7')
        device.write.assert_not_called()
