"""Simulated clipboard and paste chord; no real clipboard or input device."""
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
from keyboard_input import write_text


class Keyboard(unittest.TestCase):
    def setUp(self):
        self.evdev=patch.dict(sys.modules,{'evdev':SimpleNamespace(ecodes=SimpleNamespace(EV_KEY=1,KEY_LEFTCTRL=29,KEY_V=47))})
        self.evdev.start();self.addCleanup(self.evdev.stop)

    def test_unicode_pastes_once_without_character_typing_or_enter(self):
        for text in ('Hello world.','Tiếng Việt: nhập lệnh, gõ câu.'):
            device=Mock()
            with patch('keyboard_input.unlocked',return_value=True),patch('keyboard_input.subprocess.run') as copy:
                write_text(device,text,'7',sleep=lambda _:None)
            self.assertEqual(copy.call_args.kwargs['input'],text.encode())
            self.assertNotIn(text,str(copy.call_args.args))
            self.assertEqual([c.args for c in device.write.call_args_list],[(1,29,1),(1,47,1),(1,47,0),(1,29,0)])

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
