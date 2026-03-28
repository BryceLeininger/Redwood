@echo off
setlocal
cd /d "%~dp0"
python -m agent_factory.homebuilder_phone_suite_server --host 0.0.0.0 --port 8790
