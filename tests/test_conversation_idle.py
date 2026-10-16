import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from conversation_idle import ConversationIdle


class ConversationIdleTests(unittest.TestCase):
    def test_processing_longer_than_fifteen_seconds_never_expires(self):
        gate=ConversationIdle()
        for second in range(100):
            gate.update('busy',second)
            self.assertFalse(gate.expired(second,0,15))

    def test_full_fifteen_seconds_start_after_busy_to_idle(self):
        gate=ConversationIdle();gate.update('busy',100)
        for second in range(101,116):
            gate.update('idle',second)
            self.assertFalse(gate.expired(second,0,15))
        gate.update('idle',116)
        self.assertTrue(gate.expired(116,0,15))

    def test_unknown_busy_or_missing_heartbeat_cancels_previous_count(self):
        for state in ('busy','unknown'):
            gate=ConversationIdle()
            for second in range(15):gate.update('idle',second)
            gate.update(state,15)
            self.assertIsNone(gate.remaining(16,0,15))
            gate.update('idle',16)
            self.assertEqual(gate.remaining(16,0,15),15)
        gate=ConversationIdle();gate.update('idle',0)
        self.assertFalse(gate.expired(30,0,15))
        gate.update('idle',30)
        self.assertEqual(gate.remaining(30,0,15),15)

    def test_new_local_speech_restarts_the_idle_count(self):
        gate=ConversationIdle()
        for second in range(31):gate.update('idle',second)
        self.assertEqual(gate.remaining(30,28,15),13)
