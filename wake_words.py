"""Shared English/Vietnamese wake spelling normalization."""
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
