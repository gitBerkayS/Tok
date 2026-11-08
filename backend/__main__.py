"""Parse CLI options and open private CSV files for a capture session."""

import argparse
import os
from contextlib import ExitStack
from pathlib import Path

from .feature_csv import FeatureCSV
from .server import serve
from .store import ReadingStore


def private_file(path, flags):
    return os.open(path, flags, 0o600)


def main():
    parser = argparse.ArgumentParser(description="Capture prompt features into a local CSV")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--csv", type=Path, required=True, help="Path for a new capture CSV")
    parser.add_argument("--vocab-size", type=int, help="Known target tokenizer vocabulary size")
    parser.add_argument("--submissions-csv", type=Path, help="Path for a separate inferred submissions CSV")
    args = parser.parse_args()

    if not 0 <= args.port <= 65535:
        parser.error("--port must be between 0 and 65535")
    if args.vocab_size is not None and args.vocab_size <= 0:
        parser.error("--vocab-size must be positive")
    try:
        with ExitStack() as files:
            output = files.enter_context(open(args.csv, "x", encoding="utf-8", newline="", opener=private_file))
            submissions = None
            if args.submissions_csv:
                submission_output = files.enter_context(
                    open(args.submissions_csv, "x", encoding="utf-8", newline="", opener=private_file)
                )
                submissions = FeatureCSV(submission_output)
            serve(args.port, ReadingStore(FeatureCSV(output), args.vocab_size, submissions))
    except OSError as error:
        parser.exit(1, f"Tok could not start or write the CSV: {error}\n")


if __name__ == "__main__":
    main()
