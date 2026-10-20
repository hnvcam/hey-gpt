#!/usr/bin/env python3
"""Build separate English/Vietnamese command banks; validate before installation."""
import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import sys
import wave

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from acoustic_keywords import TemplateBank,LAYER,file_hash,trim_pcm
from audio_control import PersonalSpeechGate
from wav2vec_recognizer import Wav2VecVietnamese
from voice_activity import VoiceActivity
from keyword_dataset import read_wav,private_json

KINDS=('typing','typing-stop')


class SampleIssues(ValueError):
    def __init__(self, issues):
        self.issues=issues
        super().__init__('Items need attention: '+', '.join(i['prompt'] for i in issues))


def sample_details(plan, id):
    row=plan[id]
    takes=[key for key,r in plan.items() if r.get('text')==row.get('text') and r['kind']==row['kind']]
    return dict(prompt=id,phrase=row.get('text') or '[silence]',take=takes.index(id)+1)


def quality_issues(plan, clips, np):
    issues=[]
    for id,(_,pcm) in clips.items():
        if plan[id]['kind']=='noise':continue
        samples=np.frombuffer(pcm,dtype='<i2').astype('int32')
        reason=None
        if not len(samples) or np.max(np.abs(samples))<=2:reason='No sound was captured in this recording.'
        elif float(np.mean(np.abs(samples)>=32760))>.02:reason='The recording is heavily clipped (distorted audio).'
        if reason:issues.append(dict(**sample_details(plan,id),category='recording',reason=reason,retry_recommended=True))
    return issues


def checked_clips(session,manifest):
    if manifest.get('profile') not in {'typing','typing-vi'}:raise ValueError('Select a typing-command recording session.')
    plan={row['id']:row for row in manifest['plan']}
    clips={}
    for clip in manifest['clips']:
        if clip['source']!='filtered':continue
        path=(session/clip['file']).resolve()
        if path.parent!=session:raise ValueError('Clip path escapes session.')
        if clip['prompt'] not in plan:raise ValueError('Unknown recording prompt.')
        try:pcm=read_wav(path)
        except (OSError,ValueError,EOFError,wave.Error) as exc:
            raise SampleIssues([dict(**sample_details(plan,clip['prompt']),category='recording',reason='The audio file could not be read.',retry_recommended=True)]) from exc
        if hashlib.sha256(pcm).hexdigest()!=clip['sha256']:
            raise SampleIssues([dict(**sample_details(plan,clip['prompt']),category='recording',reason='The audio file changed after recording.',retry_recommended=True)])
        clips[clip['prompt']]=(clip,pcm)
    missing=sorted(set(plan)-set(clips))
    if missing:raise ValueError('Record these items first: '+', '.join(missing))
    return plan,clips


def segment(pcm,vad):
    gate=PersonalSpeechGate();vad.reset();out=[]
    for offset in range(0,len(pcm),3200):
        block=pcm[offset:offset+3200]
        _,utterance=gate.feed(block,voiced=vad.feed(block))
        if utterance is not None and not utterance.too_long:out.append(utterance)
    return out


def build_references(plan,clips,segments,wav):
    arrays={};refs=[];bad=[]
    for id,row in plan.items():
        if row['split']!='dev' or row['kind']=='noise':continue
        utterances=segments[id]
        if row['kind'] in KINDS and len(utterances)!=1:
            bad.append(id);continue
        count=0
        for utterance in utterances:
            pcm=trim_pcm(utterance.pcm,wav.np)
            if row['kind'] in KINDS and not 8000<=len(pcm)<=80000:
                bad.append(id);continue
            if not 6400<=len(pcm)<=160000:continue
            key=f'{id}-{count}';count+=1
            arrays[key]=wav.acoustic_features(pcm)
            refs.append(dict(key=key,kind=row['kind'],label=row['text'],prompt=id,
                             source_file=clips[id][0]['file']))
        if count==0 and row['kind']=='negative':bad.append(id)
    if bad:raise SampleIssues([dict(**sample_details(plan,id),category='recognizer',reason='Your audio is saved, but the agent could not isolate this sample. The detector needs adjustment; no retake is required.',retry_recommended=False) for id in sorted(set(bad))])
    if not {*KINDS,'negative'}<={r['kind'] for r in refs}:
        raise ValueError('Reference recordings must include trigger, stop and ordinary speech.')
    return arrays,refs


