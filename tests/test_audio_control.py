import sys
import unittest
from array import array
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from audio_control import SpeechGate,stop_command


def result(text):
 return {'text':text,'result':[{'word':w,'conf':.95} for w in text.split()]}


def block(level=0):
 return array('h',[level,-level]*800).tobytes()


class CommandBoundaries(unittest.TestCase):
 def test_all_requested_commands_after_pause(self):
  for phrase in ['hết','kết thúc','dừng lại','done']:
   with self.subTest(phrase=phrase):self.assertTrue(stop_command(result(phrase),1.2))
 def test_words_inside_sentence_do_not_end_voice(self):
  for phrase in ['dấu chấm hết','tôi vẫn chưa nói hết','nếu kết thúc thì sao','do not say done','đừng dừng lại','hết bao nhiêu tiền']:
   with self.subTest(phrase=phrase):self.assertFalse(stop_command(result(phrase),2))
 def test_command_without_pause_is_not_stop(self):
  for pause in [0,.3,.8]:self.assertFalse(stop_command(result('hết'),pause))
 def test_needs_final_words_and_confidence(self):
  self.assertFalse(stop_command({'text':'hết'},2))
  self.assertFalse(stop_command({'text':'hết','result':[{'word':'hết','conf':.2}]},2))
 def test_audio_gate_measures_preceding_pause_and_waits_for_tail(self):
  gate=SpeechGate()
  for _ in range(15):gate.feed(block())
  for _ in range(4):
   voiced,utterance=gate.feed(block(2000));self.assertTrue(voiced);self.assertIsNone(utterance)
  for _ in range(7):self.assertIsNone(gate.feed(block())[1])
  utterance=gate.feed(block())[1]
  self.assertIsNotNone(utterance);self.assertAlmostEqual(utterance.preceding_silence,1.5)
  self.assertFalse(utterance.too_long)
 def test_short_dictation_pause_does_not_include_previous_words_in_command(self):
  gate=SpeechGate(tail=.35,preroll_frames=2)
  for _ in range(10):gate.feed(block(2000),voiced=True)
  for _ in range(4):gate.feed(block(),voiced=False)
  for _ in range(8):gate.feed(block(3000),voiced=True)
  utterance=None
  for _ in range(4):utterance=gate.feed(block(),voiced=False)[1]
  self.assertIsNotNone(utterance)
  self.assertAlmostEqual(utterance.preceding_silence,.4)
  self.assertNotIn(block(2000),utterance.pcm)
 def test_long_sentence_is_not_reduced_to_its_final_stop_word(self):
  gate=SpeechGate()
  for _ in range(15):gate.feed(block())
  for _ in range(90):gate.feed(block(2000))
  utterance=None
  for _ in range(8):utterance=gate.feed(block())[1]
  self.assertTrue(utterance.too_long)

if __name__=='__main__':unittest.main()
