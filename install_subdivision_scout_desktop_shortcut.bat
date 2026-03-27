@echo off
setlocal
set WORKDIR=%~dp0

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$desktop = [Environment]::GetFolderPath('Desktop'); " ^
  "$link = Join-Path $desktop 'Residential Subdivision Scout.lnk'; " ^
  "$python = (Get-Command python -ErrorAction Stop).Source; " ^
  "$pythonw = Join-Path (Split-Path $python) 'pythonw.exe'; " ^
  "if (-not (Test-Path $pythonw)) { throw 'pythonw.exe not found next to python.exe'; } " ^
  "$w = New-Object -ComObject WScript.Shell; " ^
  "$s = $w.CreateShortcut($link); " ^
  "$s.TargetPath = $pythonw; " ^
  "$s.Arguments = '-m agent_factory.subdivision_scout_desktop_launcher'; " ^
  "$s.WorkingDirectory = '%WORKDIR%'; " ^
  "$s.IconLocation = '%SystemRoot%\System32\shell32.dll,44'; " ^
  "$s.WindowStyle = 1; " ^
  "$s.Save(); " ^
  "Write-Output ('Desktop shortcut created: ' + $link);"

if errorlevel 1 (
  echo Failed to create Desktop shortcut.
  exit /b 1
)
