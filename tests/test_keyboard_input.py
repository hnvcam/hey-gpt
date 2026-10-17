"""Keystroke event simulation; does not create an input device."""
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
from keyboard_input import KEYS, SHIFTED, write_text

class Keyboard(unittest.TestCase):
    def test_every_printable_english_character_has_a_key(self):
        for value in range(32,127):
            char=chr(value);self.assertIn(SHIFTED.get(char,char.lower()),KEYS)
    def test_only_shift_and_printable_keys_are_emitted(self):
        device=Mock()
        with patch.dict(sys.modules,{'evdev':SimpleNamespace(ecodes=SimpleNamespace(EV_KEY=1,KEY_LEFTSHIFT=42))}),patch('keyboard_input.unlocked',return_value=True):
            write_text(device,'Hello!\nNext; $HOME', '7',sleep=lambda _:None)
        events=[call.args for call in device.write.call_args_list]
        for _,code,_ in events:
            self.assertIn(code,set(KEYS.values())|{42})
            self.assertNotIn(code,{28,15,29,56,97,100}) # Enter, Tab, Ctrl, Alt
        held=set()
        for _,code,value in events:
            if value:held.add(code)
            else:held.discard(code)
        self.assertFalse(held)
    def test_lock_midway_aborts_before_more_keys(self):
        device=Mock()
        with patch.dict(sys.modules,{'evdev':SimpleNamespace(ecodes=SimpleNamespace(EV_KEY=1,KEY_LEFTSHIFT=42))}),patch('keyboard_input.unlocked',side_effect=[True,True,False]):
            with self.assertRaises(RuntimeError):write_text(device,'a'*100,'7',sleep=lambda _:None)
        downs=[call for call in device.write.call_args_list if call.args[2]==1]
        self.assertEqual(len(downs),32)
