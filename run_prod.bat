@echo off
echo ========================================================
echo  Launching Deal Auditor in Production Mode (Windows)
echo ========================================================

if not exist .venv (
    echo [ERROR] Virtual environment .venv not found!
    echo Run: python -m venv .venv ^&^& .venv\Scripts\pip install -r requirements.txt
    exit /b 1
)

.venv\Scripts\python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2
