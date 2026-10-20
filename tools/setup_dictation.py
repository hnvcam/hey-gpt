#!/usr/bin/env python3
"""One-time explicit downloads; the running agent never downloads anything."""
import hashlib
import argparse
import json
import mmap
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

ROOT=Path(__file__).resolve().parents[1]
GGUF_REVISION='741158ae71e64ef5c89385862c18f777d07a97a1'
GGUF_FILE='tdt-0.6b-v2-q8_0.gguf'
GGUF_SHA256='2027e2e1a4dc60ccdd8558f93b15e7c0db4ef8895b4e82e889f3a6275d8119c6'
WAV_REVISION='69e9000591623e5a4fc2f502407860bcdc0de0b2'
LM_SHA256='5d557b72b536a3c934b5d277b0263677ea4d32a739f44f4050e51cd197a972b3'
CPP_REVISION='5c9b0fbbd8e611d88e47d7e1ebae9bca9b447e8f'
VOSK_URL='https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip'
# Official Vosk model archive (checked during installation).
VOSK_SHA256='30f26242c4eb449f948e42cb302dd7a686cb29a3423a8367f99ff41780942498'

def digest(path):
    sha=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):sha.update(chunk)
    return sha.hexdigest()


def extract_unigrams(path):
    # This pinned KenLM v5 binary includes its NUL-delimited vocabulary at EOF.
    # Preserve it for pyctcdecode's word-prefix scoring; the Python KenLM API
    # cannot enumerate vocabulary and a binary alone does not supply it there.
    with path.open('rb') as f,mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ) as data:
        start=data.rfind(b'<unk>\0')
        if start<0:raise ValueError('missing-kenlm-vocabulary')
        words=data[start:].decode('utf-8').rstrip('\0').split('\0')
    if len(words)!=21652 or not {'<unk>','<s>','</s>'}<=set(words):
        raise ValueError('unexpected-kenlm-vocabulary')
    (path.parent/'unigrams.txt').write_text('\n'.join(words)+'\n')


def download(hf, repo, filename, revision, folder, expected):
    folder.mkdir(parents=True,exist_ok=True)
    target=folder/filename
    env=dict(os.environ,HF_HUB_DISABLE_IMPLICIT_TOKEN='1',HF_HUB_DISABLE_TELEMETRY='1')
    if not target.exists():
        subprocess.run([hf,'download',repo,filename,'--revision',revision,'--local-dir',str(folder)],env=env,check=True)
    if digest(target)!=expected:raise SystemExit('Downloaded model checksum mismatch: '+filename)
    (folder/'download-manifest.json').write_text(json.dumps(dict(model=repo,revision=revision,file=filename,sha256=expected),indent=2)+'\n')
    return target


