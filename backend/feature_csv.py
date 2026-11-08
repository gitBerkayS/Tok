"""Write numeric features in the stable CSV column order."""

import csv
import os
from dataclasses import astuple, fields

from .analyzer import Features


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
        self.writer.writerow(field.name for field in fields(Features))
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
