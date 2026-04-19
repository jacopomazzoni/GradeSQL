@echo off
setlocal EnableExtensions

set "ENV_DIR=env"
set "SCRIPT=main.py"
set "DB_PATH=course.db"
set "ANSWERS_PATH=answers.sql"
set "RESPONSES_PATH=submissions.csv"
set "OUTPUT_DIR=grading_output"
set "ADJUSTMENTS_FILE=%OUTPUT_DIR%\manual_adjustments.json"

set "PYTHON_BOOTSTRAP="
where py >nul 2>nul
if not errorlevel 1 (
  set "PYTHON_BOOTSTRAP=py -3"
) else (
  where python >nul 2>nul
  if not errorlevel 1 (
    set "PYTHON_BOOTSTRAP=python"
  )
)

if not defined PYTHON_BOOTSTRAP (
  echo [ERROR] Could not find Python 3 on PATH.
  echo [ERROR] Install Python and make sure either "py" or "python" is available.
  exit /b 1
)

if not exist "%ENV_DIR%\Scripts\python.exe" (
  echo [INFO] Creating virtual environment...
  %PYTHON_BOOTSTRAP% -m venv "%ENV_DIR%"
  if errorlevel 1 exit /b 1
)

echo [INFO] Activating virtual environment...
call "%ENV_DIR%\Scripts\activate.bat"
if errorlevel 1 exit /b 1

python -c "import pandas" >nul 2>nul
if errorlevel 1 (
  echo [INFO] Installing missing package: pandas
  python -m pip install pandas
  if errorlevel 1 exit /b 1
) else (
  echo [INFO] pandas already installed
)

if exist "%ADJUSTMENTS_FILE%" (
  echo [INFO] Found existing manual adjustments: %ADJUSTMENTS_FILE%
  echo [INFO] The grader will preserve that file so the HTML report can reload it.
) else (
  echo [INFO] No manual adjustments file found yet.
  echo [INFO] A fresh %ADJUSTMENTS_FILE% file will be created on this run.
)

echo [INFO] Running SQL grader...
python "%SCRIPT%" ^
  --db "%DB_PATH%" ^
  --answers "%ANSWERS_PATH%" ^
  --responses "%RESPONSES_PATH%" ^
  --output "%OUTPUT_DIR%"
if errorlevel 1 exit /b 1

echo [DONE] Report written to %OUTPUT_DIR%
echo [INFO] Open %OUTPUT_DIR%\index.html to review grades.
echo [INFO] Manual corrections are stored in-browser for the current session and can be exported/imported as JSON.
echo [INFO] Keep %ADJUSTMENTS_FILE% next to index.html if you want the report to auto-load saved corrections on first open.

endlocal
