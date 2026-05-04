$startupFolder = [Environment]::GetFolderPath("Startup")
$shortcutPath = Join-Path $startupFolder "OES Agent.lnk"

if (Test-Path $shortcutPath) {
    Remove-Item $shortcutPath -Force
    Write-Output "Removed startup shortcut at $shortcutPath"
} else {
    Write-Output "Startup shortcut not found at $shortcutPath"
}