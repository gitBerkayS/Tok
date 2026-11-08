"""Estimate tokens from the numeric CSV rows written by the collector."""

import csv
import math
from functools import lru_cache

from .analyzer import FEATURE_COLUMNS, Features


MODEL_ID = "fromziro/JetonCount"
REVISION = "b07f42658cdbeca9934323c5d55f5d53df6cfcb9"


@lru_cache(maxsize=1)
def load_model():
    try:
        from transformers import AutoModel
    except ImportError as error:
        raise RuntimeError("Install torch, transformers, and safetensors to run JetonCount.") from error

    return AutoModel.from_pretrained(MODEL_ID, revision=REVISION, trust_remote_code=True).eval()


def model_prediction(features):
    model = load_model()
    import torch

    # The checkpoint expands and normalizes these seven raw features internally.
    values = [getattr(features, name) for name in FEATURE_COLUMNS]
    with torch.inference_mode():
        return model(input_features=torch.tensor([values], dtype=torch.float32)).logits.item()


def estimate_tokens(features, predict=model_prediction):
    if features.chars == 0:
        return {"estimated_tokens": 0, "method": "empty"}
    if features.vocab_size is None:
        raise ValueError("Set vocab_size in the CSV or supply the target tokenizer vocabulary size.")
    raw = predict(features)
    if not math.isfinite(raw) or raw <= 0:
        return {"estimated_tokens": max(1, round(features.chars / 4)), "method": "heuristic_fallback"}
    return {"estimated_tokens": max(1, round(raw)), "method": "jetoncount"}


def parse_features(row, default_vocab_size):
    vocab = row["vocab_size"].strip()
    features = Features(
        chars=int(row["chars"]),
        words=int(row["words"]),
        avg_chars_per_word=float(row["avg_chars_per_word"]),
        punctuation_ratio=float(row["punctuation_ratio"]),
        symbol_ratio=float(row["symbol_ratio"]),
        longest_word_chars=int(row["longest_word_chars"]),
        vocab_size=int(vocab) if vocab else default_vocab_size,
    )
    if (
        not 0 <= features.words <= features.chars
        or not 0 <= features.longest_word_chars <= features.chars
        or not 0 <= features.avg_chars_per_word <= features.chars
        or not 0 <= features.symbol_ratio <= features.punctuation_ratio <= 1
        or (features.vocab_size is not None and features.vocab_size <= 0)
    ):
        raise ValueError("Feature values are outside their valid ranges.")
    return features


def estimate_csv(path, default_vocab_size=None):
    """Return per-row estimates and their sum for a capture CSV."""
    rows = []
    with open(path, encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != FEATURE_COLUMNS:
            raise ValueError("Expected this CSV header: " + ",".join(FEATURE_COLUMNS))
        for row in reader:
            try:
                if None in row or any(row[name] is None for name in FEATURE_COLUMNS):
                    raise ValueError("Expected exactly seven feature values.")
                features = parse_features(row, default_vocab_size)
                result = estimate_tokens(features)
            except ValueError as error:
                raise ValueError(f"CSV line {reader.line_num}: {error}") from error
            rows.append({"line": reader.line_num, **result})
    return {"estimated_tokens": sum(row["estimated_tokens"] for row in rows), "rows": rows}
