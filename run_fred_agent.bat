@echo off
setlocal
cd /d "C:\Users\Bryce.Leininger\Desktop\Redwood\fred_agent"
if "%FRED_API_KEY%"=="" (
    echo FRED_API_KEY is not set.
    set /p FRED_API_KEY=Enter FRED API key: 
)
python agent.py
pause
