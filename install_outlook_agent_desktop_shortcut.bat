@echo off
setlocal
set TARGET=%SystemRoot%\System32\wscript.exe
set ARGS="%~dp0run_outlook_agent_desktop_hidden.vbs"
set WORKDIR=%~dp0
set LINKNAME=%USERPROFILE%\Desktop\Outlook Agent Desktop.lnk

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$w = New-Object -ComObject WScript.Shell; " ^
  "$s = $w.CreateShortcut('%LINKNAME%'); " ^
  "$s.TargetPath = '%TARGET%'; " ^
  "$s.Arguments = '%ARGS%'; " ^
  "$s.WorkingDirectory = '%WORKDIR%'; " ^
  "$s.IconLocation = '%SystemRoot%\System32\shell32.dll,278'; " ^
  "$s.Save();"

if errorlevel 1 (
  echo Failed to create Desktop shortcut.
  exit /b 1
)

echo Desktop shortcut created: %LINKNAME%
