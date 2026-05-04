$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$serviceScript = Join-Path $repoRoot "run_oes_service.bat"

Push-Location $repoRoot
try {
    if (-not (Test-Path "data\output\oes_agent")) {
        New-Item -ItemType Directory -Path "data\output\oes_agent" | Out-Null
    }

    if (-not $env:OES_DATA_DIR) {
        $env:OES_DATA_DIR = "data/output/oes_agent"
    }

    $port = if ($env:OES_PORT) { [int]$env:OES_PORT } else { 8787 }
    $url = "http://127.0.0.1:$port/"
    $listener = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue

    if ($null -eq $listener) {
        Start-Process -FilePath $serviceScript -WorkingDirectory $repoRoot -WindowStyle Hidden
        for ($attempt = 0; $attempt -lt 16; $attempt++) {
            Start-Sleep -Milliseconds 500
            $listener = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
            if ($null -ne $listener) {
                break
            }
        }
    }

    Start-Process $url
}
finally {
    Pop-Location
}