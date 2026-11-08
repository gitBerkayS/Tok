"""Parse CLI options and open private CSV files for a capture session."""

import argparse
import errno
import fcntl
import json
from contextlib import ExitStack, contextmanager
from datetime import datetime
from pathlib import Path

from .feature_csv import (
    CURRENT_DRAFT_CSV, CURRENT_SUBMISSIONS_CSV, FeatureCSV, open_unique_csv, reset_csv,
)
from .server import serve
from .store import ReadingStore
from .token_estimator import estimate_csv


@contextmanager
def capture_store(draft_path, submission_path, vocab_size, reset_on_startup):
    with ExitStack() as files:
        if reset_on_startup:
            lock = files.enter_context(open(".tok-session.lock", "a"))
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise RuntimeError("A Tok session already owns the current CSV files.") from error
            feature_csv = files.enter_context(reset_csv(draft_path))
            submissions = files.enter_context(reset_csv(submission_path))
            print(f"Draft CSV: {draft_path}", flush=True)
            print(f"Submission CSV: {submission_path}", flush=True)
        else:
            output = files.enter_context(open_unique_csv(draft_path))
            feature_csv = FeatureCSV(output)
            print(f"Draft CSV: {output.name}", flush=True)
            submissions = None
            if submission_path:
                submission_output = files.enter_context(open_unique_csv(submission_path))
                submissions = FeatureCSV(submission_output)
                print(f"Submission CSV: {submission_output.name}", flush=True)
        yield ReadingStore(feature_csv, vocab_size, submissions)


def main():
    parser = argparse.ArgumentParser(description="Capture prompt features into a local CSV")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--csv", type=Path, help="Preferred draft CSV path (defaults to a timestamped file)")
    parser.add_argument("--vocab-size", type=int, help="Known target tokenizer vocabulary size")
    parser.add_argument("--submissions-csv", type=Path, help="Path for a separate inferred submissions CSV")
    parser.add_argument("--track-submissions", action="store_true", help="Enable a timestamped submissions CSV")
    parser.add_argument("--reset-on-startup", action="store_true", help="Reset the two current-session CSVs and track submissions")
    parser.add_argument("--estimate-csv", type=Path, help="Estimate tokens from an existing capture CSV and exit")
    args = parser.parse_args()

    if not 0 <= args.port <= 65535:
        parser.error("--port must be between 0 and 65535")
    if args.vocab_size is not None and args.vocab_size <= 0:
        parser.error("--vocab-size must be positive")
    if args.estimate_csv:
        try:
            result = estimate_csv(args.estimate_csv, args.vocab_size)
        except (OSError, ValueError, RuntimeError) as error:
            parser.exit(1, f"Could not estimate CSV: {error}\n")
        print(json.dumps(result, indent=2))
        return
    if args.reset_on_startup:
        if args.csv or args.submissions_csv:
            parser.error("--reset-on-startup uses dedicated current-session filenames")
        draft_path = Path(CURRENT_DRAFT_CSV)
        submission_path = Path(CURRENT_SUBMISSIONS_CSV)
    else:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        draft_path = args.csv or Path(f"prompt_features.{timestamp}.csv")
        submission_path = args.submissions_csv
        if args.track_submissions and submission_path is None:
            submission_path = Path(f"submitted_features.{timestamp}.csv")
    try:
        serve(args.port, capture_store(draft_path, submission_path, args.vocab_size, args.reset_on_startup))
    except RuntimeError as error:
        parser.exit(1, f"{error}\n")
    except OSError as error:
        if error.errno == errno.EADDRINUSE:
            parser.exit(1, f"Port {args.port} is already in use. Check http://127.0.0.1:{args.port}/health "
                        "or stop the existing backend before restarting Tok.\n")
        parser.exit(1, f"Tok could not start or write the CSV: {error}\n")


if __name__ == "__main__":
    main()
