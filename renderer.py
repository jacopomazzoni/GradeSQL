from __future__ import annotations

import csv
import html
import json
import re
from pathlib import Path
from typing import Any, Dict, List


DISPLAY_CLAUSE_KEYWORDS = (
    ("left outer join", "LEFT OUTER JOIN"),
    ("right outer join", "RIGHT OUTER JOIN"),
    ("inner join", "INNER JOIN"),
    ("left join", "LEFT JOIN"),
    ("right join", "RIGHT JOIN"),
    ("full join", "FULL JOIN"),
    ("group by", "GROUP BY"),
    ("order by", "ORDER BY"),
    ("union all", "UNION ALL"),
    ("select", "SELECT"),
    ("from", "FROM"),
    ("where", "WHERE"),
    ("having", "HAVING"),
    ("limit", "LIMIT"),
    ("offset", "OFFSET"),
    ("join", "JOIN"),
    ("on", "ON"),
)
SQL_START_KEYWORDS = (
    "select", "with", "insert", "update", "delete", "create", "drop", "alter",
    "pragma", "replace"
)
QUESTION_POINTS = 5.0
ADJUSTMENTS_FILENAME = "manual_adjustments.json"
ADJUSTMENTS_VERSION = 1


def ensure_dir(path: Path) -> None:
    """Create an output directory if it does not already exist.

    Parameters:
        path: Directory path that should exist before report files are written.

    Returns:
        None. The function performs filesystem side effects only.
    """
    path.mkdir(parents=True, exist_ok=True)


def strip_bom(text: str) -> str:
    """Remove a leading byte-order mark from text used in rendering helpers.

    Parameters:
        text: Input text that may start with a UTF-8 BOM.

    Returns:
        str: The same text without a leading BOM character.
    """
    return text.lstrip("\ufeff")


def remove_sql_comments(sql: str) -> str:
    """Remove SQL comments before formatting statements for display.

    Parameters:
        sql: SQL text that may include line comments or block comments.

    Returns:
        str: SQL with comments stripped so display formatting is based only on
        executable SQL content.
    """
    sql = re.sub(r"/\*.*?\*/", "", sql, flags=re.DOTALL)

    lines = []
    for line in sql.splitlines():
        idx = line.find("--")
        if idx != -1:
            line = line[:idx]
        lines.append(line)
    return "\n".join(lines)


def contains_sql_keyword(text: str) -> bool:
    """Detect whether a text block contains a likely SQL statement.

    Parameters:
        text: Arbitrary text that may mix prose and SQL.

    Returns:
        bool: True when one of the known SQL starting keywords is present.
    """
    lower = text.lower()
    return any(re.search(rf"\b{kw}\b", lower) for kw in SQL_START_KEYWORDS)


def find_first_sql_keyword_index(text: str) -> int:
    """Locate the earliest SQL keyword in mixed prompt-and-SQL text.

    Parameters:
        text: Input text that may begin with prose before the SQL statement.

    Returns:
        int: Index of the first recognized SQL keyword, or `0` when none is
        found.
    """
    lower = text.lower()
    indices = []
    for kw in SQL_START_KEYWORDS:
        match = re.search(rf"\b{re.escape(kw)}\b", lower)
        if match:
            indices.append(match.start())
    return min(indices) if indices else 0


def heuristic_strip_prompt_prefix(block: str) -> str:
    """Trim off question labels or prompt text that precede SQL.

    Parameters:
        block: Raw SQL-like text pulled from answers or submissions.

    Returns:
        str: A cleaned string that begins at the first likely SQL keyword and
        no longer includes leading question numbering noise.
    """
    block = block.strip()
    if not block:
        return block

    idx = find_first_sql_keyword_index(block)
    block = block[idx:].strip()
    block = re.sub(r"^\s*(question\s*)?\d+\s*[\)\.\:-]\s*", "", block, flags=re.IGNORECASE)
    return block.strip()


def split_sql_blocks(text: str) -> List[str]:
    """Split a text blob into individual SQL statements for display formatting.

    Parameters:
        text: Raw SQL text that may contain multiple statements separated by
        semicolons.

    Returns:
        List[str]: The detected SQL statements, excluding empty fragments and
        non-SQL leftovers.
    """
    text = strip_bom(text)
    text = remove_sql_comments(text)
    text = heuristic_strip_prompt_prefix(text)

    statements = []
    current = []
    in_single = False
    in_double = False
    i = 0

    while i < len(text):
        ch = text[i]

        if ch == "'" and not in_double:
            if in_single and i + 1 < len(text) and text[i + 1] == "'":
                current.append(ch)
                current.append(text[i + 1])
                i += 2
                continue
            in_single = not in_single
            current.append(ch)
            i += 1
            continue

        if ch == '"' and not in_single:
            in_double = not in_double
            current.append(ch)
            i += 1
            continue

        if ch == ";" and not in_single and not in_double:
            stmt = "".join(current).strip()
            if stmt:
                statements.append(stmt)
            current = []
            i += 1
            continue

        current.append(ch)
        i += 1

    tail = "".join(current).strip()
    if tail:
        statements.append(tail)

    return [stmt for stmt in statements if contains_sql_keyword(stmt)]


def collapse_sql_whitespace(sql: str) -> str:
    """Normalize whitespace while preserving quoted string contents.

    Parameters:
        sql: A SQL statement whose spacing should be simplified.

    Returns:
        str: SQL with repeated whitespace collapsed to single spaces outside of
        quoted strings.
    """
    parts = []
    in_single = False
    in_double = False
    pending_space = False
    i = 0

    while i < len(sql):
        ch = sql[i]

        if ch == "'" and not in_double:
            if in_single and i + 1 < len(sql) and sql[i + 1] == "'":
                if pending_space and parts and parts[-1] not in {" ", "\n"}:
                    parts.append(" ")
                pending_space = False
                parts.append(ch)
                parts.append(sql[i + 1])
                i += 2
                continue
            if pending_space and parts and parts[-1] not in {" ", "\n"}:
                parts.append(" ")
            pending_space = False
            in_single = not in_single
            parts.append(ch)
            i += 1
            continue

        if ch == '"' and not in_single:
            if pending_space and parts and parts[-1] not in {" ", "\n"}:
                parts.append(" ")
            pending_space = False
            in_double = not in_double
            parts.append(ch)
            i += 1
            continue

        if not in_single and not in_double and ch.isspace():
            pending_space = True
            i += 1
            continue

        if pending_space and parts and parts[-1] not in {" ", "\n"}:
            parts.append(" ")
        pending_space = False
        parts.append(ch)
        i += 1

    return "".join(parts).strip()


def format_single_sql_statement_for_display(sql: str) -> str:
    """Render one SQL statement with clause-oriented line breaks.

    Parameters:
        sql: A single SQL statement to make easier to read in the report.

    Returns:
        str: A display-oriented version of the statement with major clauses
        moved onto separate lines and a normalized trailing semicolon.
    """
    formatted = collapse_sql_whitespace(sql).strip().rstrip(";").strip()
    if not formatted:
        return ""

    for keyword, replacement in DISPLAY_CLAUSE_KEYWORDS:
        pattern = r"\b" + re.sub(r"\s+", r"\\s+", re.escape(keyword)) + r"\b"
        formatted = re.sub(
            pattern,
            lambda _: f"\n{replacement}\n",
            formatted,
            flags=re.IGNORECASE
        )

    lines = [line.strip() for line in formatted.splitlines() if line.strip()]
    if not lines:
        return ""

    lines[-1] = lines[-1].rstrip(";") + ";"
    return "\n".join(lines)


def format_sql_for_display(sql: str) -> str:
    """Format one or more SQL statements for presentation in the viewer.

    Parameters:
        sql: Raw SQL text that may contain zero, one, or multiple statements.

    Returns:
        str: A readable multiline SQL block suitable for the side-by-side
        viewer panes in the generated HTML report.
    """
    if not sql:
        return ""

    statements = split_sql_blocks(sql)
    if not statements:
        fallback = collapse_sql_whitespace(sql.strip())
        return fallback if not fallback else fallback.rstrip(";") + ";"

    formatted_statements = [
        formatted
        for formatted in (format_single_sql_statement_for_display(stmt) for stmt in statements)
        if formatted
    ]
    return "\n\n".join(formatted_statements)


def html_escape(text: str) -> str:
    """Escape text so it is safe to inject into HTML markup.

    Parameters:
        text: Untrusted or plain text that will be inserted into HTML.

    Returns:
        str: HTML-escaped text with quotes escaped as well.
    """
    return html.escape(text, quote=True)


