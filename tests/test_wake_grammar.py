import json
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from daemon import Listener,PHRASES

class WakeGrammar(unittest.TestCase):
 def test_vosk_receives_literal_vietnamese_not_unicode_escape_words(self):
  engine=Mock()
  recognizer=engine.KaldiRecognizer.return_value
  recognizer.FinalResult.return_value='{"text":""}'
  listener=Listener(Path('unused-model'));listener.model=object()
  listener.decode(engine,b'', 'wake')
  grammar=engine.KaldiRecognizer.call_args.args[2]
  self.assertIn('hây',grammar)
  self.assertIn('hê',grammar)
  self.assertNotIn(chr(92)+'u00',grammar)
  self.assertEqual(json.loads(grammar),[*PHRASES,'[unk]'])

if __name__=='__main__':unittest.main()