def check_templates(plan,segments,wav,language='en'):
    rows=[];summary={}
    for id,row in plan.items():
        hits={kind:False for kind in KINDS}
        for utterance in segments[id]:
            for kind in KINDS:
                if kind=='typing-stop' and utterance.preceding_silence+1e-6<.8:continue
                hits[kind]|=wav.match_typing(utterance.pcm,kind,language,kind=='typing')
        expected=row['kind']
        passed=(all(hit==(expected==kind) for kind,hit in hits.items()))
        rows.append(dict(**sample_details(plan,id),split=row['split'],kind=expected,
                         passed=passed,hits=hits,status='recognized' if passed else 'recognizer-needs-adjustment',
                         reason='' if passed else ('The agent missed this recording.' if expected in KINDS else 'The agent triggered on ordinary speech or background noise.'),retry_recommended=False))
        for kind,hit in hits.items():
            counts=summary.setdefault(row['split']+'/'+kind,dict(positive=0,hit=0,negative=0,false_trigger=0))
            positive=expected==kind
            counts['positive' if positive else 'negative']+=1
            counts['hit' if positive else 'false_trigger']+=int(hit)
    return rows,summary


def train(session):
    os.umask(0o077)
    manifest=json.loads((session/'manifest.json').read_text())
    language='vi' if manifest.get('profile')=='typing-vi' else 'en'
    stem='vietnamese-typing' if language=='vi' else 'typing'
    plan,clips=checked_clips(session,manifest)
    wav=Wav2VecVietnamese(ROOT/'models/wav2vec2-base-vietnamese-250h')
    vad=VoiceActivity(ROOT/'models/silero-vad/silero_vad.jit',wav.torch,wav.np,wav.device)
    issues=quality_issues(plan,clips,wav.np)
    if issues:raise SampleIssues(issues)
    segments={id:segment(pcm,vad) for id,(_,pcm) in clips.items()}
    arrays,refs=build_references(plan,clips,segments,wav)
    parent=ROOT/'data';parent.mkdir(mode=0o700,exist_ok=True)
    stamp=datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    pending=parent/(stem+'-candidate-'+stamp);pending.mkdir(mode=0o700)
    wav.np.savez_compressed(pending/'templates.npz',**arrays)
    model=wav.model_path
    meta=dict(schema=1,layer=LAYER,templates=refs,enrollment_manifest=str(session/'manifest.json'),
              model_hashes={name:file_hash(model/name) for name in ('config.json','pytorch_model.bin','vocab.json')},
              features_sha256=file_hash(pending/'templates.npz'),
              evaluation_note='Only dev clips form references. Test clips are checked separately; retakes are not a blind evaluation.')
    private_json(pending/'templates.json',meta)
    bank=TemplateBank(pending,model,wav.np)
    if language=='vi':wav.vietnamese_templates=bank
    else:wav.typing_templates=bank
    rows,summary=check_templates(plan,segments,wav,language)
    installed=all(row['passed'] for row in rows)
    if installed:
        target=parent/(stem+'-templates')
        if target.exists():target.rename(parent/(stem+'-previous-'+stamp))
        try:pending.rename(target)
        except BaseException:
            previous=parent/(stem+'-previous-'+stamp)
            if previous.exists():previous.rename(target)
            raise
    report=dict(installed=installed,device=wav.device_name,rows=rows,summary=summary,
                references=len(refs),failed=[row['prompt'] for row in rows if not row['passed']],
                issues=[dict(prompt=row['prompt'],phrase=row['phrase'],take=row['take'],category='recognizer',reason=row['reason']+' Your recording is kept; the agent needs adjustment, not a different pronunciation.',retry_recommended=False) for row in rows if not row['passed']],
                method='Personal whole-utterance acoustic match through real Silero/SpeechGate boundaries. Dev-only references; separate test clips.')
    private_json(session/'typing-report.json',report)
    print(json.dumps({'installed':installed,'failed':report['failed']}))


def main(session):
    try:train(session)
    except SampleIssues as exc:
        private_json(session/'typing-report.json',dict(installed=False,device='RTX 4060',rows=[],summary={},
                     references=0,failed=[i['prompt'] for i in exc.issues],issues=exc.issues))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('session',type=Path)
    try:main(parser.parse_args().session.resolve())
    except Exception as exc:raise SystemExit(str(exc))
