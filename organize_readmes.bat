@echo off
setlocal
cd /d "%~dp0"
if not exist "docs\history" mkdir "docs\history"
if exist "README_CASE_STUDY_SCREENING.md" move /Y "README_CASE_STUDY_SCREENING.md" "docs\history\README_CASE_STUDY_SCREENING.md"
if exist "README_DIRECTED_DISTANCE_INTEGRATION.txt" move /Y "README_DIRECTED_DISTANCE_INTEGRATION.txt" "docs\history\README_DIRECTED_DISTANCE_INTEGRATION.txt"
if exist "README_INTERSTATION_GAP.md" move /Y "README_INTERSTATION_GAP.md" "docs\history\README_INTERSTATION_GAP.md"
echo.
echo README organization complete.
echo Root README.md is the current project overview.
echo Historical notes are stored in docs\history\.
echo.
git status --short
endlocal
