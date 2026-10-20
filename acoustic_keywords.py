"""Local enrolled Wav2Vec2 keyword templates; no microphone or network I/O.

Compare entire isolated utterances, never a matching sub-span of a sentence.
The neural feature extraction is supplied by the CUDA recognizer. Tiny sequence
alignment matrices use NumPy; no second neural model or CPU ASR is involved.
"""
import hashlib
import json
from pathlib import Path

LAYER = 6


def trim_pcm(pcm, np):
    audio = np.frombuffer(pcm, dtype='<i2').astype('float32')
    if len(audio) < 320:
        return pcm
    levels = np.asarray([np.sqrt(np.mean(audio[n:n+320] ** 2))
                         for n in range(0, len(audio), 320)])
    threshold = max(60., float(np.percentile(levels, 95)) * .12)
    active = np.flatnonzero(levels >= threshold)
    if not len(active):
        return b''
    lo = max(0, int(active[0] * 320) - 1920)
    hi = min(len(audio), int((active[-1] + 1) * 320) + 1920)
    return pcm[lo*2:hi*2]


def whole_distance(a, b, np):
    """Full sequence DTW; duration bounds prevent stretching tiny fragments."""
    if not len(a) or not len(b) or not .45 <= len(a)/len(b) <= 2.2:
        return 2.
    costs = np.maximum(0., 1. - a @ b.T)
    previous = np.full(len(b)+1, np.inf)
    previous[0] = 0.
    for row in costs:
        current = np.full(len(b)+1, np.inf)
        for j, distance in enumerate(row, 1):
            current[j] = min(previous[j]+distance, current[j-1]+distance,
                             previous[j-1]+2*distance)
        previous = current
    return float(previous[-1] / (len(a)+len(b)))


def file_hash(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for block in iter(lambda: handle.read(1024*1024), b''):
            digest.update(block)
    return digest.hexdigest()


class TemplateBank:
    def __init__(self, path, model_path, np):
        path = Path(path)
        meta = json.loads((path / 'templates.json').read_text())
        if meta.get('schema') != 1 or meta.get('layer') != LAYER:
            raise ValueError('unsupported-acoustic-template-schema')
        for name, expected in meta['model_hashes'].items():
            if name not in {'config.json', 'pytorch_model.bin', 'model.safetensors', 'vocab.json'}:
                raise ValueError('invalid-template-model-file')
            if file_hash(Path(model_path)/name) != expected:
                raise ValueError('acoustic-template-model-mismatch')
        if file_hash(path / 'templates.npz') != meta['features_sha256']:
            raise ValueError('acoustic-template-corrupted')
        self.np = np
        self.rows = []
        with np.load(path / 'templates.npz', allow_pickle=False) as arrays:
            for row in meta['templates']:
                data = arrays[row['key']]
                if (data.ndim != 2 or data.shape[1] != 768 or not 2 <= len(data) <= 400
                        or not np.isfinite(data).all()):
                    raise ValueError('invalid-acoustic-feature-shape')
                self.rows.append((row['kind'], row['label'], data.copy()))
        self.thresholds = {'wake': .45, 'stop': .30, 'typing': .45, 'typing-stop': .30}
        self.minimum_margin = .08

    def match(self, features, kind, seconds, competing=(), strict=False):
        if kind not in self.thresholds or not .25 <= seconds <= 2.5:
            return False
        distances = [(whole_distance(features, data, self.np), row_kind)
                     for row_kind, _, data in self.rows]
        # Dictation starts may use personal audio without a generic transcript.
        # Require a closer match and compare against the other language and
        # Voice banks as negatives, including their wake and stop commands.
        for bank in competing:
            distances.extend((whole_distance(features, data, self.np), None)
                             for _, _, data in bank.rows)
        own = min((d for d,k in distances if k == kind), default=2.)
        other = min((d for d,k in distances if k != kind), default=2.)
        maximum,margin=(.25,.10) if strict else (self.thresholds[kind],self.minimum_margin)
        return own <= maximum and other-own >= margin


def acoustic_accept(result, kind, preceding_silence):
    # Ignore transcript spellings/scores here. This evidence is already validated
    # by the model-specific enrolled bank; the conversation boundary still wins.
    return (result.get('acoustic', {}).get(kind) is True
            and (kind == 'wake' or preceding_silence+1e-6 >= 1.0))
