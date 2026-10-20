"""One local command vocabulary and decision policy for Voice and dictation."""
from dataclasses import dataclass
import re
import unicodedata

ENGLISH_TRIGGERS = frozenset({'typing this', 'type this'})
ENGLISH_STOPS = frozenset({'stop typing', 'end typing', 'typing end'})
VIETNAMESE_TRIGGERS = frozenset({'nhập lệnh', 'gõ câu'})
VIETNAMESE_STOPS = frozenset({'dừng nhập', 'ngừng nhập', 'hết', 'kết thúc'})
VOICE_STOPS = frozenset({'hết', 'kết thúc', 'dừng lại', 'done', 'kết thúc trò chuyện'})
STOP_PHRASES = ENGLISH_STOPS | VIETNAMESE_STOPS | VOICE_STOPS
STOP_PAUSE = .35
COMMAND_PHASES = frozenset({'wake', 'conversation', 'typing-recording'})


def command_text(text):
    return ' '.join(re.sub(r"[^\w\s]", ' ', unicodedata.normalize('NFC', text).casefold()).split()) if isinstance(text, str) else ''


def command_match(result, phrases, minimum=.80):
    text = command_text(result.get('text', ''))
    words = result.get('result', [])
    if text not in phrases or len(words) != len(text.split()):
        return False
    scores = [w.get('conf', 0) for w in words]
    if not scores or not all(isinstance(c, (float, int)) and 0 <= c <= 1 for c in scores):
        return False
    confirmed = result.get('grammar_confirmed') == text
    return (min(scores) >= minimum and sum(scores)/len(scores) >= .88 or
            confirmed and min(scores) >= .35 and sum(scores)/len(scores) >= .55)


def vietnamese_command_match(result, starting):
    phrases = VIETNAMESE_TRIGGERS if starting else STOP_PHRASES
    if starting and result.get('vietnamese_acoustic', {}).get('typing_confirmed') is True:
        return True
    personal = result.get('vietnamese_acoustic', {}).get('typing' if starting else 'typing-stop') is True
    if command_match(result, phrases):
        return True
    return personal and (not starting or command_text(result.get('text', '')) in phrases)


def stop_command(result, preceding_silence, minimum_pause=STOP_PAUSE, personal=False):
    """A complete end command in either language, independent of playback status."""
    if preceding_silence + 1e-6 < minimum_pause:
        return False
    return (personal or command_match(result, STOP_PHRASES) or
            result.get('acoustic', {}).get('stop') is True or
            result.get('vietnamese_acoustic', {}).get('typing-stop') is True)


@dataclass(frozen=True)
class RecognizedCommand:
    action: str
    language: str | None = None


def recognize_command(result, language, phase, preceding_silence, profile=None, personal=False):
    """Decoders supply evidence; this policy alone chooses the application action."""
    if phase not in COMMAND_PHASES:
        return None
    if phase != 'wake':
        return RecognizedCommand('stop') if stop_command(result, preceding_silence, personal=personal) else None
    if language == 'en':
        return RecognizedCommand('dictation', 'en') if personal or command_match(result, ENGLISH_TRIGGERS) else None
    if vietnamese_command_match(result, True):
        return RecognizedCommand('dictation', 'vi')
    from wav2vec_recognizer import wake_match
    if wake_match(result, profile) or result.get('acoustic', {}).get('wake') is True:
        return RecognizedCommand('wake')
    return None
