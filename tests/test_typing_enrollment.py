"""Personal enrollment isolation, replay labels and runtime selection. No microphone."""
import asyncio
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import keyword_dataset as studio
import enroll_typing as enroll
from acoustic_keywords import TemplateBank,file_hash
from audio_control import Utterance
from daemon import Listener
from dictation import ENGLISH_STOPS

class Enrollment(unittest.TestCase):
    def test_five_of_every_command_with_separate_reference_and_test(self):
        plan=studio.typing_plan()
        self.assertEqual(len(plan),33)
        for phrase in ('typing this','type this','stop typing','end typing','typing end'):
            rows=[r for r in plan if r['text']==phrase]
            self.assertEqual(len(rows),5)
            self.assertEqual(sum(r['split']=='dev' for r in rows),3)
            self.assertEqual(sum(r['split']=='test' for r in rows),2)
        self.assertTrue(any(r['kind']=='negative' and r['split']=='test' for r in plan))
        self.assertEqual(len(studio.reading_plan()),20)
    def test_test_audio_never_becomes_a_reference(self):
        plan={'01':dict(id='01',kind='typing',text='typing this',split='dev'),
              '02':dict(id='02',kind='typing-stop',text='end typing',split='dev'),
              '03':dict(id='03',kind='negative',text='other sentence',split='dev'),
              '04':dict(id='04',kind='typing',text='typing this',split='test')}
        pcm=np.tile(np.array([500,-500],dtype='<i2'),8000).tobytes()
        utt=Utterance(pcm,1.5,500,False)
        segments={id:[utt] for id in plan}
        clips={id:({'file':id+'.wav'},pcm) for id in plan}
        wav=Mock(np=np);wav.acoustic_features.return_value=np.zeros((10,768),dtype='float32')
        arrays,refs=enroll.build_references(plan,clips,segments,wav)
        self.assertEqual({r['prompt'] for r in refs},{'01','02','03'})
        self.assertEqual(len(arrays),3)
    def test_detector_miss_is_an_agent_issue_not_a_request_to_change_voice(self):
        with self.assertRaises(enroll.SampleIssues) as caught:
            enroll.build_references({'01':dict(kind='typing',text='type this',split='dev')},{'01':({'file':'x'},b'')},{'01':[]},Mock(np=np))
        issue=caught.exception.issues[0]
        self.assertEqual(issue['prompt'],'01')
        self.assertEqual(issue['category'],'recognizer')
        self.assertFalse(issue['retry_recommended'])
    def test_clip_paths_and_hashes_checked_before_learning(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)
            manifest=dict(profile='typing',plan=[dict(id='01')],clips=[dict(source='filtered',file='../outside.wav',prompt='01')])
            with self.assertRaisesRegex(ValueError,'escapes'):
                enroll.checked_clips(path,manifest)
    def test_typing_classes_are_independent_of_existing_voice_classes(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory);(path/'config.json').write_text('{}')
            features=np.zeros((10,768),dtype='float32');features[:,0]=1
            other=np.zeros_like(features);other[:,1]=1
            np.savez_compressed(path/'templates.npz',typing=features,stop=other)
            (path/'templates.json').write_text(json.dumps(dict(schema=1,layer=6,
                model_hashes={'config.json':file_hash(path/'config.json')},features_sha256=file_hash(path/'templates.npz'),
                templates=[dict(key='typing',kind='typing',label='type this'),dict(key='stop',kind='typing-stop',label='end typing')])))
            bank=TemplateBank(path,path,np)
            self.assertTrue(bank.match(features,'typing',1))
            self.assertFalse(bank.match(features,'typing-stop',1))
            self.assertFalse(bank.match(features,'wake',1))
    def test_studio_opens_no_microphone_in_constructor(self):
        with tempfile.TemporaryDirectory() as directory,patch.object(studio,'capture') as capture:
            recorder=studio.Studio(Path(directory),{'filtered':'test'},profile='typing')
            self.assertEqual(recorder.state['phase'],'idle')
            self.assertIsNone(recorder.session);capture.assert_not_called()

