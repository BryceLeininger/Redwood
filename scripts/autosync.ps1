param(
  [int]$IntervalSeconds = 30,
  [string]$CommitMessagePrefix = "autosync",
  [switch]$NoPull,
  [switch]$NoPush
)

$ErrorActionPreference = "Stop"

function Exec([string]$cmd) {
  $out = & powershell -NoProfile -Command $cmd 2>&1
  $code = $LASTEXITCODE
  return @{ Output = $out; ExitCode = $code }
}

function ExecGit([string[]]$args) {
  $out = & git @args 2>&1
  $code = $LASTEXITCODE
  return @{ Output = $out; ExitCode = $code }
}

# Ensure we're in a git repo
$root = (ExecGit @("rev-parse","--show-toplevel"))
if ($root.ExitCode -ne 0) {
  throw "Not a git repository (or git not installed)."
}
$repoRoot = ($root.Output | Select-Object -First 1).Trim()
Set-Location $repoRoot

Write-Host "[autosync] Repo: $repoRoot"
Write-Host "[autosync] Interval: $IntervalSeconds seconds"
Write-Host "[autosync] Pull: " -NoNewline; if ($NoPull) { Write-Host "disabled" } else { Write-Host "enabled" }
Write-Host "[autosync] Push: " -NoNewline; if ($NoPush) { Write-Host "disabled" } else { Write-Host "enabled" }
Write-Host "[autosync] Press Ctrl+C to stop."

while ($true) {
  try {
    $status = ExecGit @("status","--porcelain")
    if ($status.ExitCode -ne 0) {
      Write-Host "[autosync] git status failed:" -ForegroundColor Red
      Write-Host $status.Output
      Start-Sleep -Seconds $IntervalSeconds
      continue
    }

    $changes = @($status.Output)
    if ($changes.Count -eq 0) {
      Start-Sleep -Seconds $IntervalSeconds
      continue
    }

    # Stage changes (respects .gitignore)
    $add = ExecGit @("add","-A")
    if ($add.ExitCode -ne 0) {
      Write-Host "[autosync] git add failed:" -ForegroundColor Red
      Write-Host $add.Output
      Start-Sleep -Seconds $IntervalSeconds
      continue
    }

    # Commit (will fail if nothing is staged)
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $msg = "${CommitMessagePrefix}: $ts"
    $commit = ExecGit @("commit","-m",$msg)
    if ($commit.ExitCode -ne 0) {
      $txt = ($commit.Output | Out-String)
      if ($txt -match "nothing to commit" -or $txt -match "no changes added to commit") {
        Start-Sleep -Seconds $IntervalSeconds
        continue
      }
      Write-Host "[autosync] git commit failed:" -ForegroundColor Red
      Write-Host $commit.Output
      Start-Sleep -Seconds $IntervalSeconds
      continue
    }

    Write-Host "[autosync] committed: $msg"

    if (-not $NoPull) {
      $pull = ExecGit @("pull","--rebase")
      if ($pull.ExitCode -ne 0) {
        Write-Host "[autosync] git pull --rebase failed. Resolve manually, then restart autosync." -ForegroundColor Red
        Write-Host $pull.Output
        break
      }
    }

    if (-not $NoPush) {
      $push = ExecGit @("push")
      if ($push.ExitCode -ne 0) {
        Write-Host "[autosync] git push failed. You may need to sign in / set upstream." -ForegroundColor Red
        Write-Host $push.Output
        Start-Sleep -Seconds $IntervalSeconds
        continue
      }
    }

  } catch {
    Write-Host "[autosync] error: $($_.Exception.Message)" -ForegroundColor Red
  }

  Start-Sleep -Seconds $IntervalSeconds
}