def safe_slug(value: str) -> str:
    """Sanitize arbitrary text into a compact slug identifier.

    Parameters:
        value: Source text such as a student name or override key component.

    Returns:
        str: A slug containing only filesystem-safe characters, with a default
        fallback of `"student"` when the input becomes empty.
    """
    value = value.strip()
    value = re.sub(r"[^A-Za-z0-9._-]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("_")
    return value or "student"


def write_csv(results: List[Dict[str, Any]], output_csv: Path) -> None:
    """Write the flattened per-question grading data to a CSV file.

    Parameters:
        results: Full per-student result objects that include question-level
        grading records.
        output_csv: Destination path for the exported CSV file.

    Returns:
        None. The function writes the CSV file as a side effect.
    """
    fieldnames = [
        "student_name",
        "question_number",
        "status",
        "is_correct",
        "student_exec_ok",
        "answer_exec_ok",
        "student_error",
        "answer_error",
        "student_sql",
        "answer_sql",
        "student_sql_normalized",
        "answer_sql_normalized",
    ]

    with output_csv.open("w", newline="", encoding="utf-8") as file_handle:
        writer = csv.DictWriter(file_handle, fieldnames=fieldnames)
        writer.writeheader()

        for student in results:
            for question in student["questions"]:
                writer.writerow({
                    "student_name": student["student_name"],
                    "question_number": question["question_number"],
                    "status": question["status"],
                    "is_correct": question["is_correct"],
                    "student_exec_ok": question["student_exec_ok"],
                    "answer_exec_ok": question["answer_exec_ok"],
                    "student_error": question["student_error"],
                    "answer_error": question["answer_error"],
                    "student_sql": question["student_sql"],
                    "answer_sql": question["answer_sql"],
                    "student_sql_normalized": question["student_sql_normalized"],
                    "answer_sql_normalized": question["answer_sql_normalized"],
                })


def format_points_number(value: float) -> str:
    """Render a point value with human-friendly trimming.

    Parameters:
        value: Numeric score value to display.

    Returns:
        str: A trimmed string representation with at most two decimals and no
        unnecessary trailing zeros.
    """
    rounded = round(float(value), 2)
    if rounded.is_integer():
        return str(int(rounded))
    return f"{rounded:.2f}".rstrip("0").rstrip(".")


def auto_points_for_status(status: str, question_points: float = QUESTION_POINTS) -> float:
    """Translate an automatic grading status into awarded points.

    Parameters:
        status: Status code for a question, such as `pass` or `fail`.
        question_points: Maximum number of points available for one question.

    Returns:
        float: The automatic score to award for that status.
    """
    if status in {"pass", "extra_column"}:
        return question_points
    return 0.0


def default_adjustments_payload() -> Dict[str, Any]:
    """Create the default manual-adjustments payload structure.

    Parameters:
        None.

    Returns:
        Dict[str, Any]: A new adjustments object with version metadata,
        question-point metadata, and an empty overrides map.
    """
    return {
        "version": ADJUSTMENTS_VERSION,
        "question_points": QUESTION_POINTS,
        "overrides": {},
    }


def normalize_adjustments_payload(payload: Any) -> Dict[str, Any]:
    """Validate and sanitize a manual-adjustments payload.

    Parameters:
        payload: Parsed JSON or arbitrary data that may represent manual score
        overrides.

    Returns:
        Dict[str, Any]: A normalized adjustments structure containing only
        valid override records and clamped point values.
    """
    normalized = default_adjustments_payload()
    if not isinstance(payload, dict):
        return normalized

    raw_overrides = payload.get("overrides", {})
    cleaned_overrides: Dict[str, Dict[str, Any]] = {}

    if isinstance(raw_overrides, dict):
        for raw_override in raw_overrides.values():
            if not isinstance(raw_override, dict):
                continue

            student_slug = safe_slug(str(raw_override.get("student_slug", "")))
            if not student_slug:
                continue

            try:
                question_number = int(raw_override.get("question_number"))
                points = float(raw_override.get("points"))
            except (TypeError, ValueError):
                continue

            points = max(0.0, min(QUESTION_POINTS, points))
            key = f"{student_slug}::{question_number}"
            cleaned_overrides[key] = {
                "student_slug": student_slug,
                "student_name": str(raw_override.get("student_name", "")).strip(),
                "question_number": question_number,
                "points": points,
                "note": str(raw_override.get("note", "")).strip(),
                "status": str(raw_override.get("status", "")).strip(),
                "updated_at": str(raw_override.get("updated_at", "")).strip(),
            }

    normalized["overrides"] = cleaned_overrides
    return normalized


def load_adjustments(path: Path) -> Dict[str, Any]:
    """Load saved manual score overrides from disk if the file exists.

    Parameters:
        path: Path to the JSON adjustments file beside the generated report.

    Returns:
        Dict[str, Any]: A normalized adjustments payload. If the file is
        missing or invalid, a default empty payload is returned instead.
    """
    if not path.exists():
        return default_adjustments_payload()

    try:
        payload = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except json.JSONDecodeError:
        return default_adjustments_payload()

    return normalize_adjustments_payload(payload)


def write_adjustments_file(path: Path, adjustments: Dict[str, Any]) -> None:
    """Persist the manual-adjustments payload to JSON on disk.

    Parameters:
        path: Destination path for the adjustments JSON file.
        adjustments: Adjustment payload to normalize and write.

    Returns:
        None. The file is written as a side effect.
    """
    payload = normalize_adjustments_payload(adjustments)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )


def status_symbol(status: str) -> str:
    """Convert a status code into the compact label shown in the grid.

    Parameters:
        status: Internal grading status string.

    Returns:
        str: Short human-readable text used inside the grade cell.
    """
    if status == "pass":
        return "PASS"
    if status == "extra_column":
        return "EXTRA COL"
    if status == "missing_column":
        return "MISSING COL"
    if status == "row_count_mismatch":
        return "ROW COUNT"
    return "FAIL"


