#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
from pathlib import Path

from grader import grade_submissions
from renderer import write_report_bundle


def parse_args() -> argparse.Namespace:
    """Parse the command-line options used to run the grader.

    Parameters:
        None. This function reads arguments directly from the process command line.

    Returns:
        argparse.Namespace: An object containing the resolved values for the
        database path, answers file, responses CSV, and output directory.
    """
    parser = argparse.ArgumentParser(description="Grade SQL submissions from a Google Forms CSV export.")
    parser.add_argument("--db", required=True, help="Path to SQLite database file.")
    parser.add_argument("--answers", required=True, help="Path to SQL file containing correct answers.")
    parser.add_argument("--responses", required=True, help="Path to Google Forms CSV export.")
    parser.add_argument("--output", required=True, help="Output directory.")
    return parser.parse_args()


# Main flow overview:
# 1. `parse_args()` reads the CLI inputs that point at the database, answer key,
#    student submissions CSV, and output folder.
# 2. `main()` converts those raw strings into `Path` objects and validates that
#    the required input files exist before any grading work starts.
# 3. `main()` then calls `grade_submissions(...)` from `grader.py`. That routine
#    opens the CSV, detects the question columns, loops through each student row,
#    and then loops through each question number to execute and compare the
#    student SQL against the reference SQL.
# 4. After grading completes, `main()` passes the finished result objects to
#    `write_report_bundle(...)` in `renderer.py`, which formats SQL for display,
#    loads any saved manual adjustments, and writes the HTML, JSON, and CSV
#    report artifacts.
# 5. The final print statement confirms the output directory so the caller knows
#    where the generated review report was written.

def main() -> None:
    """Coordinate the full grading pipeline from CLI input to report output.

    Parameters:
        None. The function reads runtime settings from the command line by
        calling `parse_args()`.

    Returns:
        None. This function performs validation, grading, and report writing as
        side effects, then prints the output directory path when successful.
    """
    args = parse_args()

    db_path = Path(args.db)
    answers_file = Path(args.answers)
    responses_csv = Path(args.responses)
    output_dir = Path(args.output)

    if not db_path.exists():
        raise FileNotFoundError(f"Database file not found: {db_path}")
    if not answers_file.exists():
        raise FileNotFoundError(f"Answers file not found: {answers_file}")
    if not responses_csv.exists():
        raise FileNotFoundError(f"Responses CSV not found: {responses_csv}")

    results, total_questions = grade_submissions(
        db_path=db_path,
        answers_file=answers_file,
        responses_csv=responses_csv,
    )
    write_report_bundle(
        results=results,
        total_questions=total_questions,
        output_dir=output_dir,
    )

    print(f"Done. Output written to: {output_dir}")


if __name__ == "__main__":
    main()
