@echo off
python -X utf8 "%~dp0tools\workspace.py" launch
exit /b %errorlevel%
