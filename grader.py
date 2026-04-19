from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

try:
    import pandas as pd
except ImportError:
    raise SystemExit(
        "This script requires pandas.\n"
        "Install it with:\n"
        "    pip install pandas"
    )


SQL_START_KEYWORDS = (
    "select", "with", "insert", "update", "delete", "create", "drop", "alter",
    "pragma", "replace"
)


def read_text_file(path: Path) -> str:
    """Read a UTF-8 text file while tolerating malformed characters.

    Parameters:
        path: Filesystem path to the text file that should be loaded.

    Returns:
        str: The full file contents as a single string. Invalid byte sequences
        are replaced so the grader can continue working with imperfect files.
    """
    return path.read_text(encoding="utf-8", errors="replace")


def strip_bom(text: str) -> str:
    """Remove a UTF-8 byte-order mark if one is present at the start.

    Parameters:
        text: Raw text that may begin with a BOM character.

    Returns:
        str: The same text without a leading BOM so later parsing logic sees
        the expected first character.
    """
    return text.lstrip("\ufeff")


def remove_sql_comments(sql: str) -> str:
    """Strip block comments and line comments from a SQL string.

    Parameters:
        sql: SQL text that may include `/* ... */` comments or `--` comments.

    Returns:
        str: SQL with comments removed but line structure preserved as much as
        possible, which keeps downstream parsing simpler and more predictable.
    """
    sql = re.sub(r"/\*.*?\*/", "", sql, flags=re.DOTALL)

    lines = []
    for line in sql.splitlines():
        idx = line.find("--")
        if idx != -1:
            line = line[:idx]
        lines.append(line)
    return "\n".join(lines)


def split_top_level_args(s: str) -> List[str]:
    """Split a comma-delimited argument list while respecting nesting.

    Parameters:
        s: Text inside a function call or expression list where commas inside
        parentheses or quoted strings should not create a split.

    Returns:
        List[str]: A list of top-level argument fragments in their original
        order, without discarding embedded commas inside nested expressions.
    """
    args = []
    current = []
    depth = 0
    in_single = False
    in_double = False

    for ch in s:
        if ch == "'" and not in_double:
            in_single = not in_single
            current.append(ch)
            continue
        if ch == '"' and not in_single:
            in_double = not in_double
            current.append(ch)
            continue

        if not in_single and not in_double:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            elif ch == "," and depth == 0:
                args.append("".join(current))
                current = []
                continue

        current.append(ch)

    if current:
        args.append("".join(current))

    return args


def remove_round_functions(sql: str) -> str:
    """Remove `ROUND(...)` wrappers so rounded and unrounded answers can match.

    Parameters:
        sql: A normalized SQL statement that may wrap expressions in `ROUND()`.

    Returns:
        str: SQL with every top-level `ROUND(expression, ...)` reduced to its
        first argument so comparison focuses on the underlying calculation.
    """
    def strip_one_round(expr: str) -> str:
        """Remove the first `ROUND(...)` call found inside one expression.

        Parameters:
            expr: An expression or SQL fragment that may contain a `ROUND()`
            wrapper around another expression.

        Returns:
            str: The same expression with the first removable `ROUND()` call
            replaced by its first argument, or the original text if no safe
            replacement was found.
        """
        pattern = re.compile(r"\bROUND\s*\(", re.IGNORECASE)
        match = pattern.search(expr)
        if not match:
            return expr

        start = match.start()
        open_paren_idx = match.end() - 1

        depth = 0
        i = open_paren_idx
        in_single = False
        in_double = False

        while i < len(expr):
            ch = expr[i]

            if ch == "'" and not in_double:
                in_single = not in_single
            elif ch == '"' and not in_single:
                in_double = not in_double
            elif not in_single and not in_double:
                if ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
                    if depth == 0:
                        inner = expr[open_paren_idx + 1:i]
                        arg = split_top_level_args(inner)[0].strip() if inner.strip() else ""
                        return expr[:start] + arg + expr[i + 1:]

            i += 1

        return expr

    prev = None
    current = sql
    while prev != current:
        prev = current
        current = strip_one_round(current)
    return current


def contains_sql_keyword(text: str) -> bool:
    """Check whether a block of text appears to contain SQL at all.

    Parameters:
        text: Arbitrary text, often copied from a student response or answer
        file section, that might or might not contain a SQL statement.

    Returns:
        bool: True when one of the recognized starting SQL keywords is present;
        otherwise False.
    """
    lower = text.lower()
    return any(re.search(rf"\b{kw}\b", lower) for kw in SQL_START_KEYWORDS)


