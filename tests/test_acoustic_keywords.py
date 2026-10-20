import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
from acoustic_keywords import TemplateBank, acoustic_accept, file_hash, trim_pcm, whole_distance
from audio_control import SpeechGate


class AcousticKeywords(unittest.TestCase):
    def test_transcript_independent_start_requires_closer_match_and_cross_bank_margin(self):
        bank=TemplateBank.__new__(TemplateBank)
        bank.np=np;bank.thresholds={'typing':.45};bank.minimum_margin=.08
        feature=np.array([[1.,0.]],dtype='float32')
        bank.rows=[('typing','type this',feature),('negative','ordinary speech',-feature)]
        near=np.array([[.8,.6]],dtype='float32')
        broad=np.array([[.7,np.sqrt(.51)]],dtype='float32')
        self.assertTrue(bank.match(near,'typing',1,strict=True))
        self.assertTrue(bank.match(broad,'typing',1))
        self.assertFalse(bank.match(broad,'typing',1,strict=True))
        other_language=Mock(rows=[('typing','gõ câu',near)])
        self.assertFalse(bank.match(near,'typing',1,competing=(other_language,),strict=True))

    def test_alignment_uses_whole_utterance_and_rejects_extreme_stretch(self):
        a = np.eye(4, dtype='float32')
        self.assertAlmostEqual(whole_distance(a, a, np), 0.)
        self.assertAlmostEqual(whole_distance(a, np.repeat(a, 2, axis=0), np), 0.)
        self.assertEqual(whole_distance(a, np.repeat(a, 4, axis=0), np), 2.)
        self.assertGreater(whole_distance(a, a[::-1], np), .3)

    def test_templates_still_require_preceding_stop_pause(self):
        result = {'acoustic': {'wake': True, 'stop': True}}
        self.assertTrue(acoustic_accept(result, 'wake', 0))
        self.assertFalse(acoustic_accept(result, 'stop', .8))
        self.assertTrue(acoustic_accept(result, 'stop', 1.))
        self.assertFalse(acoustic_accept({'acoustic': {'stop': 'true'}}, 'stop', 2))

    def test_bank_rejects_competing_class_and_corrupted_features(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model = root/'model'
            model.mkdir()
            (model/'config.json').write_text('{}')
            feature = np.zeros((5,768), dtype='float32')
            feature[:,0] = 1
            opposite = np.zeros_like(feature)
            opposite[:,1] = 1
            np.savez_compressed(root/'templates.npz', wake=feature, stop=opposite)
            meta = dict(schema=1, layer=6, model_hashes={'config.json': file_hash(model/'config.json')},
                        features_sha256=file_hash(root/'templates.npz'),
                        templates=[dict(key='wake', kind='wake', label='Hey GPT'),
                                   dict(key='stop', kind='stop', label='done')])
            (root/'templates.json').write_text(json.dumps(meta))
            bank = TemplateBank(root, model, np)
            self.assertTrue(bank.match(feature, 'wake', 1))
            self.assertFalse(bank.match(feature, 'stop', 1))
            self.assertFalse(bank.match(feature, 'wake', 4))
            mixed = (feature+opposite)/np.sqrt(2)
            self.assertFalse(bank.match(mixed, 'wake', 1))
            (root/'templates.npz').write_bytes(b'broken')
            with self.assertRaisesRegex(ValueError, 'corrupted'):
                TemplateBank(root, model, np)

    def test_model_switch_cannot_reuse_incompatible_templates(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'config.json').write_text('new model')
            (root/'templates.json').write_text(json.dumps(dict(schema=1,layer=6,model_hashes={'config.json':'wrong'})))
            with self.assertRaisesRegex(ValueError,'model-mismatch'):
                TemplateBank(root, root, np)

    def test_quiet_audio_does_not_produce_features_and_soft_speech_reaches_gate(self):
        self.assertEqual(trim_pcm(b'\0'*32000, np), b'')
        gate = SpeechGate()
        silent = b'\0'*3200
        for _ in range(20):
            self.assertIsNone(gate.feed(silent)[1])
        soft = np.tile(np.array([180,-180],dtype='<i2'),800).tobytes()
        for _ in range(4):
            self.assertTrue(gate.feed(soft)[0])
        for _ in range(8):
            _,utterance = gate.feed(silent)
        self.assertIsNotNone(utterance)
        self.assertGreaterEqual(utterance.preceding_silence,1)


if __name__ == '__main__':
    unittest.main()
