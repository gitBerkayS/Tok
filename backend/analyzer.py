"""Extract the seven raw JetonCount features from a draft."""

import re
from dataclasses import dataclass, fields
from typing import Optional


SYMBOLS = set(r"""@#$%^&*()-_=+[]{}<>/\|~`""")
PUNCTUATION = SYMBOLS | set(".,!?;:'\"")
WORDS = re.compile(r"\b\w+\b")


@dataclass(frozen=True)
class Features:
    chars: int
    words: int
    avg_chars_per_word: float
    punctuation_ratio: float
    symbol_ratio: float
    longest_word_chars: int
    vocab_size: Optional[int]

    @classmethod
    def from_draft(cls, draft: str, vocab_size: Optional[int]):
        lengths = [len(word.group()) for word in WORDS.finditer(draft)]
        chars = len(draft)
        words = len(lengths)
        return cls(
            chars,
            words,
            sum(lengths) / words if words else 0,
            sum(char in PUNCTUATION for char in draft) / chars if chars else 0,
            sum(char in SYMBOLS for char in draft) / chars if chars else 0,
            max(lengths, default=0),
            vocab_size,
        )


FEATURE_COLUMNS = tuple(field.name for field in fields(Features))
