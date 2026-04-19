#!/bin/bash

set -euo pipefail

ENV_DIR="env"
PYTHON_BIN="python3"
SCRIPT="main.py"
DB_PATH="course.db"
ANSWERS_PATH="answers.sql"
RESPONSES_PATH="submissions.csv"
OUTPUT_DIR="grading_output"
ADJUSTMENTS_FILE="$OUTPUT_DIR/manual_adjustments.json"

# ---- 1. Create venv if missing ----
if [ ! -d "$ENV_DIR" ]; then
  echo "[INFO] Creating virtual environment..."
  "$PYTHON_BIN" -m venv "$ENV_DIR"
fi

# ---- 2. Activate venv ----
echo "[INFO] Activating virtual environment..."
source "$ENV_DIR/bin/activate"

# ---- 3. Check & install required packages ----
# Keep this local-first so grading still works without network access.
REQUIRED_PACKAGES=("pandas")

for pkg in "${REQUIRED_PACKAGES[@]}"; do
  if ! python -c "import $pkg" >/dev/null 2>&1; then
    echo "[INFO] Installing missing package: $pkg"
    pip install "$pkg"
  else
    echo "[INFO] $pkg already installed"
  fi
done

# ---- 4. Note manual adjustments behavior ----
if [ -f "$ADJUSTMENTS_FILE" ]; then
  echo "[INFO] Found existing manual adjustments: $ADJUSTMENTS_FILE"
  echo "[INFO] The grader will preserve that file so the HTML report can reload it."
else
  echo "[INFO] No manual adjustments file found yet."
  echo "[INFO] A fresh $ADJUSTMENTS_FILE file will be created on this run."
fi

# ---- 5. Run script ----
echo "[INFO] Running SQL grader..."

python "$SCRIPT" \
  --db "$DB_PATH" \
  --answers "$ANSWERS_PATH" \
  --responses "$RESPONSES_PATH" \
  --output "$OUTPUT_DIR"

echo "[DONE] Report written to $OUTPUT_DIR"
echo "[INFO] Open $OUTPUT_DIR/index.html to review grades."
echo "[INFO] Manual corrections are stored in-browser for the current session and can be exported/imported as JSON."
echo "[INFO] Keep $ADJUSTMENTS_FILE next to index.html if you want the report to auto-load saved corrections on first open."