def find_first_sql_keyword_index(text: str) -> int:
    """Locate the earliest recognizable SQL starting keyword in text.

    Parameters:
        text: Free-form text that may include prose before the actual SQL.

    Returns:
        int: The character index of the first detected SQL keyword, or `0` if
        no keyword is found.
    """
    lower = text.lower()
    indices = []
    for kw in SQL_START_KEYWORDS:
        match = re.search(rf"\b{re.escape(kw)}\b", lower)
        if match:
            indices.append(match.start())
    return min(indices) if indices else 0


def heuristic_strip_prompt_prefix(block: str) -> str:
    """Remove common prompt text that students may leave before their SQL.

    Parameters:
        block: Raw student or answer-key text that may include question numbers,
        prose, or labels before the actual statement.

    Returns:
        str: A cleaned block that starts as close as possible to the intended
        SQL statement.
    """
    block = block.strip()
    if not block:
        return block

    idx = find_first_sql_keyword_index(block)
    block = block[idx:].strip()
    block = re.sub(r"^\s*(question\s*)?\d+\s*[\)\.\:-]\s*", "", block, flags=re.IGNORECASE)
    return block.strip()


def normalize_sql(sql: str) -> str:
    """Canonicalize SQL text before execution or comparison.

    Parameters:
        sql: Raw SQL text taken from the answer key or a student submission.

    Returns:
        str: SQL with BOMs removed, comments stripped, prompt prefixes removed,
        `ROUND()` wrappers simplified, and trailing semicolons normalized away.
    """
    sql = strip_bom(sql)
    sql = remove_sql_comments(sql)
    sql = heuristic_strip_prompt_prefix(sql)
    sql = remove_round_functions(sql)
    sql = sql.strip().rstrip(";").strip()
    return sql


def find_statement_end(text: str, start_idx: int) -> int:
    """Find the end of a SQL statement while respecting quoted strings.

    Parameters:
        text: A larger text block that contains at least one SQL statement.
        start_idx: The character index where the statement begins.

    Returns:
        int: The index of the terminating semicolon, or the end of the text if
        no semicolon is found outside of quotes.
    """
    in_single = False
    in_double = False
    i = start_idx

    while i < len(text):
        ch = text[i]

        if ch == "'" and not in_double:
            if in_single and i + 1 < len(text) and text[i + 1] == "'":
                i += 2
                continue
            in_single = not in_single
            i += 1
            continue

        if ch == '"' and not in_single:
            in_double = not in_double
            i += 1
            continue

        if ch == ";" and not in_single and not in_double:
            return i

        i += 1

    return len(text)


def parse_answer_key_sections(text: str) -> List[Dict[str, Any]]:
    """Break the answer file into numbered question sections.

    Parameters:
        text: Full contents of the answer SQL file.

    Returns:
        List[Dict[str, Any]]: One dictionary per detected question containing
        the numeric question id, any leading instructional comments, and the
        normalized reference SQL for that question.
    """
    text = strip_bom(text)
    markers = list(re.finditer(r"(?m)^\s*--\s*(\d+)\.", text))
    sections: List[Dict[str, Any]] = []

    for idx, marker in enumerate(markers):
        question_number = int(marker.group(1))
        block_start = marker.start()
        block_end = markers[idx + 1].start() if idx + 1 < len(markers) else len(text)
        block = text[block_start:block_end]

        sql_match = re.search(
            rf"(?im)^\s*(?:{'|'.join(re.escape(kw) for kw in SQL_START_KEYWORDS)})\b",
            block
        )
        if not sql_match:
            continue

        sql_start = sql_match.start()
        statement_end = find_statement_end(block, sql_start)
        raw_sql = block[sql_start:statement_end]
        normalized_sql = normalize_sql(raw_sql)
        if not normalized_sql or not contains_sql_keyword(normalized_sql):
            continue

        comment_lines: List[str] = []
        for line in block[:sql_start].splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("--"):
                cleaned = re.sub(r"^\s*--\s?", "", line).rstrip()
                if cleaned and not re.fullmatch(r"[-=]{3,}", cleaned):
                    comment_lines.append(cleaned)

        sections.append({
            "question_number": question_number,
            "comments": "\n".join(comment_lines).strip(),
            "sql": normalized_sql,
        })

    return sections


