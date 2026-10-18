import itertools
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from wake_words import wake_identity, HEADS, LETTERS
from wav2vec_recognizer import wake_match

def result(text,score=.95):
    return {'text':text,'result':[{'word':w,'conf':score} for w in text.split()]}

class VariantIdentity(unittest.TestCase):
    def test_requested_abbreviations_spellings_and_pronunciations_match(self):
        for text in ['Hey GPT','HEY G B T','hey G P T','hây gi bi ti','hay gờ bê tê',
                     'hê g bê tê','hây GBT','hay gp t','hey g bt','HeyGPT',
                     'hey G.P.T.','hêy gờ pê tê','hey gee pee tee','hey gee bee tee',
                     'hey chatGPT','hây chát g b t','hay dì bị tí']:
            with self.subTest(text=text):
                self.assertEqual(wake_identity(text),'hey-gpt')
                self.assertTrue(wake_match(result(text)))

    def test_all_alias_combinations_and_joined_forms(self):
        for head,g,p,t in itertools.product(HEADS,*LETTERS):
            for text in [f'{head} {g} {p} {t}',f'{head} {g}{p}{t}',f'{head}{g}{p}{t}']:
                self.assertEqual(wake_identity(text),'hey-gpt',text)

    def test_missing_letters_extra_sentences_and_bare_names_do_not_match(self):
        for text in ['hey','gpt','gbt','g b t','hey g p','hey g t','hey p t',
                     'hôm nay trời đẹp','tôi nói hey gpt','hey gpt kết thúc',
                     'hết','kết thúc','hay ghét','hey send']:
            self.assertIsNone(wake_identity(text),text)

    def test_calibrated_score_applies_to_abbreviated_and_split_variants_equally(self):
        profile={'hay gờ bê tê':(.68,.50)}
        for text in ['hey GPT','hay G B T','hey g bt','hây gi bi ti']:
            self.assertTrue(wake_match(result(text,.75),profile))
            self.assertFalse(wake_match(result(text,.3),profile))

if __name__=='__main__':unittest.main()
