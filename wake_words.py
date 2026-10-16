"""Shared English/Vietnamese wake spelling normalization for both recognizers."""
import itertools
import re
import unicodedata

HEADS = ('hey','hay','he','hei','hai')
LETTERS = (
    ('g','gi','chi','go','ge','di','ghi','gee','ji'),
    ('p','b','pi','bi','pe','be','pee','bee'),
    ('t','ti','te','thi','tee'),
)
NAMES = frozenset(''.join(parts) for parts in itertools.product(*LETTERS))
# Spoken vocabulary only. Vosk filters this list against its real dictionary;
# unknown abbreviations such as GPT must never have their syllables discarded.
SPOKEN_PARTS = (
    ('hây','hê','hey','hay','hei','hai'),
    ('gi','chi','g','gờ','gê','di','đi','ghi'),
    ('pi','bi','bê','p','b','pê'),
    ('ti','t','tê','thi'),
)
PHRASES = tuple(' '.join(parts) for parts in itertools.product(*SPOKEN_PARTS))


def fold(text):
    value = unicodedata.normalize('NFD', str(text).lower().replace('đ','d'))
    return ''.join(c for c in value if unicodedata.category(c) != 'Mn')


def wake_identity(text):
    """Whole phrase only; accept merged, split, accented and letter-name forms."""
    compact = ''.join(re.findall(r'[a-z0-9]+', fold(text)))
    for head in HEADS:
        if not compact.startswith(head):
            continue
        name = compact[len(head):]
        if name.startswith('chat'):
            name = name[4:]
        if name in NAMES:
            return 'hey-gpt'
    return None
