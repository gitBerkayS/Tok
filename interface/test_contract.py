"""Checks that the model plug-in still honours CONTRACT.md.

Run from the repo root or interface/:   python interface/test_contract.py
(also works with pytest). Uses only Flask, which the app already needs.
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import app as tok_app  # noqa: E402


def _is_count(value):
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value >= 0
    )


def test_get_token_count_returns_non_negative_int():
    for _ in range(20):  # the mock is random, so try several times
        value = tok_app.get_token_count()
        assert _is_count(value), f"get_token_count() returned {value!r}; must be an int >= 0"


def test_api_usage_shape():
    response = tok_app.app.test_client().get("/api/usage")
    assert response.status_code == 200
    data = response.get_json()
    assert set(data) >= {"tokens", "scale"}, f"missing keys in {data!r}"
    assert _is_count(data["tokens"])
    assert isinstance(data["scale"], int) and data["scale"] > 0


if __name__ == "__main__":
    test_get_token_count_returns_non_negative_int()
    test_api_usage_shape()
    print("contract OK")
