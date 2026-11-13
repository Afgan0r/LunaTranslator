@echo off
python -X utf8 "%~dp0tools\build_native.py"
if errorlevel 1 exit /b %errorlevel%
python -X utf8 "%~dp0tools\workspace.py" build %*
exit /b %errorlevel%
