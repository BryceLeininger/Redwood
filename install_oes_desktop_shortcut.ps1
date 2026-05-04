$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$desktopFolder = [Environment]::GetFolderPath("Desktop")
$shortcutPath = Join-Path $desktopFolder "Outlook Email Secretary.lnk"
$launcherPath = Join-Path $repoRoot "launch_oes_dashboard.ps1"

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
$shortcut.Arguments = "-ExecutionPolicy Bypass -File `"$launcherPath`""
$shortcut.WorkingDirectory = $repoRoot
$shortcut.IconLocation = "$env:SystemRoot\System32\shell32.dll,220"
$shortcut.Description = "Launch Outlook Email Secretary"
$shortcut.Save()

Write-Output "Installed desktop shortcut at $shortcutPath"