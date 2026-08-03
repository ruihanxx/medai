@echo off
setlocal
set "MEDAI_PROJECT_ROOT=%~dp0"
where py >nul 2>&1
if errorlevel 1 goto python
py -3 "%~dp0src\medai\launcher.py" %*
exit /b %errorlevel%

:python
python "%~dp0src\medai\launcher.py" %*
exit /b %errorlevel%
