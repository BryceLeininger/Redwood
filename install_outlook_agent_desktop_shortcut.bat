@echo off
setlocal
set WORKDIR=%~dp0

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$desktop = [Environment]::GetFolderPath('Desktop'); " ^
  "$link = Join-Path $desktop 'Outlook Agent Desktop.lnk'; " ^
  "$python = (Get-Command python -ErrorAction Stop).Source; " ^
  "$pythonw = Join-Path (Split-Path $python) 'pythonw.exe'; " ^
  "if (-not (Test-Path $pythonw)) { throw 'pythonw.exe not found next to python.exe'; } " ^
  "$w = New-Object -ComObject WScript.Shell; " ^
  "$s = $w.CreateShortcut($link); " ^
  "$s.TargetPath = $pythonw; " ^
  "$s.Arguments = '-m agent_factory.desktop_agent_app'; " ^
  "$s.WorkingDirectory = '%WORKDIR%'; " ^
  "$s.IconLocation = '%SystemRoot%\System32\shell32.dll,278'; " ^
  "$s.WindowStyle = 1; " ^
  "$s.Save(); " ^
  "Write-Output ('Desktop shortcut created: ' + $link);"

if errorlevel 1 (
  echo Failed to create Desktop shortcut.
  exit /b 1
)
