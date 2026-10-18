import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from wav2vec_recognizer import wake_match as matched

def result(text,confidence):
 return {'text':text,'result':[{'word':w,'conf':c} for w,c in zip(text.split(),confidence)]}

class LivePronunciationRegression(unittest.TestCase):
 def test_vietnamese_letter_names_observed_in_live_test(self):
  self.assertTrue(matched(result('hay gờ p tê',[.96,1,.87,1])))
  self.assertTrue(matched(result('hay gờ bi tê',[.71,.87,.97,.96])))
 def test_one_uncertain_last_syllable_does_not_erase_strong_phrase(self):
  self.assertTrue(matched(result('hây gi bi ti',[1,.98,1,.64])))
 def test_incomplete_live_sample_does_not_trigger(self):
  self.assertFalse(matched(result('hay gờ gi',[.96,1,.73])))
 def test_weak_phrase_and_single_bad_syllable_still_fail(self):
  self.assertFalse(matched(result('hay gờ bi tê',[.7,.7,.7,.7])))
  self.assertFalse(matched(result('hay gờ bi tê',[1,1,1,.2])))
 def test_extra_words_and_normal_sentences_fail(self):
  self.assertFalse(matched(result('hôm nay trời đẹp',[1]*4)))
  self.assertFalse(matched(result('tôi nói hay gờ p tê',[1]*6)))

if __name__=='__main__':unittest.main()
