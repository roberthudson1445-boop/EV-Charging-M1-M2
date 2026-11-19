@echo off
setlocal
set PY=.^\.venv\Scripts\python.exe

echo ============================================================
echo Directed OSM MILP scenario runs: LOW, BASE, HIGH, ARMSTAT
echo Outputs are written to data\derived\case_study_screening_milp_directed_network
echo ============================================================

%PY% scripts\run_case_study_scenario.py low
if errorlevel 1 exit /b %errorlevel%

%PY% scripts\run_case_study_scenario.py base
if errorlevel 1 exit /b %errorlevel%

%PY% scripts\run_case_study_scenario.py high
if errorlevel 1 exit /b %errorlevel%

%PY% scripts\run_case_study_scenario.py armstat_ev_share_2_92
if errorlevel 1 exit /b %errorlevel%

echo.
echo All four directed-network scenario runs completed.
endlocal
