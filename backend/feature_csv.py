"""Write numeric features in the stable CSV column order."""

import csv
from dataclasses import astuple, fields

from .analyzer import Features


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