def execute_sql_query(
    db_path: Path,
    sql: str
) -> Tuple[bool, List[str], List[Tuple[Any, ...]], str]:
    """Execute one SQL statement against the grading database.

    Parameters:
        db_path: Path to the SQLite database used for grading.
        sql: The SQL statement to execute.

    Returns:
        Tuple[bool, List[str], List[Tuple[Any, ...]], str]:
            - success flag indicating whether execution completed.
            - list of column names from `cursor.description`.
            - fetched result rows as tuples.
            - error message string, empty when execution succeeded.
    """
    try:
        with sqlite3.connect(str(db_path)) as conn:
            cur = conn.cursor()
            cur.execute(sql)
            columns = [description[0] for description in (cur.description or [])]
            rows = cur.fetchall()
        return True, columns, rows, ""
    except Exception as exc:
        return False, [], [], str(exc)


def normalize_value_for_compare(value: Any) -> str:
    """Convert a SQLite value into a stable string for result comparison.

    Parameters:
        value: Any scalar value returned by SQLite, including `None`, numbers,
        or text.

    Returns:
        str: A normalized string representation that trims whitespace, renders
        nulls consistently, and reduces float noise from trailing zeros.
    """
    if value is None:
        return "NULL"
    if isinstance(value, float):
        rendered = f"{value:.10f}"
        if "." in rendered:
            rendered = rendered.rstrip("0").rstrip(".")
        return rendered
    return str(value).strip()


def canonicalize_row_ignore_column_order(row: Iterable[Any]) -> Tuple[str, ...]:
    """Normalize one row and sort its values for column-order-insensitive checks.

    Parameters:
        row: A single result row represented as any iterable of scalar values.

    Returns:
        Tuple[str, ...]: The normalized row values sorted into a stable tuple so
        two rows can be compared even if the columns were returned in a
        different order.
    """
    normalized = [normalize_value_for_compare(v) for v in row]
    normalized.sort()
    return tuple(normalized)


def compare_result_sets(
    student_rows: List[Tuple[Any, ...]],
    answer_rows: List[Tuple[Any, ...]]
) -> Tuple[bool, str]:
    """Compare student and reference query results using grader rules.

    Parameters:
        student_rows: Result rows returned by the student's SQL.
        answer_rows: Result rows returned by the reference SQL.

    Returns:
        Tuple[bool, str]:
            - True when the result sets match under the grader rules.
            - A status string explaining the outcome, such as `pass`,
              `extra_column`, `missing_column`, `row_count_mismatch`, or `fail`.
    """
    if len(student_rows) != len(answer_rows):
        return False, "row_count_mismatch"

    for student_row, answer_row in zip(student_rows, answer_rows):
        if len(student_row) < len(answer_row):
            return False, "missing_column"
        if len(student_row) > len(answer_row):
            return False, "extra_column"

        student_canonical = canonicalize_row_ignore_column_order(student_row)
        answer_canonical = canonicalize_row_ignore_column_order(answer_row)

        if student_canonical != answer_canonical:
            return False, "fail"

    return True, "pass"