def prepare_results_for_rendering(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Augment grading results with display-only SQL formatting fields.

    Parameters:
        results: Raw grading results returned by the grading module.

    Returns:
        List[Dict[str, Any]]: A copied result structure where each question also
        includes formatted SQL strings used by the HTML viewer.
    """
    prepared_results: List[Dict[str, Any]] = []

    for student in results:
        prepared_questions = []
        for question in student["questions"]:
            prepared_question = dict(question)
            prepared_question["student_sql_display"] = format_sql_for_display(question.get("student_sql", ""))
            prepared_question["answer_sql_display"] = format_sql_for_display(question.get("answer_sql", ""))
            prepared_questions.append(prepared_question)

        prepared_student = dict(student)
        prepared_student["questions"] = prepared_questions
        prepared_results.append(prepared_student)

    return prepared_results


def build_index_html(
    results: List[Dict[str, Any]],
    total_questions: int,
    adjustments: Dict[str, Any],
    question_points: float,
    adjustments_filename: str,
) -> str:
    """Build the full interactive grading report as one HTML document.

    Parameters:
        results: Prepared per-student results, including display-friendly SQL.
        total_questions: Number of question columns to render in the main grid.
        adjustments: Initial manual-adjustments payload to embed in the page.
        question_points: Maximum points available for each question.
        adjustments_filename: Filename the browser should use when loading or
        saving manual corrections.

    Returns:
        str: The complete HTML report, including CSS, JavaScript, summary
        widgets, the grading grid, and the detailed review viewer.
    """
    headers = "".join(
        f'<th class="question-head">Q{q}</th>'
        for q in range(1, total_questions + 1)
    )
    max_total_points = total_questions * question_points

    rows: List[str] = []
    detail_data = []

    for student_idx, student in enumerate(results):
        auto_total_points = sum(
            auto_points_for_status(q["status"], question_points)
            for q in student["questions"]
        )

        cells = []
        for question in student["questions"]:
            status = question["status"]
            auto_points = auto_points_for_status(status, question_points)
            title = f"Q{question['question_number']}: {status.replace('_', ' ').upper()}"

            cells.append(
                f'<td class="grade-cell {status}" '
                f'title="{html_escape(title)}" '
                f'data-student-index="{student_idx}" '
                f'data-student-slug="{html_escape(student["student_slug"])}" '
                f'data-question-number="{question["question_number"]}" '
                f'data-status="{html_escape(status)}" '
                f'data-auto-points="{auto_points:.2f}" '
                f'onclick="showDetail({student_idx}, {question["question_number"]})">'
                f'<div class="cell-main">{status_symbol(status)}</div>'
                f'<div class="cell-meta hidden"></div>'
                f'</td>'
            )

        rows.append(
            f"""
<tr data-student-index="{student_idx}" data-student-slug="{html_escape(student["student_slug"])}">
  <td class="student-col">{html_escape(student["student_name"])}</td>
  <td
    class="score-col"
    id="score-cell-{student_idx}"
    data-student-index="{student_idx}"
    data-auto-points="{auto_total_points:.2f}"
  >{format_points_number(auto_total_points)}/{format_points_number(max_total_points)}</td>
  {''.join(cells)}
</tr>
""".strip()
        )

        student_entry = {
            "student_name": student["student_name"],
            "student_slug": student["student_slug"],
            "questions": []
        }
        for question in student["questions"]:
            student_entry["questions"].append({
                "question_number": question["question_number"],
                "status": question["status"],
                "is_correct": question["is_correct"],
                "question_comments": question["question_comments"],
                "student_sql": question["student_sql"],
                "answer_sql": question["answer_sql"],
                "student_sql_display": question["student_sql_display"],
                "answer_sql_display": question["answer_sql_display"],
                "student_exec_ok": question["student_exec_ok"],
                "answer_exec_ok": question["answer_exec_ok"],
                "student_error": question["student_error"],
                "answer_error": question["answer_error"],
                "student_columns": question["student_columns"],
                "answer_columns": question["answer_columns"],
                "student_rows": question["student_rows"],
                "answer_rows": question["answer_rows"],
            })
        detail_data.append(student_entry)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>SQL Grader - Review Grid</title>
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <style>
    :root {{
      --green: #1e7e34;
      --green-bg: #eaf7ee;
      --red: #b02a37;
      --red-bg: #fbecee;
      --amber: #856404;
      --amber-bg: #fff3cd;
      --olive: #78825a;
      --olive-bg: #f3f5e6;
      --blue: #0d6efd;
      --blue-bg: #eef5ff;
      --blue-strong: #084298;
      --border: #d9dde3;
      --text: #212529;
      --muted: #5c6770;
      --panel: #ffffff;
      --bg: #f5f7fb;
      --shadow: 0 14px 34px rgba(15, 23, 42, 0.08);
      --student-col-width: 240px;
      --score-col-width: 120px;
      --cell-width: 112px;
    }}

    * {{
      box-sizing: border-box;
    }}

    body {{
      margin: 0;
      font-family: "Segoe UI", Tahoma, Geneva, Verdana, sans-serif;
      background:
        radial-gradient(circle at top left, rgba(13, 110, 253, 0.08), transparent 32%),
        linear-gradient(180deg, #f8fbff 0%, var(--bg) 100%);
      color: var(--text);
    }}

    .page-wrap {{
      max-width: 1760px;
      margin: 0 auto;
      padding: 24px;
    }}

    h1 {{
      margin: 0 0 8px 0;
      font-size: 30px;
    }}

    .sub {{
      color: var(--muted);
      margin-bottom: 18px;
      line-height: 1.5;
    }}

    .legend {{
      display: flex;
      gap: 16px;
      flex-wrap: wrap;
      margin-bottom: 18px;
      font-size: 14px;
    }}

    .legend-item {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
    }}

    .legend-box {{
      display: inline-block;
      width: 18px;
      height: 18px;
      border-radius: 4px;
      border: 1px solid var(--border);
    }}

    .legend-box.pass {{
      background: var(--green-bg);
      border-color: #b7e0c2;
    }}

    .legend-box.fail {{
      background: var(--red-bg);
      border-color: #efc2c7;
    }}

    .legend-box.partial {{
      background: var(--amber-bg);
      border-color: #ffe69c;
    }}

    .legend-box.selected {{
      background: var(--blue-bg);
      border-color: #b6d0ff;
    }}

    .legend-box.manual {{
      background: #dbeafe;
      border-color: #93c5fd;
    }}

    .toolbar {{
      display: grid;
      grid-template-columns: minmax(0, 2fr) minmax(280px, 1fr);
      gap: 16px;
      margin-bottom: 18px;
    }}

    .toolbar-card,
    .detail-panel,
    .adjustments-panel,
    .table-wrap {{
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 12px;
      box-shadow: var(--shadow);
    }}

    .toolbar-card {{
      padding: 16px 18px;
    }}

    .toolbar-title {{
      font-size: 16px;
      font-weight: 700;
      margin-bottom: 8px;
    }}

    .toolbar-copy {{
      color: var(--muted);
      font-size: 14px;
      line-height: 1.5;
      margin-bottom: 14px;
    }}

    .toolbar-actions {{
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      align-items: center;
    }}

    button,
    .button-label {{
      appearance: none;
      border: 1px solid #0b5ed7;
      background: var(--blue);
      color: #fff;
      border-radius: 8px;
      padding: 10px 14px;
      font-size: 14px;
      font-weight: 600;
      cursor: pointer;
      transition: transform 0.15s ease, box-shadow 0.15s ease, background 0.15s ease;
      text-decoration: none;
    }}

    button:hover,
    .button-label:hover {{
      transform: translateY(-1px);
      box-shadow: 0 8px 20px rgba(13, 110, 253, 0.16);
    }}

    button.secondary,
    .button-label.secondary {{
      background: #fff;
      color: var(--blue-strong);
      border-color: #b6d0ff;
      box-shadow: none;
    }}

    .button-label input {{
      display: none;
    }}

    .toolbar-status {{
      margin-top: 12px;
      font-size: 13px;
      color: var(--muted);
      line-height: 1.45;
    }}

    .toolbar-status.success {{
      color: var(--green);
    }}

    .toolbar-status.warning {{
      color: var(--amber);
    }}

    .stats-grid {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 10px;
    }}

    .overview-grid {{
      display: grid;
      grid-template-columns: minmax(0, 1.8fr) minmax(320px, 1fr);
      gap: 16px;
      margin-bottom: 18px;
    }}

    .stat-pill {{
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 14px 12px;
      background: #f8fbff;
      min-width: 0;
    }}

    .stat-pill strong {{
      display: block;
      font-size: 22px;
      line-height: 1.1;
      margin-bottom: 6px;
    }}

    .stat-pill span {{
      color: var(--muted);
      font-size: 13px;
    }}

    .distribution-meta {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: center;
      flex-wrap: wrap;
      margin-bottom: 10px;
      font-size: 13px;
      color: var(--muted);
    }}

    .distribution-chart {{
      border: 1px solid var(--border);
      border-radius: 10px;
      background:
        linear-gradient(180deg, #fcfdff 0%, #f6f9ff 100%);
      padding: 12px;
      min-height: 260px;
    }}

    .distribution-chart svg {{
      display: block;
      width: 100%;
      height: auto;
    }}

    .summary-table {{
      width: 100%;
      min-width: 0;
      border-collapse: collapse;
      border-spacing: 0;
      table-layout: fixed;
    }}

    .summary-table th,
    .summary-table td {{
      border: 1px solid var(--border);
      padding: 9px 10px;
      font-size: 13px;
      background: #fff;
      text-align: left;
      vertical-align: middle;
    }}

    .summary-table th {{
      width: 38%;
      background: #f8fbff;
      color: var(--muted);
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.25px;
    }}

    .summary-table td {{
      font-weight: 600;
      color: var(--text);
    }}

    .table-wrap {{
      overflow: auto;
      max-height: 75vh;
    }}

    table {{
      width: 100%;
      border-collapse: separate;
      border-spacing: 0;
      min-width: 1480px;
    }}

    th, td {{
      border-right: 1px solid var(--border);
      border-bottom: 1px solid var(--border);
      padding: 10px 12px;
      text-align: center;
      vertical-align: middle;
      font-size: 14px;
      background: #fff;
    }}

    tr td:first-child,
    tr th:first-child {{
      border-left: 1px solid var(--border);
    }}

    thead th {{
      background: #f2f6fb;
      font-weight: 700;
      position: sticky;
      top: 0;
      z-index: 5;
    }}

    .student-head,
    .student-col {{
      position: sticky;
      left: 0;
      z-index: 4;
      min-width: var(--student-col-width);
      max-width: var(--student-col-width);
      text-align: left;
    }}

    .score-head,
    .score-col {{
      position: sticky;
      left: var(--student-col-width);
      z-index: 4;
      min-width: var(--score-col-width);
      max-width: var(--score-col-width);
      background: #fff;
    }}

    thead .student-head,
    thead .score-head {{
      z-index: 6;
      background: #f2f6fb;
    }}

    .student-col {{
      white-space: normal;
      font-weight: 600;
      line-height: 1.4;
    }}

    .score-col {{
      font-weight: 700;
      white-space: nowrap;
    }}

    .score-col.adjusted {{
      background: #eff6ff;
    }}

    .score-main {{
      font-weight: 700;
    }}

    .score-sub {{
      margin-top: 4px;
      font-size: 12px;
      color: var(--muted);
      font-weight: 500;
    }}

    .question-head,
    .grade-cell {{
      min-width: var(--cell-width);
    }}

    .grade-cell {{
      font-weight: 700;
      cursor: pointer;
      user-select: none;
      transition: transform 0.12s ease, box-shadow 0.12s ease;
    }}

    .grade-cell:hover {{
      transform: translateY(-1px);
    }}

    .grade-cell.pass {{
      background: var(--green-bg);
      color: var(--green);
    }}

    .grade-cell.fail {{
      background: var(--red-bg);
      color: var(--red);
    }}

    .grade-cell.extra_column {{
      background: var(--olive-bg);
      color: var(--olive);
    }}

    .grade-cell.missing_column,
    .grade-cell.row_count_mismatch {{
      background: var(--amber-bg);
      color: var(--amber);
    }}

    .grade-cell.active {{
      outline: 3px solid var(--blue);
      outline-offset: -3px;
    }}

    .grade-cell.overridden {{
      box-shadow: inset 0 0 0 2px #60a5fa;
    }}

    .cell-main {{
      line-height: 1.15;
    }}

    .cell-meta {{
      margin-top: 6px;
      font-size: 12px;
      font-weight: 600;
      color: var(--blue-strong);
    }}

    .hidden {{
      display: none !important;
    }}

    .detail-panel,
    .adjustments-panel {{
      margin-top: 22px;
      padding: 18px;
    }}

    .detail-title {{
      margin: 0 0 10px 0;
      font-size: 24px;
    }}

    .detail-sub,
    .note {{
      color: var(--muted);
      font-size: 14px;
      line-height: 1.5;
    }}

    .detail-comments-wrap {{
      margin-top: 16px;
      margin-bottom: 2px;
    }}

    .detail-comments {{
      margin-bottom: 0;
      background: #f8fbff;
      border-color: #d6e4ff;
    }}

    .detail-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 18px;
      margin-top: 16px;
    }}

    .detail-col,
    .manual-panel {{
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 14px;
      background: #fff;
      min-width: 0;
    }}

    .detail-col h3,
    .manual-title,
    .adjustments-title {{
      margin-top: 0;
      margin-bottom: 10px;
      font-size: 18px;
    }}

    .detail-section-label {{
      font-size: 13px;
      font-weight: 700;
      color: var(--muted);
      margin-bottom: 6px;
      text-transform: uppercase;
      letter-spacing: 0.3px;
    }}

    pre {{
      margin: 0 0 14px 0;
      white-space: pre-wrap;
      word-break: break-word;
      background: #f8f9fa;
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 12px;
      overflow-x: auto;
      font-size: 13px;
      line-height: 1.45;
      max-height: 240px;
    }}

    .result-frame {{
      border: 1px solid var(--border);
      border-radius: 8px;
      overflow: auto;
      max-height: 320px;
      background: #fff;
    }}

    .result-table {{
      display: inline-table;
      width: max-content;
      max-width: none;
      min-width: 0;
      border-collapse: collapse;
      border-spacing: 0;
      background: #fff;
      font-size: 13px;
      table-layout: auto;
    }}

    .adjustments-table {{
      width: 100%;
      min-width: 0;
      border-collapse: collapse;
      background: #fff;
      font-size: 13px;
    }}

    .result-table th,
    .result-table td,
    .adjustments-table th,
    .adjustments-table td {{
      border: 1px solid var(--border);
      padding: 8px 10px;
      vertical-align: top;
      text-align: left;
    }}

    .result-table th {{
      position: static;
      top: auto;
      z-index: auto;
      background: #f8fbff;
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.25px;
      white-space: nowrap;
    }}

    .result-table td {{
      white-space: normal;
      word-break: normal;
    }}

    .result-cell {{
      display: inline-block;
      min-width: 0;
      max-width: 28ch;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      word-break: break-word;
      line-height: 1.4;
    }}

    .result-cell.numeric,
    .result-cell.nullish {{
      max-width: none;
      white-space: nowrap;
      overflow-wrap: normal;
      word-break: normal;
    }}

    .adjustments-table th {{
      background: #f8fbff;
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.3px;
    }}

    .rows-empty {{
      font-size: 13px;
      color: var(--muted);
      padding: 12px 0;
    }}

    .error-box {{
      color: var(--red);
      background: var(--red-bg);
      border: 1px solid #efc2c7;
      border-radius: 8px;
      padding: 10px 12px;
      font-size: 13px;
      white-space: pre-wrap;
      word-break: break-word;
    }}

    .status-line {{
      margin-bottom: 12px;
      font-weight: 700;
    }}

    .status-line.pass {{
      color: var(--green);
    }}

    .status-line.fail {{
      color: var(--red);
    }}

    .status-line.partial {{
      color: var(--amber);
    }}

    .manual-panel {{
      margin-top: 18px;
    }}

    .manual-copy,
    .adjustments-sub {{
      color: var(--muted);
      font-size: 13px;
      line-height: 1.5;
      margin-bottom: 12px;
    }}

    .manual-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 14px;
      margin-bottom: 12px;
    }}

    .field {{
      display: flex;
      flex-direction: column;
      gap: 6px;
      min-width: 0;
    }}

    .field.full {{
      margin-bottom: 12px;
    }}

    .field-label {{
      font-size: 13px;
      font-weight: 700;
      color: var(--muted);
    }}

    input[type="number"],
    input[readonly],
    textarea {{
      width: 100%;
      border: 1px solid #cbd5e1;
      border-radius: 8px;
      padding: 10px 12px;
      font: inherit;
      color: var(--text);
      background: #fff;
    }}

    input[readonly] {{
      background: #f8fafc;
    }}

    textarea {{
      resize: vertical;
      min-height: 88px;
    }}

    .adjustments-header {{
      display: flex;
      justify-content: space-between;
      gap: 14px;
      align-items: flex-start;
      margin-bottom: 12px;
      flex-wrap: wrap;
    }}

    .adjustments-actions button {{
      padding: 7px 10px;
      font-size: 12px;
    }}

    .note {{
      margin-top: 14px;
    }}

    @media (max-width: 1200px) {{
      .toolbar {{
        grid-template-columns: 1fr;
      }}

      .overview-grid {{
        grid-template-columns: 1fr;
      }}
    }}

    @media (max-width: 1000px) {{
      .detail-grid,
      .manual-grid,
      .stats-grid {{
        grid-template-columns: 1fr;
      }}
    }}

    @media (max-width: 760px) {{
      .page-wrap {{
        padding: 16px;
      }}

      .student-head,
      .student-col {{
        min-width: 180px;
        max-width: 180px;
      }}

      .score-head,
      .score-col {{
        left: 180px;
      }}
    }}
  </style>
</head>
<body>
  <div class="page-wrap">
    <h1>SQL Grader</h1>
    <div class="sub">
      Review the automatic result grid, click a cell for side-by-side SQL output, and use manual point overrides for failed or warning cells when you want to grant partial credit.
    </div>

    <div class="legend">
      <span class="legend-item"><span class="legend-box pass"></span> Pass</span>
      <span class="legend-item"><span class="legend-box fail"></span> Fail</span>
      <span class="legend-item"><span class="legend-box partial"></span> Warning mismatch</span>
      <span class="legend-item"><span class="legend-box manual"></span> Manual override</span>
      <span class="legend-item"><span class="legend-box selected"></span> Selected cell</span>
    </div>

    <div class="toolbar">
      <div class="toolbar-card">
        <div class="toolbar-title">Manual Corrections</div>
        <div class="toolbar-copy">
          Corrections are stored in <code>sessionStorage</code> for this browser tab. Export them as JSON to keep them, or load a saved corrections file back into a new session.
        </div>
        <div class="toolbar-actions">
          <button type="button" onclick="saveAdjustmentsToFile()">Save Corrections File</button>
          <label class="button-label secondary">
            Load Corrections File
            <input id="adjustments-file-input" type="file" accept=".json,application/json" onchange="loadAdjustmentsFromFile(event)">
          </label>
          <button type="button" class="secondary" onclick="resetSessionAdjustments()">Reset Session</button>
        </div>
        <div id="toolbar-status" class="toolbar-status">Loading corrections…</div>
      </div>

      <div class="toolbar-card">
        <div class="toolbar-title">Session Summary</div>
        <div class="stats-grid">
          <div class="stat-pill">
            <strong id="override-count">0</strong>
            <span>Overrides</span>
          </div>
          <div class="stat-pill">
            <strong id="adjusted-student-count">0</strong>
            <span>Students impacted</span>
          </div>
          <div class="stat-pill">
            <strong>{format_points_number(max_total_points)}</strong>
            <span>Max points</span>
          </div>
        </div>
      </div>
    </div>

    <div class="overview-grid">
      <div class="toolbar-card">
        <div class="toolbar-title">Grade Distribution</div>
        <div class="toolbar-copy">
          Histogram of current student totals as percentages of the full assignment. This updates when manual overrides change scores.
        </div>
        <div class="distribution-meta">
          <span id="distribution-range">Bins: 0-100%</span>
          <span id="distribution-count">0 students</span>
        </div>
        <div id="distribution-chart" class="distribution-chart"></div>
      </div>

      <div class="toolbar-card">
        <div class="toolbar-title">Grade Statistics</div>
        <div class="toolbar-copy">
          Summary values are based on the current session totals, including any manual corrections.
        </div>
        <table class="summary-table">
          <tbody>
            <tr><th>Max</th><td id="summary-max">-</td></tr>
            <tr><th>Min</th><td id="summary-min">-</td></tr>
            <tr><th>Average</th><td id="summary-average">-</td></tr>
            <tr><th>Median</th><td id="summary-median">-</td></tr>
            <tr><th>Q1</th><td id="summary-q1">-</td></tr>
            <tr><th>Q3</th><td id="summary-q3">-</td></tr>
            <tr><th>IQR</th><td id="summary-iqr">-</td></tr>
          </tbody>
        </table>
      </div>
    </div>

    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th class="student-head">Full Name</th>
            <th class="score-head">Score</th>
            {headers}
          </tr>
        </thead>
        <tbody>
          {''.join(rows)}
        </tbody>
      </table>
    </div>

    <div id="detail-panel" class="detail-panel hidden">
      <h2 id="detail-title" class="detail-title">Question detail</h2>
      <div id="detail-sub" class="detail-sub"></div>

      <div id="detail-comments-wrap" class="detail-comments-wrap hidden">
        <div class="detail-section-label">Question Comments</div>
        <pre id="detail-comments" class="detail-comments"></pre>
      </div>

      <div class="detail-grid">
        <div class="detail-col">
          <h3>Student Submission</h3>
          <div id="student-status" class="status-line"></div>

          <div class="detail-section-label">Query</div>
          <pre id="student-sql"></pre>

          <div class="detail-section-label">Result</div>
          <div id="student-result" class="result-frame"></div>
        </div>

        <div class="detail-col">
          <h3>Reference Answer</h3>
          <div id="answer-status" class="status-line"></div>

          <div class="detail-section-label">Query</div>
          <pre id="answer-sql"></pre>

          <div class="detail-section-label">Result</div>
          <div id="answer-result" class="result-frame"></div>
        </div>
      </div>

      <div id="manual-panel" class="manual-panel hidden">
        <h3 class="manual-title">Manual Score Adjustment</h3>
        <div class="manual-copy">
          Set manual points for failed or warning results. The automatic score stays visible so you can compare what changed.
        </div>

        <div class="manual-grid">
          <label class="field">
            <span class="field-label">Automatic score</span>
            <input id="manual-auto-points" type="text" readonly>
          </label>

          <label class="field">
            <span class="field-label">Manual score</span>
            <input id="manual-points" type="number" min="0" max="{format_points_number(question_points)}" step="0.5">
          </label>
        </div>

        <label class="field full">
          <span class="field-label">Reason</span>
          <textarea id="manual-note" placeholder="Why this answer should receive manual credit"></textarea>
        </label>

        <div class="toolbar-actions">
          <button type="button" onclick="applyManualOverride()">Apply Manual Score</button>
          <button type="button" class="secondary" onclick="clearManualOverride()">Clear Override</button>
        </div>
        <div id="manual-feedback" class="toolbar-status"></div>
      </div>
    </div>

    <div class="adjustments-panel">
      <div class="adjustments-header">
        <div>
          <h2 class="adjustments-title">Manual Corrections Log</h2>
          <div class="adjustments-sub">
            Saved corrections use the filename <code>{html_escape(adjustments_filename)}</code>. If that file is present beside this report, the page will try to load it on first open before falling back to the embedded defaults.
          </div>
        </div>
      </div>

      <div id="adjustments-empty" class="rows-empty">No manual corrections in this session yet.</div>
      <table id="adjustments-table" class="adjustments-table hidden">
        <thead>
          <tr>
            <th>Student</th>
            <th>Question</th>
            <th>Status</th>
            <th>Manual score</th>
            <th>Reason</th>
            <th>Updated</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody id="adjustments-body"></tbody>
      </table>
    </div>

    <div class="note">
      Automatic grading awards {format_points_number(question_points)} points for each pass and extra-column result, for a maximum of {format_points_number(max_total_points)} points.
    </div>
  </div>

  <script>
    const DETAIL_DATA = {json.dumps(detail_data, ensure_ascii=False)};
    const QUESTION_POINTS = {json.dumps(question_points)};
    const MAX_TOTAL_POINTS = {json.dumps(max_total_points)};
    const ADJUSTMENTS_FILENAME = {json.dumps(adjustments_filename)};
    const STORAGE_KEY = "sql-grader-adjustments-v1";
    const EMBEDDED_ADJUSTMENTS = {json.dumps(adjustments, ensure_ascii=False)};

    let adjustmentsState = createEmptyAdjustments();
    let currentSelection = null;

    function escapeHtml(value) {{
      return String(value)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
    }}

    function createEmptyAdjustments() {{
      return {{
        version: {ADJUSTMENTS_VERSION},
        question_points: QUESTION_POINTS,
        overrides: {{}}
      }};
    }}

    function formatPoints(value) {{
      const rounded = Math.round(Number(value) * 100) / 100;
      if (Number.isInteger(rounded)) {{
        return String(rounded);
      }}
      return rounded.toFixed(2).replace(/0+$/, "").replace(/\\.$/, "");
    }}

    function normalizePoints(value) {{
      const numberValue = Number(value);
      if (!Number.isFinite(numberValue)) {{
        return null;
      }}
      return Math.min(QUESTION_POINTS, Math.max(0, numberValue));
    }}

    function overrideKey(studentSlug, questionNumber) {{
      return studentSlug + "::" + String(questionNumber);
    }}

    function normalizeAdjustmentsPayload(payload) {{
      const normalized = createEmptyAdjustments();
      if (!payload || typeof payload !== "object") {{
        return normalized;
      }}

      const rawOverrides = payload.overrides && typeof payload.overrides === "object"
        ? payload.overrides
        : {{}};

      const cleanedOverrides = {{}};
      for (const rawOverride of Object.values(rawOverrides)) {{
        if (!rawOverride || typeof rawOverride !== "object") {{
          continue;
        }}

        const studentSlug = String(rawOverride.student_slug || "").trim();
        const questionNumber = Number(rawOverride.question_number);
        const points = normalizePoints(rawOverride.points);

        if (!studentSlug || !Number.isInteger(questionNumber) || points === null) {{
          continue;
        }}

        cleanedOverrides[overrideKey(studentSlug, questionNumber)] = {{
          student_slug: studentSlug,
          student_name: String(rawOverride.student_name || "").trim(),
          question_number: questionNumber,
          points: points,
          note: String(rawOverride.note || "").trim(),
          status: String(rawOverride.status || "").trim(),
          updated_at: String(rawOverride.updated_at || "").trim()
        }};
      }}

      normalized.overrides = cleanedOverrides;
      return normalized;
    }}

    function getOverride(studentSlug, questionNumber) {{
      return adjustmentsState.overrides[overrideKey(studentSlug, questionNumber)] || null;
    }}

    function persistAdjustmentsToSession() {{
      try {{
        sessionStorage.setItem(STORAGE_KEY, JSON.stringify(adjustmentsState));
      }} catch (error) {{
        console.warn("Could not persist session adjustments:", error);
      }}
    }}

    function readAdjustmentsFromSession() {{
      try {{
        const raw = sessionStorage.getItem(STORAGE_KEY);
        return raw ? normalizeAdjustmentsPayload(JSON.parse(raw)) : null;
      }} catch (error) {{
        console.warn("Could not read session adjustments:", error);
        return null;
      }}
    }}

    async function fetchAdjustmentsFromFile() {{
      try {{
        const response = await fetch(ADJUSTMENTS_FILENAME + "?ts=" + Date.now(), {{
          cache: "no-store"
        }});
        if (!response.ok) {{
          return null;
        }}
        const payload = await response.json();
        return normalizeAdjustmentsPayload(payload);
      }} catch (error) {{
        return null;
      }}
    }}

    function setToolbarStatus(message, tone) {{
      const node = document.getElementById("toolbar-status");
      node.textContent = message;
      node.className = "toolbar-status" + (tone ? " " + tone : "");
    }}

    function setManualFeedback(message, tone) {{
      const node = document.getElementById("manual-feedback");
      node.textContent = message;
      node.className = "toolbar-status" + (tone ? " " + tone : "");
    }}

    function getAutoPoints(question) {{
      return question.status === "pass" || question.status === "extra_column"
        ? QUESTION_POINTS
        : 0;
    }}

    function getEffectivePoints(student, question) {{
      const override = getOverride(student.student_slug, question.question_number);
      return override ? override.points : getAutoPoints(question);
    }}

    function getStudentTotal(student) {{
      return student.questions.reduce(function(total, question) {{
        return total + getEffectivePoints(student, question);
      }}, 0);
    }}

    function getCurrentTotals() {{
      return DETAIL_DATA.map(function(student) {{
        return getStudentTotal(student);
      }});
    }}

    function formatScoreValue(value) {{
      const percent = MAX_TOTAL_POINTS > 0 ? (Number(value) / MAX_TOTAL_POINTS) * 100 : 0;
      return formatPoints(value) + "/" + formatPoints(MAX_TOTAL_POINTS) + " (" + formatPoints(percent) + "%)";
    }}

    function quantile(sortedValues, percentile) {{
      if (!sortedValues.length) {{
        return 0;
      }}
      if (sortedValues.length === 1) {{
        return sortedValues[0];
      }}

      const index = (sortedValues.length - 1) * percentile;
      const lower = Math.floor(index);
      const upper = Math.ceil(index);
      const weight = index - lower;

      if (lower === upper) {{
        return sortedValues[lower];
      }}

      return sortedValues[lower] + ((sortedValues[upper] - sortedValues[lower]) * weight);
    }}

    function computeGradeSummary(scores) {{
      if (!scores.length) {{
        return null;
      }}

      const sorted = scores.slice().sort(function(a, b) {{
        return a - b;
      }});
      const sum = sorted.reduce(function(total, value) {{
        return total + value;
      }}, 0);
      const q1 = quantile(sorted, 0.25);
      const q3 = quantile(sorted, 0.75);

      return {{
        count: sorted.length,
        min: sorted[0],
        max: sorted[sorted.length - 1],
        average: sum / sorted.length,
        median: quantile(sorted, 0.5),
        q1: q1,
        q3: q3,
        iqr: q3 - q1
      }};
    }}

    function buildDistributionBins(scores) {{
      const bins = Array.from({{ length: 10 }}, function(_, index) {{
        const start = index * 10;
        const end = index === 9 ? 100 : start + 10;
        return {{
          start: start,
          end: end,
          label: index === 9 ? "90-100%" : String(start) + "-" + String(end - 1) + "%",
          count: 0
        }};
      }});

      scores.forEach(function(score) {{
        const percent = MAX_TOTAL_POINTS > 0 ? (score / MAX_TOTAL_POINTS) * 100 : 0;
        let index = Math.floor(percent / 10);
        if (percent >= 100) {{
          index = 9;
        }}
        index = Math.max(0, Math.min(9, index));
        bins[index].count += 1;
      }});

      return bins;
    }}

    function renderDistributionChart(scores) {{
      const container = document.getElementById("distribution-chart");
      const countNode = document.getElementById("distribution-count");

      if (!scores.length) {{
        countNode.textContent = "0 students";
        container.innerHTML = '<div class="rows-empty">No student scores available.</div>';
        return;
      }}

      const bins = buildDistributionBins(scores);
      const maxCount = Math.max.apply(null, bins.map(function(bin) {{
        return bin.count;
      }}));
      const width = 680;
      const height = 240;
      const paddingLeft = 24;
      const paddingRight = 8;
      const paddingTop = 18;
      const paddingBottom = 52;
      const chartWidth = width - paddingLeft - paddingRight;
      const chartHeight = height - paddingTop - paddingBottom;
      const gap = 10;
      const barWidth = (chartWidth - (gap * (bins.length - 1))) / bins.length;

      const bars = bins.map(function(bin, index) {{
        const barHeight = maxCount > 0 ? (bin.count / maxCount) * chartHeight : 0;
        const x = paddingLeft + (index * (barWidth + gap));
        const y = paddingTop + (chartHeight - barHeight);
        const countY = y - 6;
        const labelX = x + (barWidth / 2);

        return (
          '<g>' +
            '<rect x="' + x.toFixed(2) + '" y="' + y.toFixed(2) + '" width="' + barWidth.toFixed(2) + '" height="' + barHeight.toFixed(2) + '" rx="8" fill="#0d6efd" fill-opacity="0.82"></rect>' +
            '<text x="' + labelX.toFixed(2) + '" y="' + countY.toFixed(2) + '" text-anchor="middle" font-size="12" fill="#5c6770">' + String(bin.count) + '</text>' +
            '<text x="' + labelX.toFixed(2) + '" y="' + (height - 18) + '" text-anchor="middle" font-size="11" fill="#5c6770">' + escapeHtml(bin.label) + '</text>' +
          '</g>'
        );
      }}).join("");

      const gridLines = [0, 0.5, 1].map(function(step) {{
        const y = paddingTop + (chartHeight - (chartHeight * step));
        return '<line x1="' + paddingLeft + '" y1="' + y.toFixed(2) + '" x2="' + (width - paddingRight) + '" y2="' + y.toFixed(2) + '" stroke="#d9dde3" stroke-dasharray="4 6"></line>';
      }}).join("");

      countNode.textContent = String(scores.length) + (scores.length === 1 ? " student" : " students");
      container.innerHTML =
        '<svg viewBox="0 0 ' + width + " " + height + '" role="img" aria-label="Grade distribution histogram">' +
          gridLines +
          '<line x1="' + paddingLeft + '" y1="' + (paddingTop + chartHeight) + '" x2="' + (width - paddingRight) + '" y2="' + (paddingTop + chartHeight) + '" stroke="#9aa4af"></line>' +
          bars +
        '</svg>';
    }}

    function renderGradeSummary() {{
      const totals = getCurrentTotals();
      const summary = computeGradeSummary(totals);

      if (!summary) {{
        ["max", "min", "average", "median", "q1", "q3", "iqr"].forEach(function(key) {{
          document.getElementById("summary-" + key).textContent = "-";
        }});
        renderDistributionChart([]);
        return;
      }}

      document.getElementById("summary-max").textContent = formatScoreValue(summary.max);
      document.getElementById("summary-min").textContent = formatScoreValue(summary.min);
      document.getElementById("summary-average").textContent = formatScoreValue(summary.average);
      document.getElementById("summary-median").textContent = formatScoreValue(summary.median);
      document.getElementById("summary-q1").textContent = formatScoreValue(summary.q1);
      document.getElementById("summary-q3").textContent = formatScoreValue(summary.q3);
      document.getElementById("summary-iqr").textContent =
        formatPoints(summary.iqr) + "/" + formatPoints(MAX_TOTAL_POINTS) + " (" +
        formatPoints(MAX_TOTAL_POINTS > 0 ? (summary.iqr / MAX_TOTAL_POINTS) * 100 : 0) +
        "%)";

      renderDistributionChart(totals);
    }}

    function resultCellClass(rendered) {{
      if (rendered === "NULL") {{
        return "result-cell nullish";
      }}
      if (/^-?\\d+(?:\\.\\d+)?$/.test(rendered)) {{
        return "result-cell numeric";
      }}
      return "result-cell";
    }}

    function rowsToTable(columns, rows) {{
      if (!rows || rows.length === 0) {{
        return '<div class="rows-empty">No rows returned.</div>';
      }}

      let header = "";
      if (columns && columns.length) {{
        header =
          "<thead><tr>" +
          columns.map(function(columnName) {{
            return "<th>" + escapeHtml(String(columnName)) + "</th>";
          }}).join("") +
          "</tr></thead>";
      }}

      let body = "";
      for (const row of rows) {{
        let cells = "";
        for (const cell of row) {{
          const rendered = cell === null ? "NULL" : String(cell);
          cells += (
            "<td><div class='" + resultCellClass(rendered) + "'>" +
            escapeHtml(rendered) +
            "</div></td>"
          );
        }}
        body += "<tr>" + cells + "</tr>";
      }}

      return '<table class="result-table">' + header + "<tbody>" + body + "</tbody></table>";
    }}

    function showExecutionResult(execOk, errorMsg, columns, rows) {{
      if (!execOk) {{
        return '<div class="error-box">' + escapeHtml(errorMsg || "Execution failed.") + "</div>";
      }}
      return rowsToTable(columns, rows);
    }}

    function clearActiveCells() {{
      document.querySelectorAll(".grade-cell.active").forEach(function(cell) {{
        cell.classList.remove("active");
      }});
    }}

    function statusDisplayText(status) {{
      if (status === "pass") return "Overall result: PASS";
      if (status === "extra_column") return "Overall result: EXTRA COLUMN";
      if (status === "missing_column") return "Overall result: MISSING COLUMN";
      if (status === "row_count_mismatch") return "Overall result: ROW COUNT MISMATCH";
      return "Overall result: FAIL";
    }}

    function updateSummaryCards() {{
      const overrides = Object.values(adjustmentsState.overrides);
      const studentCount = new Set(overrides.map(function(item) {{
        return item.student_slug;
      }})).size;

      document.getElementById("override-count").textContent = String(overrides.length);
      document.getElementById("adjusted-student-count").textContent = String(studentCount);
    }}

    function renderScoreboard() {{
      DETAIL_DATA.forEach(function(student, studentIndex) {{
        let autoTotal = 0;
        let adjustedTotal = 0;

        student.questions.forEach(function(question) {{
          autoTotal += getAutoPoints(question);
          adjustedTotal += getEffectivePoints(student, question);
        }});

        const scoreCell = document.getElementById("score-cell-" + String(studentIndex));
        if (scoreCell) {{
          scoreCell.classList.toggle("adjusted", adjustedTotal !== autoTotal);
          if (adjustedTotal !== autoTotal) {{
            scoreCell.innerHTML =
              '<div class="score-main">' + formatPoints(adjustedTotal) + "/" + formatPoints(MAX_TOTAL_POINTS) + "</div>" +
              '<div class="score-sub">Auto ' + formatPoints(autoTotal) + "</div>";
          }} else {{
            scoreCell.textContent = formatPoints(adjustedTotal) + "/" + formatPoints(MAX_TOTAL_POINTS);
          }}
        }}

        student.questions.forEach(function(question) {{
          const selector =
            '.grade-cell[data-student-index="' + String(studentIndex) + '"][data-question-number="' + String(question.question_number) + '"]';
          const cell = document.querySelector(selector);
          if (!cell) {{
            return;
          }}

          const meta = cell.querySelector(".cell-meta");
          const override = getOverride(student.student_slug, question.question_number);

          if (override) {{
            cell.classList.add("overridden");
            meta.textContent = formatPoints(override.points) + "/" + formatPoints(QUESTION_POINTS);
            meta.classList.remove("hidden");
          }} else {{
            cell.classList.remove("overridden");
            meta.textContent = "";
            meta.classList.add("hidden");
          }}
        }});
      }});

      updateSummaryCards();
    }}

    function findStudentIndex(studentSlug) {{
      return DETAIL_DATA.findIndex(function(student) {{
        return student.student_slug === studentSlug;
      }});
    }}

    function renderAdjustmentsTable() {{
      const body = document.getElementById("adjustments-body");
      const table = document.getElementById("adjustments-table");
      const empty = document.getElementById("adjustments-empty");
      const overrides = Object.values(adjustmentsState.overrides).sort(function(a, b) {{
        if (a.student_name === b.student_name) {{
          return a.question_number - b.question_number;
        }}
        return a.student_name.localeCompare(b.student_name);
      }});

      if (overrides.length === 0) {{
        body.innerHTML = "";
        table.classList.add("hidden");
        empty.classList.remove("hidden");
        return;
      }}

      empty.classList.add("hidden");
      table.classList.remove("hidden");

      body.innerHTML = overrides.map(function(override) {{
        const reason = override.note ? escapeHtml(override.note) : '<span class="rows-empty">No note</span>';
        const updated = override.updated_at ? escapeHtml(override.updated_at) : "This session";
        const focusSlugArg = JSON.stringify(override.student_slug);
        const removeKeyArg = JSON.stringify(overrideKey(override.student_slug, override.question_number));
        return (
          "<tr>" +
            "<td>" + escapeHtml(override.student_name || override.student_slug) + "</td>" +
            "<td>Q" + escapeHtml(String(override.question_number)) + "</td>" +
            "<td>" + escapeHtml(statusDisplayText(override.status).replace("Overall result: ", "")) + "</td>" +
            "<td>" + escapeHtml(formatPoints(override.points)) + "/" + escapeHtml(formatPoints(QUESTION_POINTS)) + "</td>" +
            "<td>" + reason + "</td>" +
            "<td>" + updated + "</td>" +
            '<td class="adjustments-actions">' +
              `<button type="button" class="secondary" onclick='focusOverride(${{focusSlugArg}},${{String(override.question_number)}})'>View</button> ` +
              `<button type="button" class="secondary" onclick='clearOverrideByKey(${{removeKeyArg}})'>Remove</button>` +
            "</td>" +
          "</tr>"
        );
      }}).join("");
    }}

    function focusOverride(studentSlug, questionNumber) {{
      const studentIndex = findStudentIndex(studentSlug);
      if (studentIndex === -1) {{
        return;
      }}
      showDetail(studentIndex, questionNumber);
    }}

    function clearOverrideByKey(key) {{
      if (!adjustmentsState.overrides[key]) {{
        return;
      }}
      delete adjustmentsState.overrides[key];
      persistAdjustmentsToSession();
      renderAll(true);
      setToolbarStatus("Removed a manual correction from the current session.", "success");
    }}

    function renderManualPanel(student, question) {{
      const panel = document.getElementById("manual-panel");
      const override = getOverride(student.student_slug, question.question_number);
      const eligible = question.status !== "pass" || Boolean(override);

      if (!eligible) {{
        panel.classList.add("hidden");
        setManualFeedback("", "");
        return;
      }}

      panel.classList.remove("hidden");
      document.getElementById("manual-auto-points").value =
        formatPoints(getAutoPoints(question)) + "/" + formatPoints(QUESTION_POINTS);
      document.getElementById("manual-points").value =
        formatPoints(override ? override.points : getAutoPoints(question));
      document.getElementById("manual-note").value = override ? override.note : "";

      if (override) {{
        setManualFeedback("Manual override currently active for this result.", "success");
      }} else {{
        setManualFeedback("No manual override yet for this result.", "");
      }}
    }}

    function renderAll(preserveSelection) {{
      renderScoreboard();
      renderGradeSummary();
      renderAdjustmentsTable();

      if (preserveSelection && currentSelection) {{
        showDetail(currentSelection.studentIndex, currentSelection.questionNumber, true);
      }}
    }}

    function showDetail(studentIndex, questionNumber, preserveScroll) {{
      const student = DETAIL_DATA[studentIndex];
      if (!student) {{
        return;
      }}

      const question = student.questions.find(function(item) {{
        return item.question_number === questionNumber;
      }});
      if (!question) {{
        return;
      }}

      currentSelection = {{
        studentIndex: studentIndex,
        questionNumber: questionNumber
      }};

      clearActiveCells();

      const clicked = document.querySelector(
        '.grade-cell[data-student-index="' + String(studentIndex) + '"][data-question-number="' + String(questionNumber) + '"]'
      );
      if (clicked) {{
        clicked.classList.add("active");
      }}

      const override = getOverride(student.student_slug, questionNumber);
      const detailCommentsWrap = document.getElementById("detail-comments-wrap");
      const detailComments = document.getElementById("detail-comments");

      document.getElementById("detail-title").textContent =
        student.student_name + " — Question " + String(questionNumber);
      document.getElementById("detail-sub").textContent = override
        ? statusDisplayText(question.status) + " · Manual score " + formatPoints(override.points) + "/" + formatPoints(QUESTION_POINTS)
        : statusDisplayText(question.status);

      if (question.question_comments) {{
        detailComments.textContent = question.question_comments;
        detailCommentsWrap.classList.remove("hidden");
      }} else {{
        detailComments.textContent = "";
        detailCommentsWrap.classList.add("hidden");
      }}

      const studentStatus = document.getElementById("student-status");
      studentStatus.textContent = question.student_exec_ok
        ? "Student query executed successfully"
        : "Student query execution failed";
      studentStatus.className = "status-line " + (question.student_exec_ok ? "pass" : "fail");

      const answerStatus = document.getElementById("answer-status");
      answerStatus.textContent = question.answer_exec_ok
        ? "Reference query executed successfully"
        : "Reference query execution failed";
      answerStatus.className = "status-line " + (question.answer_exec_ok ? "pass" : "fail");

      document.getElementById("student-sql").textContent = question.student_sql_display || question.student_sql || "";
      document.getElementById("answer-sql").textContent = question.answer_sql_display || question.answer_sql || "";
      document.getElementById("student-result").innerHTML =
        showExecutionResult(
          question.student_exec_ok,
          question.student_error,
          question.student_columns,
          question.student_rows
        );
      document.getElementById("answer-result").innerHTML =
        showExecutionResult(
          question.answer_exec_ok,
          question.answer_error,
          question.answer_columns,
          question.answer_rows
        );

      renderManualPanel(student, question);

      const detailPanel = document.getElementById("detail-panel");
      detailPanel.classList.remove("hidden");

      if (!preserveScroll) {{
        detailPanel.scrollIntoView({{ behavior: "smooth", block: "start" }});
      }}
    }}

    function applyManualOverride() {{
      if (!currentSelection) {{
        return;
      }}

      const student = DETAIL_DATA[currentSelection.studentIndex];
      const question = student.questions.find(function(item) {{
        return item.question_number === currentSelection.questionNumber;
      }});

      if (!question) {{
        return;
      }}

      const manualPoints = normalizePoints(document.getElementById("manual-points").value);
      if (manualPoints === null) {{
        setManualFeedback("Enter a valid number between 0 and " + formatPoints(QUESTION_POINTS) + ".", "warning");
        return;
      }}

      const override = {{
        student_slug: student.student_slug,
        student_name: student.student_name,
        question_number: question.question_number,
        points: manualPoints,
        note: document.getElementById("manual-note").value.trim(),
        status: question.status,
        updated_at: new Date().toISOString()
      }};

      adjustmentsState.overrides[overrideKey(student.student_slug, question.question_number)] = override;
      persistAdjustmentsToSession();
      renderAll(true);
      setToolbarStatus(
        "Saved a manual correction for " + student.student_name + " question " + String(question.question_number) + ".",
        "success"
      );
      setManualFeedback("Manual override saved in this session.", "success");
    }}

    function clearManualOverride() {{
      if (!currentSelection) {{
        return;
      }}

      const student = DETAIL_DATA[currentSelection.studentIndex];
      const key = overrideKey(student.student_slug, currentSelection.questionNumber);
      if (!adjustmentsState.overrides[key]) {{
        setManualFeedback("No manual override is set for this result.", "");
        return;
      }}

      delete adjustmentsState.overrides[key];
      persistAdjustmentsToSession();
      renderAll(true);
      setToolbarStatus(
        "Cleared the manual correction for " + student.student_name + " question " + String(currentSelection.questionNumber) + ".",
        "success"
      );
      setManualFeedback("Manual override removed from this session.", "success");
    }}

    function buildExportPayload() {{
      return {{
        version: {ADJUSTMENTS_VERSION},
        question_points: QUESTION_POINTS,
        overrides: adjustmentsState.overrides
      }};
    }}

    function downloadTextFile(filename, text) {{
      const blob = new Blob([text], {{ type: "application/json" }});
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
    }}

    async function saveAdjustmentsToFile() {{
      const payloadText = JSON.stringify(buildExportPayload(), null, 2);

      if (window.showSaveFilePicker) {{
        try {{
          const handle = await window.showSaveFilePicker({{
            suggestedName: ADJUSTMENTS_FILENAME,
            types: [{{
              description: "JSON files",
              accept: {{ "application/json": [".json"] }}
            }}]
          }});
          const writable = await handle.createWritable();
          await writable.write(payloadText);
          await writable.close();
          setToolbarStatus(
            "Saved manual corrections to " + (handle.name || ADJUSTMENTS_FILENAME) + ".",
            "success"
          );
          return;
        }} catch (error) {{
          if (error && error.name === "AbortError") {{
            return;
          }}
        }}
      }}

      downloadTextFile(ADJUSTMENTS_FILENAME, payloadText);
      setToolbarStatus(
        "Downloaded " + ADJUSTMENTS_FILENAME + ". Keep it beside the report to reuse it later.",
        "success"
      );
    }}

    async function loadAdjustmentsFromFile(event) {{
      const file = event.target.files && event.target.files[0];
      if (!file) {{
        return;
      }}

      try {{
        const text = await file.text();
        adjustmentsState = normalizeAdjustmentsPayload(JSON.parse(text));
        persistAdjustmentsToSession();
        renderAll(true);
        setToolbarStatus("Loaded manual corrections from " + file.name + ".", "success");
      }} catch (error) {{
        setToolbarStatus("Could not load " + file.name + ". Make sure it is valid JSON.", "warning");
      }} finally {{
        event.target.value = "";
      }}
    }}

    function resetSessionAdjustments() {{
      if (!window.confirm("Clear all manual corrections from this browser session?")) {{
        return;
      }}

      adjustmentsState = createEmptyAdjustments();
      persistAdjustmentsToSession();
      renderAll(true);
      setToolbarStatus("Cleared all manual corrections from this session.", "success");
    }}

    async function initializePage() {{
      const sessionAdjustments = readAdjustmentsFromSession();
      if (sessionAdjustments) {{
        adjustmentsState = sessionAdjustments;
        setToolbarStatus("Loaded manual corrections from this browser session.", "success");
        renderAll(false);
        return;
      }}

      const fileAdjustments = await fetchAdjustmentsFromFile();
      if (fileAdjustments && Object.keys(fileAdjustments.overrides).length > 0) {{
        adjustmentsState = fileAdjustments;
        setToolbarStatus("Loaded manual corrections from " + ADJUSTMENTS_FILENAME + ".", "success");
      }} else {{
        adjustmentsState = normalizeAdjustmentsPayload(EMBEDDED_ADJUSTMENTS);
        if (Object.keys(adjustmentsState.overrides).length > 0) {{
          setToolbarStatus("Loaded embedded manual corrections into this session.", "success");
        }} else {{
          setToolbarStatus("No saved manual corrections found yet.", "");
        }}
      }}

      persistAdjustmentsToSession();
      renderAll(false);
    }}

    document.addEventListener("DOMContentLoaded", function() {{
      initializePage();
    }});
  </script>
</body>
</html>
"""


def write_report_bundle(
    results: List[Dict[str, Any]],
    total_questions: int,
    output_dir: Path,
    question_points: float = QUESTION_POINTS,
    adjustments_filename: str = ADJUSTMENTS_FILENAME,
) -> None:
    """Write every report artifact needed by the grader viewer.

    Parameters:
        results: Raw grading results returned by the grading module.
        total_questions: Number of questions to include in the report layout.
        output_dir: Folder where HTML, JSON, CSV, and adjustments files belong.
        question_points: Maximum points per question used for score summaries.
        adjustments_filename: Name of the JSON file used for manual overrides.

    Returns:
        None. This function creates the output directory when needed and writes
        the rendered report bundle to disk.
    """
    ensure_dir(output_dir)
    prepared_results = prepare_results_for_rendering(results)

    adjustments_path = output_dir / adjustments_filename
    adjustments = load_adjustments(adjustments_path)

    write_csv(prepared_results, output_dir / "results.csv")
    (output_dir / "results.json").write_text(
        json.dumps(prepared_results, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

    if not adjustments_path.exists():
        write_adjustments_file(adjustments_path, adjustments)

    index_html = build_index_html(
        results=prepared_results,
        total_questions=total_questions,
        adjustments=adjustments,
        question_points=question_points,
        adjustments_filename=adjustments_filename,
    )
    (output_dir / "index.html").write_text(index_html, encoding="utf-8")
