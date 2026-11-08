"""Parse CLI options and open private CSV files for a capture session."""

import argparse
import errno
from contextlib import ExitStack
from datetime import datetime
from pathlib import Path

from .feature_csv import FeatureCSV, open_unique_csv
from .server import serve
from .store import ReadingStore


def main():
    parser = argparse.ArgumentParser(description="Capture prompt features into a local CSV")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--csv", type=Path, help="Preferred draft CSV path (defaults to a timestamped file)")
    parser.add_argument("--vocab-size", type=int, help="Known target tokenizer vocabulary size")
    parser.add_argument("--submissions-csv", type=Path, help="Path for a separate inferred submissions CSV")
    parser.add_argument("--track-submissions", action="store_true", help="Enable a timestamped submissions CSV")
    args = parser.parse_args()

    if not 0 <= args.port <= 65535:
        parser.error("--port must be between 0 and 65535")
    if args.vocab_size is not None and args.vocab_size <= 0:
        parser.error("--vocab-size must be positive")
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    draft_path = args.csv or Path(f"prompt_features.{timestamp}.csv")
    submission_path = args.submissions_csv
    if args.track_submissions and submission_path is None:
        submission_path = Path(f"submitted_features.{timestamp}.csv")
    try:
        with ExitStack() as files:
            output = files.enter_context(open_unique_csv(draft_path))
            feature_csv = FeatureCSV(output)
            print(f"Draft CSV: {output.name}", flush=True)
            submissions = None
            if submission_path:
                submission_output = files.enter_context(open_unique_csv(submission_path))
                submissions = FeatureCSV(submission_output)
                print(f"Submission CSV: {submission_output.name}", flush=True)
            serve(args.port, ReadingStore(feature_csv, args.vocab_size, submissions))
    except OSError as error:
        if error.errno == errno.EADDRINUSE:
            parser.exit(1, f"Port {args.port} is already in use. Check http://127.0.0.1:{args.port}/health "
                        "or stop the existing backend before restarting Tok.\n")
        parser.exit(1, f"Tok could not start or write the CSV: {error}\n")


if __name__ == "__main__":
    main()