class PersonalRuntime(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory();self.env=patch.dict(os.environ,{'XDG_RUNTIME_DIR':self.temp.name});self.env.start()
        self.listener=Listener();self.listener.enabled=self.listener.mic=True
        self.listener.wav2vec=Mock(typing_templates=True);self.listener.wav2vec.match_typing.return_value=True
        self.listener.english=Mock()
        self.listener.parakeet=Mock(state='unloaded',error=None)
        self.listener.parakeet.snapshot.return_value={'state':'unloaded','error':None}
        self.unlock=patch('daemon.unlocked_session',AsyncMock(return_value='7'));self.unlock.start()
    async def asyncTearDown(self):
        await self.listener.disarm();self.unlock.stop();self.env.stop();self.temp.cleanup()
    async def test_personal_trigger_works_with_parakeet_unloaded(self):
        self.listener.english.decode.return_value={'text':'typing this','result':[{'conf':.99},{'conf':.99}]}
        with patch.object(self.listener,'begin_dictation') as begin:
            await self.listener.recognize_english(Utterance(b'x'*32000,1.5,500,False),'7',self.listener.recognition_context(),None)
            begin.assert_called_once()
        self.listener.english.decode.assert_called_once();self.listener.parakeet.transcribe.assert_not_called()
        self.assertEqual(self.listener.english_stats['personal_matches'],1)
    async def test_personal_similarity_without_spoken_command_cannot_start(self):
        self.listener.english.decode.return_value={'text':'something else','result':[{'conf':.99},{'conf':.99}]}
        with patch.object(self.listener,'begin_dictation') as begin:
            await self.listener.recognize_english(Utterance(b'x'*32000,1.5,500,False),'7',self.listener.recognition_context(),None)
            begin.assert_not_called()
    async def test_all_requested_stop_aliases_are_supported(self):
        self.assertEqual(ENGLISH_STOPS,{'stop typing','end typing','typing end'})
    async def test_personal_stop_still_needs_a_pause(self):
        self.listener.phase='typing-recording'
        await self.listener.recognize_english(Utterance(b'x'*32000,.2,500,False),'7',self.listener.recognition_context(),32000)
        self.listener.wav2vec.match_typing.assert_not_called()
        self.assertEqual(self.listener.phase,'typing-recording')


class RecordingFeedback(unittest.TestCase):
    def test_exact_phrase_and_take_are_reported(self):
        plan={row['id']:row for row in studio.typing_plan()}
        self.assertEqual(enroll.sample_details(plan,'20'),dict(prompt='20',phrase='end typing',take=4))
    def test_quiet_voice_is_not_rejected_as_a_bad_recording(self):
        plan={'20':dict(kind='typing-stop',text='end typing')}
        quiet=np.tile(np.array([80,-80],dtype='<i2'),8000).tobytes()
        self.assertEqual(enroll.quality_issues(plan,{'20':({},quiet)},np),[])
    def test_empty_audio_identifies_the_specific_recording_to_retry(self):
        plan={'20':dict(kind='typing-stop',text='end typing')}
        issues=enroll.quality_issues(plan,{'20':({},b'\0'*32000)},np)
        self.assertEqual(issues[0]['prompt'],'20');self.assertTrue(issues[0]['retry_recommended'])
        self.assertEqual(issues[0]['category'],'recording')
    def test_personal_gate_recovers_audio_a_neural_vad_missed(self):
        from audio_control import PersonalSpeechGate,SpeechGate
        personal,voice=PersonalSpeechGate(),SpeechGate()
        silent=b'\0'*3200;spoken=np.tile(np.array([400,-400],dtype='<i2'),800).tobytes()
        recovered=[];voice_results=[]
        for frame in [silent]*20+[spoken]*8+[silent]*10:
            _,u=personal.feed(frame,voiced=False)
            if u:recovered.append(u)
            _,v=voice.feed(frame,voiced=False)
            if v:voice_results.append(v)
        self.assertEqual(len(recovered),1);self.assertEqual(voice_results,[])
        self.assertGreaterEqual(recovered[0].preceding_silence,1)
