"""Vietnamese CTC recognizer. Local files only; no saved audio/transcripts."""
import math
import json
import os
import sys
import unicodedata
from wake_words import wake_identity
from pathlib import Path
from acoustic_keywords import TemplateBank, LAYER, trim_pcm


def canonical(text):
    return ' '.join(''.join(c if c.isalnum() or c.isspace() else ' '
                            for c in unicodedata.normalize('NFC', text.lower())).split())


def phonetic_key(text):
    return wake_identity(text) or canonical(text)


def load_wake_profile(path):
    """Per-user phonetic phrases only, never arbitrary substrings/stop commands."""
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return {}
    profile = {}
    if not isinstance(data, dict) or not isinstance(data.get('phrases'), list):
        return profile
    for item in data['phrases'][:20]:
        if not isinstance(item, dict):
            continue
        text = canonical(item.get('text', '')) if isinstance(item.get('text'), str) else ''
        parts = text.split()
        mean, floor = item.get('minimum_mean'), item.get('minimum_word')
        if (wake_identity(text)
            and isinstance(mean,(int,float)) and isinstance(floor,(int,float))
            and math.isfinite(mean) and math.isfinite(floor)
            and .65 <= mean <= 1 and .45 <= floor <= 1):
            profile[text] = (mean, floor)
    return profile


def wake_match(result, profile=None):
    """Complete wake phrase only; never find a keyword inside another sentence.

    CTC frame scores are model-specific, not calibrated Vosk confidence values.
    Keep a separate conservative initial cutoff until real speech is measured.
    """
    text = canonical(result.get('text', ''))
    words = result.get('result', [])
    if not words or any(not math.isfinite(w.get('conf', 0)) for w in words):
        return False
    identity = wake_identity(text)
    if not identity:
        return False
    personal = next((limits for phrase,limits in (profile or {}).items()
                     if wake_identity(phrase) == identity), None)
    scores = [w.get('conf', 0) for w in words]
    mean, floor = personal or (.85, .55)
    return bool(len(words) == len(result.get('text','').split()) and min(scores) >= floor
                and sum(scores) / len(scores) >= mean)


def ctc_words(ids, scores, tokenizer, blank_id):
    """Collapse CTC runs, retaining peak evidence per emitted character.

    Blank must reset a run so that repeated letters separated by blank survive.
    Word confidence is the mean of those character peaks, not a probability that
    the whole word is correct. This score must be calibrated on real negatives.
    """
    collapsed = []
    for token, score in zip(ids, scores):
        token, score = int(token), float(score)
        if collapsed and token == collapsed[-1][0]:
            collapsed[-1][1] = max(collapsed[-1][1], score)
        else:
            collapsed.append([token, score])
    delimiter = tokenizer.word_delimiter_token_id
    special = set(tokenizer.all_special_ids)
    result, letters, evidence = [], [], []

    def flush():
        if letters:
            word = tokenizer.decode(letters, group_tokens=False, skip_special_tokens=True).strip()
            if word:
                result.append({'word': word, 'conf': sum(evidence) / len(evidence)})
        letters.clear()
        evidence.clear()

    for token, score in collapsed:
        if token == blank_id:
            continue
        if token == delimiter:
            flush()
        elif token not in special:
            letters.append(token)
            evidence.append(score)
    flush()
    return {'text': ' '.join(w['word'] for w in result), 'result': result}


