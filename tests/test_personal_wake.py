import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from wav2vec_recognizer import wake_match, load_wake_profile
from audio_control import stop_command

PROFILE = {'hay gờ bê tê':(.68,.50), 'hay di bi ti':(.68,.50)}
def result(text, scores):
    return {'text':text,'result':[{'word':w,'conf':s} for w,s in zip(text.split(),scores)]}


class PersonalWake(unittest.TestCase):
    def test_observed_accent_variants_and_scores(self):
        recordings = [
            ('hay gờ bê tê',[.978,.712,.545,.713]),
            ('hay gờ bê tê',[.971,.734,.682,.939]),
            ('hay gờ bê tê',[.971,.660,.911,.950]),
            ('hay gờ bê tê',[.975,.708,.827,.951]),
            ('hay di bi ti',[.986,.713,.598,.834]),
            ('hay di bi ti',[.985,.712,.856,.807]),
            ('hay di bi ti',[.968,.541,.893,.834]),
        ]
        for text,scores in recordings:
            self.assertTrue(wake_match(result(text,scores),PROFILE))
        self.assertFalse(wake_match(result('hay di bi ti',[.986,.713,.598,.834])))

    def test_personalization_never_accepts_partial_sentences_or_weak_audio(self):
        for text in ['hay di bi','di bi ti','tôi nói hay di bi ti','hay gờ bê tê hôm nay','hôm nay trời đẹp']:
            self.assertFalse(wake_match(result(text,[.99]*len(text.split())),PROFILE))
        self.assertFalse(wake_match(result('hay di bi ti',[.6]*4),PROFILE))
        self.assertFalse(wake_match(result('hay di bi ti',[1,1,.3,1]),PROFILE))

    def test_profile_cannot_install_a_stop_word_or_arbitrary_low_threshold(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'profile.json'
            path.write_text(json.dumps({'phrases':[
                {'text':'hay di bi ti','minimum_mean':.72,'minimum_word':.50},
                {'text':'hết','minimum_mean':.72,'minimum_word':.50},
                {'text':'hay gờ bê tê','minimum_mean':.1,'minimum_word':.1},
            ]}))
            self.assertEqual(load_wake_profile(path),{'hay di bi ti':(.72,.50)})

    def test_stop_threshold_and_sentence_boundaries_stay_strict(self):
        self.assertFalse(stop_command(result('hết',[.72]),1.2))
        self.assertFalse(stop_command(result('dấu chấm hết',[.99]*3),1.2))
        self.assertTrue(stop_command(result('hết',[.95]),1.2))

    def test_tones_of_english_letter_names_do_not_erase_personal_phrase(self):
        self.assertTrue(wake_match(result('hây dì bì tí',[.841,.543,.628,.752]),PROFILE))
        self.assertTrue(wake_match(result('hãy đi bị tị',[.983,.780,.717,.876]),PROFILE))
        self.assertFalse(wake_match(result('tôi hãy đi bị tị',[.99]*5),PROFILE))

    def test_asr_literal_letter_and_spoken_letter_name_share_a_profile(self):
        self.assertTrue(wake_match(result('hay g bê tê',[.972,.653,.748,.955]),PROFILE))
        self.assertTrue(wake_match(result('hay g bê tê',[.984,.591,.777,.946]),PROFILE))
        self.assertFalse(wake_match(result('hay g bê',[.99]*3),PROFILE))
        self.assertFalse(wake_match(result('hôm nay trời đẹp',[.99]*4),PROFILE))


if __name__=='__main__':unittest.main()
