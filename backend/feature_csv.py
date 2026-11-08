"""Write numeric features in the stable CSV column order."""

import csv
import os
from contextlib import contextmanager
from dataclasses import astuple
from pathlib import Path
from tempfile import NamedTemporaryFile

from .analyzer import FEATURE_COLUMNS, Features

CURRENT_DRAFT_CSV = "prompt_features.current.csv"
CURRENT_SUBMISSIONS_CSV = "submitted_features.current.csv"


def _private_file(path, flags):
    return os.open(path, flags, 0o600)


def open_unique_csv(path):
    """Create a private CSV without overwriting a previous capture."""
    candidate = path
    suffix = 2
    while True:
        try:
            return open(candidate, "x", encoding="utf-8", newline="", opener=_private_file)
        except FileExistsError:
            candidate = path.with_name(f"{path.stem}-{suffix}{path.suffix}")
            suffix += 1


class FeatureCSV:
    def __init__(self, output):
        self.output = output
        self.writer = csv.writer(output)
        self.writer.writerow(FEATURE_COLUMNS)
        self.output.flush()

    def append(self, features: Features):
        position = self.output.tell()
        try:
            self.writer.writerow(astuple(features))
            self.output.flush()
        except OSError:
            self.output.seek(position)
            self.output.truncate()
            raise


@contextmanager
def reset_csv(path):
    """Publish a fresh header atomically so readers never see a truncated CSV."""
    with NamedTemporaryFile(
        mode="w", encoding="utf-8", newline="", dir=path.parent, delete=False
    ) as output:
        temporary_path = Path(output.name)
        try:
            writer = FeatureCSV(output)
            os.replace(temporary_path, path)
            yield writer
        finally:
            temporary_path.unlink(missing_ok=True)