def safe_slug(value: str) -> str:
    """Create a filesystem-safe and storage-safe identifier from free text.

    Parameters:
        value: Arbitrary text such as a student name combined with an index.

    Returns:
        str: A sanitized slug using only letters, numbers, periods,
        underscores, and dashes. A fallback value of `"student"` is returned if
        sanitization removes everything.
    """
    value = value.strip()
    value = re.sub(r"[^A-Za-z0-9._-]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("_")
    return value or "student"


def detect_question_columns(columns: List[str]) -> List[Tuple[int, str]]:
    """Identify Google Forms columns that correspond to numbered questions.

    Parameters:
        columns: The full list of CSV column headers from the submission file.

    Returns:
        List[Tuple[int, str]]: A sorted list of `(question_number, column_name)`
        pairs for headers that begin with a number like `1.`, `2.`, and so on.
    """
    found = []
    for col in columns:
        match = re.match(r"^\s*(\d+)\s*\.", str(col))
        if match:
            qnum = int(match.group(1))
            found.append((qnum, col))
    found.sort(key=lambda item: item[0])
    return found


def value_to_sql_text(value: Any) -> str:
    """Convert a pandas cell value into a usable SQL string.

    Parameters:
        value: A value pulled from the submissions DataFrame, which may be
        missing, `NaN`, or already text.

    Returns:
        str: A stripped string version of the value, or an empty string when
        the cell should be treated as blank.
    """
    if value is None:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    text = str(value).strip()
    if text.lower() == "nan":
        return ""
    return text


def build_question_result(
    qnum: int,
    student_sql: Optional[str],
    answer_sql: Optional[str],
    question_comments: str,
    db_path: Path
) -> Dict[str, Any]:
    """Build the full grading record for one student on one question.

    Parameters:
        qnum: Numeric question id being graded.
        student_sql: Student-submitted SQL for the question, if any.
        answer_sql: Reference SQL from the answer key, if any.
        question_comments: Prompt or comment text associated with the question.
        db_path: Path to the SQLite database used for execution.

    Returns:
        Dict[str, Any]: A complete per-question result object containing the raw
        SQL, normalized SQL, execution status, column names, result rows,
        comparison outcome, and final status code used by the viewer.
    """
    result: Dict[str, Any] = {
        "question_number": qnum,
        "question_comments": question_comments,
        "student_sql": student_sql or "",
        "answer_sql": answer_sql or "",
        "student_sql_normalized": normalize_sql(student_sql) if student_sql else "",
        "answer_sql_normalized": normalize_sql(answer_sql) if answer_sql else "",
        "student_exec_ok": False,
        "answer_exec_ok": False,
        "student_error": "",
        "answer_error": "",
        "student_columns": [],
        "answer_columns": [],
        "student_rows": [],
        "answer_rows": [],
        "is_correct": False,
        "status": "fail",
    }

    if answer_sql:
        answer_ok, answer_columns, answer_rows, answer_err = execute_sql_query(
            db_path,
            result["answer_sql_normalized"]
        )
        result["answer_exec_ok"] = answer_ok
        result["answer_error"] = answer_err
        result["answer_columns"] = answer_columns
        result["answer_rows"] = [list(row) for row in answer_rows]

    if student_sql:
        student_ok, student_columns, student_rows, student_err = execute_sql_query(
            db_path,
            result["student_sql_normalized"]
        )
        result["student_exec_ok"] = student_ok
        result["student_error"] = student_err
        result["student_columns"] = student_columns
        result["student_rows"] = [list(row) for row in student_rows]

    if not student_sql or not answer_sql:
        return result

    if not result["student_exec_ok"] or not result["answer_exec_ok"]:
        result["status"] = "fail"
        return result

    matched, compare_status = compare_result_sets(
        [tuple(row) for row in result["student_rows"]],
        [tuple(row) for row in result["answer_rows"]],
    )
    result["is_correct"] = matched
    result["status"] = "pass" if matched else compare_status
    return result


def grade_submissions(
    db_path: Path,
    answers_file: Path,
    responses_csv: Path
) -> Tuple[List[Dict[str, Any]], int]:
    """Grade every student submission in the CSV against the answer key.

    Parameters:
        db_path: Path to the SQLite database that should be queried.
        answers_file: Path to the SQL answer key file.
        responses_csv: Path to the Google Forms CSV containing student answers.

    Returns:
        Tuple[List[Dict[str, Any]], int]:
            - A list of per-student grading records, each containing all
              question-level results.
            - The total number of questions represented across the CSV and
              answer key, which is later used to build the report layout.
    """
    answers_text = read_text_file(answers_file)
    answer_sections = parse_answer_key_sections(answers_text)
    if not answer_sections:
        raise ValueError("No answer SQL statements found in answers file.")

    df = pd.read_csv(responses_csv)
    question_columns = detect_question_columns(list(df.columns))
    if not question_columns:
        raise ValueError(
            "No question columns found in the CSV. Expected headers like '1. ...', '2. ...', etc."
        )

    question_numbers_in_csv = [qnum for qnum, _ in question_columns]
    max_q_csv = max(question_numbers_in_csv)
    answer_sections_by_qnum = {
        section["question_number"]: section
        for section in answer_sections
    }
    max_q_answers = max(answer_sections_by_qnum)
    total_questions = max(max_q_csv, max_q_answers)

    results: List[Dict[str, Any]] = []

    for idx, row in df.iterrows():
        student_name = value_to_sql_text(row.get("Full Name", "")) or f"Student {idx + 1}"

        student_answers_by_qnum: Dict[int, str] = {}
        for qnum, colname in question_columns:
            student_answers_by_qnum[qnum] = value_to_sql_text(row.get(colname, ""))

        question_results = []
        for qnum in range(1, total_questions + 1):
            student_sql = student_answers_by_qnum.get(qnum, "")
            answer_section = answer_sections_by_qnum.get(qnum, {})
            question_results.append(
                build_question_result(
                    qnum=qnum,
                    student_sql=student_sql,
                    answer_sql=answer_section.get("sql", ""),
                    question_comments=answer_section.get("comments", ""),
                    db_path=db_path,
                )
            )

        results.append({
            "student_name": student_name,
            "student_slug": safe_slug(f"{student_name}_{idx + 1}"),
            "questions": question_results,
        })

    return results, total_questions