class Wav2VecVietnamese:
    def __init__(self, model_path, gpu_uuid=None):
        # Imports are intentionally lazy: Vosk still works if this optional
        # dependency/model has not been installed. Nothing downloads at runtime.
        path = Path(model_path)
        self.model_path = path
        if not (path / 'config.json').is_file():
            raise FileNotFoundError('wav2vec-model-missing')
        requested = gpu_uuid or os.environ.get('HEY_GPT_CUDA_UUID')
        if not requested:
            config = Path(__file__).resolve().parent / 'gpu.local.json'
            if config.is_file():
                requested = json.loads(config.read_text()).get('uuid')
        if not isinstance(requested, str) or not requested.startswith('GPU-'):
            raise RuntimeError('gpu-not-configured')
        # Select by immutable UUID before importing CUDA. cuda:0 below is the
        # 4060 inside this process's device mask, not physical GPU index zero.
        if 'torch' in sys.modules and os.environ.get('CUDA_VISIBLE_DEVICES') != requested:
            raise RuntimeError('cuda-already-imported-with-different-device-mask')
        os.environ['CUDA_VISIBLE_DEVICES'] = requested
        # The systemd listener has a read-only home; CUDA's optional compilation
        # cache must live in its private writable runtime directory.
        runtime = Path(os.environ.get('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}')) / 'hey-gpt'
        cache = runtime / 'cuda-cache'
        cache.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.environ['CUDA_CACHE_PATH'] = str(cache)
        os.environ['HF_HOME'] = str(runtime / 'huggingface')
        os.environ['HF_HUB_OFFLINE'] = '1'
        os.environ['TRANSFORMERS_OFFLINE'] = '1'
        os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'
        import torch
        import numpy as np
        from transformers import Wav2Vec2ForCTC, Wav2Vec2Processor
        torch.set_num_threads(2)
        if not torch.cuda.is_available():
            raise RuntimeError('cuda-unavailable')
        self.device_name = torch.cuda.get_device_name(0)
        if 'RTX 4060' not in self.device_name:
            raise RuntimeError('wrong-cuda-gpu')
        self.gpu_uuid = requested
        self.device = 'cuda:0'
        self.torch, self.np = torch, np
        self.processor = Wav2Vec2Processor.from_pretrained(str(path), local_files_only=True)
        self.model = Wav2Vec2ForCTC.from_pretrained(
            str(path), local_files_only=True, weights_only=True).eval().to(self.device)
        # Initialize CUDA/cuDNN while the UI says "loading", before accepting
        # live utterances with a five-second result deadline.
        with torch.inference_mode():
            self.model(input_values=torch.zeros((1,16000), device=self.device))
        torch.cuda.synchronize()
        template_path = Path(__file__).resolve().parent / 'data/keyword-templates'
        self.templates = TemplateBank(template_path, path, np) if template_path.exists() else None
        self.typing_templates = None
        self.reload_typing_templates()

    def reload_typing_templates(self):
        folder=Path(__file__).resolve().parent/'data/typing-templates'
        bank=TemplateBank(folder,self.model_path,self.np) if folder.exists() else None
        self.typing_templates=bank
        return len(bank.rows) if bank else 0

    def match_typing(self, pcm, kind):
        bank=self.typing_templates
        if bank is None:return False
        trimmed=trim_pcm(pcm,self.np)
        if not 8000<=len(trimmed)<=80000:return False
        features=self.acoustic_features(trimmed)
        return bool(bank.match(features,kind,len(trimmed)/32000))

    def acoustic_features(self, pcm):
        """Same CUDA model, fixed middle layer; no text conversion needed."""
        audio = self.np.frombuffer(pcm, dtype='<i2').astype('float32') / 32768.0
        data = self.processor(audio, sampling_rate=16000, return_tensors='pt')
        data = {key: value.to(self.device) for key, value in data.items()}
        with self.torch.inference_mode():
            output = self.model(**data, output_hidden_states=True)
            features = self.torch.nn.functional.normalize(output.hidden_states[LAYER][0], dim=-1)
        return features.cpu().numpy()

    def decode(self, pcm):
        if not 3200 <= len(pcm) <= 16000 * 2 * 8:
            return {'text': '', 'result': []}
        audio = self.np.frombuffer(pcm, dtype='<i2').astype('float32') / 32768.0
        data = self.processor(audio, sampling_rate=16000, return_tensors='pt')
        data = {key: value.to(self.device) for key, value in data.items()}
        with self.torch.inference_mode():
            logits = self.model(**data).logits[0]
            scores, ids = logits.softmax(dim=-1).max(dim=-1)
        result = ctc_words(ids.tolist(), scores.tolist(), self.processor.tokenizer,
                           self.model.config.pad_token_id)
        if self.templates is not None:
            trimmed = trim_pcm(pcm, self.np)
            if 8000 <= len(trimmed) <= 80000:
                features = self.acoustic_features(trimmed)
                result['acoustic'] = {kind: bool(self.templates.match(features, kind, len(trimmed)/32000))
                                      for kind in ('wake', 'stop')}
        return result
