<a name="top"></a>

[![Binghamton University](https://img.shields.io/badge/Binghamton_University-Coding_in_SQL-005A43)](https://www.binghamton.edu/apps/calendar/event/details/be-2267627)
[![Sponsor](https://img.shields.io/badge/sponsored_by-Harpur_Edge-1D4F91)](https://www.binghamton.edu/apps/calendar/event/details/be-2267627)
[![language](https://img.shields.io/badge/language-Python-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![database](https://img.shields.io/badge/database-SQLite-003B57?logo=sqlite&logoColor=white)](https://www.sqlite.org/)
[![OS](https://img.shields.io/badge/OS-linux%2C%20windows%2C%20macOS-0078D4)](#-quick-start)
[![outputs](https://img.shields.io/badge/output-HTML%20%7C%20CSV%20%7C%20JSON-6f42c1)](#-outputs)
[![viewer](https://img.shields.io/badge/viewer-manual_review%20%2B%20analytics-brightgreen)](#-features)
[![course level](https://img.shields.io/badge/level-foundational-orange)](https://www.credly.com/org/binghamton-university/badge/coding-in-sql)
[![cost](https://img.shields.io/badge/course-free-success)](https://www.credly.com/org/binghamton-university/badge/coding-in-sql)

# SQL Grader

Interactive grading and review tooling for **Binghamton University's Coding in SQL** course and crash-course style assessments.

This project automatically runs student SQL against a reference answer key, compares outputs, generates an interactive HTML review report, and supports instructor-side manual score adjustments with saved correction files.


## Table of Contents
- [About](#-about)
- [Course Context](#-course-context)
- [Official Binghamton Links](#-official-binghamton-links)
- [Features](#-features)
- [How It Works](#-how-it-works)
- [Repository Structure](#-repository-structure)
- [Quick Start](#-quick-start)
- [Outputs](#-outputs)
- [Grading Rules](#-grading-rules)
- [Manual Review Workflow](#-manual-review-workflow)
- [Sources](#-sources)
- [License](#-license)

## 🚀 About

**SQL Grader** is a Python-based grading pipeline built for introductory SQL instruction. It is especially well suited for workshop, bootcamp, and classroom settings where students submit one SQL response per question and instructors need:

- automatic execution against a shared SQLite database
- answer-key comparison by result set rather than string matching
- a side-by-side HTML review experience for student and reference queries
- manual score overrides for edge cases and partial credit
- exportable grading artifacts for archival or follow-up

The generated report includes:

- an interactive grading grid
- side-by-side query/result comparison
- question comments pulled from the answer file
- session-based manual score corrections
- import/export of saved correction files
- grade distribution visualization
- summary statistics including min, max, average, median, quartiles, and IQR

## 🎓 Course Context

This grader is designed around **Coding in SQL**, a Binghamton University offering described publicly as:

- a **foundational** SQL learning experience
- an **ideal first step into data analytics**
- a course where **no prior programming or statistics experience is expected**
- a workshop that teaches students how databases store and retrieve large amounts of information efficiently
- a learning experience focused on writing SQL to **manipulate and summarize data**

Public course and badge descriptions also indicate that students work on topics such as:

- filtering
- aggregate functions
- grouping
- sorting
- joins
- basic database design
- creating and organizing databases

The Credly badge page further notes that learners earn the credential by passing the assessment with **70% or better**.

## 🔗 Official Binghamton Links

- Harpur Edge crash course page: [Harpur Edge Crash Courses](https://www.binghamton.edu/harpur/edge/professional/crash-course.html)
- Binghamton course catalog page: [DIDA 110 / Database Fundamentals (SQL)](https://catalog.binghamton.edu/preview_course_nopop.php?catoid=2&coid=31566)
- DIDA page: [Data Science and Analytics | Digital and Data Studies](https://www.binghamton.edu/academics/programs/digital-and-data-studies/professional/data-science-analytics.html)

## ✨ Features

- **Automatic SQL grading**: Executes student and reference SQL against the same SQLite database.
- **Result-based comparison**: Grades based on returned rows instead of exact query text.
- **Mismatch classification**: Distinguishes between `pass`, `fail`, `missing_column`, `extra_column`, and `row_count_mismatch`.
- **Interactive HTML review report**: Lets instructors inspect each answer in a click-through grid.
- **Formatted SQL display**: Renders both student and answer queries in a readable multiline format.
- **Question prompt comments**: Pulls pre-query comments from `answers.sql` into the viewer.
- **Manual score adjustments**: Supports override points and notes for failed or warning results.
- **Saved corrections**: Uses browser session state plus JSON import/export for persistent review workflows.
- **Grade analytics**: Includes a live grade distribution chart and summary statistics table.
- **Cross-platform runners**: Includes both `run.sh` and `run.bat`.

## 🧠 How It Works

The grading flow is intentionally split into three Python modules:

- [`main.py`](./main.py): CLI entrypoint that validates inputs and coordinates the full run.
- [`grader.py`](./grader.py): grading logic, SQL parsing, execution, comparison, and result construction.
- [`renderer.py`](./renderer.py): report generation, HTML viewer rendering, CSV/JSON exports, and manual adjustment support.

At a high level:

1. The CLI receives paths to the database, answer key, submissions CSV, and output directory.
2. The answer key is split into numbered question sections.
3. Student responses are read from the CSV and matched to numbered question columns.
4. Each student answer is executed against the SQLite database.
5. The returned result set is compared to the reference result set.
6. Per-question and per-student results are assembled.
7. A report bundle is written to disk, including the interactive viewer.

## 🗂 Repository Structure

```text
.
├── main.py               # main CLI entrypoint
├── grader.py             # grading and comparison logic
├── renderer.py           # HTML/CSV/JSON report generation
├── run.sh                # macOS/Linux convenience runner
├── run.bat               # Windows convenience runner
├── course.db             # SQLite grading database
├── answers.sql           # reference answers (gitignored)
├── submissions.csv       # student submissions (gitignored)
└── grading_output/       # generated report bundle
```

> [!IMPORTANT]
> `answers.sql` and `submissions.csv` are intentionally left out of this repo.
 That keeps answer keys and student work out of Git history and allows you to upload yours.

## 🛠 Quick Start

### Option 1: Use the helper scripts

On macOS or Linux:

```bash
bash run.sh
```

On Windows:

```bat
run.bat
```

### Option 2: Run the grader directly

```bash
python main.py \
  --db course.db \
  --answers answers.sql \
  --responses submissions.csv \
  --output grading_output
```

### Python environment

The helper scripts will:

- create a local virtual environment if needed
- install `pandas` if it is missing
- preserve `grading_output/manual_adjustments.json`
- regenerate the report bundle

## 📦 Outputs

After a successful run, the grader writes a report bundle to `grading_output/`:

- `index.html`: interactive browser-based review report
- `results.json`: structured grading data
- `results.csv`: flattened per-question grading export
- `manual_adjustments.json`: saved manual correction file for reuse

## 📏 Grading Rules

The current grading behavior is result-oriented:

- row order matters
- column order inside a row does **not** matter for correctness
- row counts must match exactly
- fewer columns than expected are labeled `missing_column`
- more columns than expected are labeled `extra_column`
- `pass` and `extra_column` currently receive full automatic credit

This design is useful in introductory SQL instruction because it tolerates some harmless query formulation differences while still surfacing structural mistakes clearly.

## 📝 Manual Review Workflow

The HTML report is built for instructor review rather than just batch scoring.

In the report you can:

- click any graded cell to inspect details
- compare the student query and reference query side by side
- inspect result tables with column headers
- review prompt comments from the answer key
- assign manual partial credit
- add a note explaining the override
- save corrections to JSON
- reload corrections into a later review session

The report also recalculates:

- student totals
- override counts
- grade distribution
- grade summary statistics

## 📚 Sources

The course context in this README is based on the following public pages:

- Harpur Edge: [Harpur Edge Crash Courses](https://www.binghamton.edu/harpur/edge/professional/crash-course.html)
- Binghamton course catalog: [DIDA 110 / Database Fundamentals (SQL)](https://catalog.binghamton.edu/preview_course_nopop.php?catoid=2&coid=31566)
- Digital and Data Studies: [Data Science and Analytics](https://www.binghamton.edu/academics/programs/digital-and-data-studies/professional/data-science-analytics.html)
- Binghamton University Events Calendar: [Coding in SQL Crash Course](https://www.binghamton.edu/apps/calendar/event/details/be-2267627)
- Credly badge description: [Coding in SQL](https://www.credly.com/org/binghamton-university/badge/coding-in-sql)

The specific B-Engaged RSVP page provided as source context was not directly retrievable in the browser tool during generation, so this README uses the public Binghamton and Credly descriptions above as the authoritative references.


[Back to top](#top)
