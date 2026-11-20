@echo off
setlocal
set "LIDAR2DSM_ROOT=%~dp0"
set "LIDAR2DSM_PYTHON=%LIDAR2DSM_ROOT%.venv\Scripts\python.exe"

if exist "%LIDAR2DSM_PYTHON%" (
  "%LIDAR2DSM_PYTHON%" "%LIDAR2DSM_ROOT%start_lidar2dsm.py" %*
) else (
  python "%LIDAR2DSM_ROOT%start_lidar2dsm.py" %*
)

exit /b %ERRORLEVEL%
