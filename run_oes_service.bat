@echo off
setlocal
cd /d "%~dp0"

if not exist "data\output\oes_agent" mkdir "data\output\oes_agent"

if exist ".venv\Scripts\python.exe" (
    set "PYTHON_EXE=%CD%\.venv\Scripts\python.exe"
) else (
    set "PYTHON_EXE=python"
)

if "%OES_HOST%"=="" set "OES_HOST=0.0.0.0"
if "%OES_PORT%"=="" set "OES_PORT=8787"
if "%OES_DATA_DIR%"=="" set "OES_DATA_DIR=data/output/oes_agent"

"%PYTHON_EXE%" -m oes_agent serve --host %OES_HOST% --port %OES_PORT% >> "data\output\oes_agent\service.log" 2>&1