def build_runtime(source=None, jobs=4):
    folder=ROOT/'models/parakeet-cpp'
    folder.mkdir(parents=True,exist_ok=True)
    source=source or folder/'source'
    if not (source/'.git').exists():
        subprocess.run(['git','init',str(source)],check=True)
        subprocess.run(['git','-C',str(source),'remote','add','origin','https://github.com/mudler/parakeet.cpp.git'],check=True)
        subprocess.run(['git','-C',str(source),'fetch','--depth','1','origin',CPP_REVISION],check=True)
        subprocess.run(['git','-C',str(source),'checkout','--detach','FETCH_HEAD'],check=True)
    revision=subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD'],text=True).strip()
    if revision!=CPP_REVISION:raise SystemExit('Unexpected parakeet.cpp revision')
    if not (source/'third_party/ggml/CMakeLists.txt').exists():
        subprocess.run(['git','-C',str(source),'submodule','update','--init','--depth','1','third_party/ggml'],check=True)
    build=folder/'build'
    cache=build/'CMakeCache.txt'
    if cache.exists():
        homes=[line.split('=',1)[1] for line in cache.read_text().splitlines() if line.startswith('CMAKE_HOME_DIRECTORY:INTERNAL=')]
        if homes and Path(homes[0]).resolve()!=source.resolve():
            # This contains only generated, ignored build files. CMake refuses
            # a cache tied to a different checkout (including after relocation).
            shutil.rmtree(build)
    env=dict(os.environ,CCACHE_DIR=str(folder/'ccache'))
    subprocess.run(['cmake','-S',str(source),'-B',str(build),'-DPARAKEET_SHARED=ON',
                    '-DPARAKEET_GGML_CUDA=ON','-DCMAKE_CUDA_ARCHITECTURES=89',
                    '-DPARAKEET_BUILD_SERVER=OFF','-DPARAKEET_BUILD_CLI=OFF',
                    '-DPARAKEET_WITH_CED=OFF','-DPARAKEET_WITH_VOICEDETECT=OFF',
                    '-DCMAKE_BUILD_RPATH_USE_ORIGIN=ON','-DCMAKE_BUILD_TYPE=Release'],env=env,check=True)
    subprocess.run(['cmake','--build',str(build),'--parallel',str(jobs)],env=env,check=True)
    library=build/'libhey_gpt_parakeet.so'
    pending=build/'libhey_gpt_parakeet.pending.so'
    subprocess.run(['c++','-std=c++17','-shared','-fPIC',str(ROOT/'native/parakeet_backend.cpp'),
                    '-I'+str(source/'src'),'-I'+str(source/'third_party/ggml/include'),
                    '-L'+str(build),'-lparakeet','-Wl,-rpath,$ORIGIN',
                    '-o',str(pending)],check=True)
    pending.replace(library)
    (folder/'build-manifest.json').write_text(json.dumps(dict(repository='https://github.com/mudler/parakeet.cpp',revision=revision,cuda_architecture=89),indent=2)+'\n')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--source',type=Path,help='Existing checkout at the pinned parakeet.cpp revision')
    parser.add_argument('--jobs',type=int,default=4)
    args=parser.parse_args()
    hf=shutil.which('hf')
    if not hf:raise SystemExit('Install hf first; see docs/INSTALLATION.md.')
    download(hf,'mudler/parakeet-cpp-gguf',GGUF_FILE,GGUF_REVISION,ROOT/'models/parakeet-tdt-0.6b-v2-q8',GGUF_SHA256)
    lm=ROOT/'models/vietnamese-4gram'
    archive=download(hf,'nguyenvulebinh/wav2vec2-base-vietnamese-250h','vi_lm_4grams.bin.zip',WAV_REVISION,lm,LM_SHA256)
    with zipfile.ZipFile(archive) as files:
        matches=[i for i in files.infolist() if i.filename=='vi_lm_4grams.bin' and not i.is_dir()]
        if len(matches)!=1:raise SystemExit('Unexpected Vietnamese language model archive')
        if not (lm/'vi_lm_4grams.bin').exists():
            with files.open(matches[0]) as src,(lm/'vi_lm_4grams.bin').open('wb') as dst:shutil.copyfileobj(src,dst)
    extract_unigrams(lm/'vi_lm_4grams.bin')
    if not (ROOT/'models/vosk-model-small-en-us-0.15').is_dir():
        with tempfile.TemporaryDirectory() as folder:
            archive=Path(folder)/'english.zip'
            urllib.request.urlretrieve(VOSK_URL,archive)
            if hashlib.sha256(archive.read_bytes()).hexdigest()!=VOSK_SHA256:
                raise SystemExit('English command model checksum mismatch.')
            with zipfile.ZipFile(archive) as files:
                for name in files.namelist():
                    if Path(name).is_absolute() or '..' in Path(name).parts:raise SystemExit('Invalid model archive.')
                files.extractall(ROOT/'models')
    build_runtime(args.source.resolve() if args.source else None,args.jobs)
    subprocess.run(['/usr/bin/python3','-c','import evdev'],check=True)
    if not shutil.which('wl-copy'):raise SystemExit('Install wl-clipboard for Unicode dictation paste.')
    if not os.access('/dev/uinput',os.W_OK):
        raise SystemExit('Your desktop user needs /dev/uinput access; see README.md. Do not run the agent as root.')
    print('English Q8 and Vietnamese 4-gram dictation installed. Restart hey-gpt.service and hey-gpt-tray.service.')

if __name__=='__main__':main()
