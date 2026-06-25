@echo off
echo KB & Co Backend Setup
echo =====================
echo.

REM Create virtual environment
if not exist venv (
    echo Creating virtual environment...
    python -m venv venv
)

echo Activating virtual environment...
call venv\Scripts\activate.bat

echo Installing dependencies...
pip install -r requirements.txt

echo.
echo Setup complete! To start the backend:
echo   venv\Scripts\activate
echo   python run.py
echo.
echo Make sure PostgreSQL is running and create the database:
echo   createdb kbco
echo.
echo Copy .env.example to .env and fill in your credentials.
