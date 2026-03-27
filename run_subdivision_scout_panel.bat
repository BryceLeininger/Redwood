@echo off
start "" powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 2; Start-Process 'http://127.0.0.1:8785'"
python -m agent_factory.subdivision_scout_panel_server --host 127.0.0.1 --port 8785
