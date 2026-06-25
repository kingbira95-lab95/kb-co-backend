@echo off
echo Starting KB & Co Backend...
cd /d "%~dp0"
if exist venv (
    call venv\Scripts\activate.bat
)
python run.py
