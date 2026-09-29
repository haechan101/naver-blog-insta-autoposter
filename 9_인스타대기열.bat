@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
venv\Scripts\python.exe run_insta.py --list
echo.
echo  [시험] 지금 자동 발행이 돌면 무엇을 올리는지 (실제로 올리지 않음):
venv\Scripts\python.exe run_insta.py --dry
echo.
pause
