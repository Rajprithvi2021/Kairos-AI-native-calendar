<#
.SYNOPSIS
  Run every automated check: backend lint + tests + NL evals, web type-check + lint + unit tests + build,
  and (with -E2E) the Playwright end-to-end flows in Microsoft Edge.

  powershell -ExecutionPolicy Bypass -File scripts\test.ps1          # everything except E2E
  powershell -ExecutionPolicy Bypass -File scripts\test.ps1 -E2E     # also E2E (start scripts\dev.ps1 first)
#>
param([switch]$E2E)

$ErrorActionPreference = 'Continue'
. "$PSScriptRoot\common.ps1"
$repo = Get-RepoRoot
$api = Join-Path $repo 'services\api'
$web = Join-Path $repo 'apps\web'
$env:PYTHONUTF8 = '1'
$env:NEXT_TELEMETRY_DISABLED = '1'
$script:failed = @()

function Invoke-Check([string]$Name, [scriptblock]$Command) {
  Write-Step $Name
  & $Command
  if ($LASTEXITCODE -ne 0) { $script:failed += $Name; Write-Host "  FAILED: $Name" -ForegroundColor Red }
}

Push-Location $api
Invoke-Check 'Backend lint (ruff)' { uv run --no-sync python -m ruff check app tests evals }
Invoke-Check 'Backend tests (pytest, incl. property tests)' { uv run --no-sync python -m pytest }
Invoke-Check 'NL command golden-set evaluation' { uv run --no-sync python -m evals.run_evals }
Pop-Location

Use-Node
Push-Location $web
Invoke-Check 'Web route types (next typegen)' { npx.cmd next typegen }
Invoke-Check 'Web type-check (tsc)' { npx.cmd tsc --noEmit }
Invoke-Check 'Web lint (eslint)' { npx.cmd eslint src }
Invoke-Check 'Web unit tests (vitest)' { npx.cmd vitest run }
$devRunning = Get-NetTCPConnection -LocalPort 3000 -State Listen -ErrorAction SilentlyContinue
if ($devRunning) {
  Write-Host '==> Skipping production build: the dev server on :3000 shares .next (stop it to build).' -ForegroundColor Yellow
} else {
  Invoke-Check 'Web production build' { npm.cmd run build }
}
Pop-Location

if ($E2E) {
  Push-Location $api
  Invoke-Check 'End-to-end flows (Playwright + Edge)' { uv run --no-sync python -m pytest ../../tests/e2e }
  Pop-Location
}

if ($script:failed.Count) {
  Write-Host ("`nFAILED: " + ($script:failed -join ', ')) -ForegroundColor Red
  exit 1
}
Write-Host "`nAll checks passed." -ForegroundColor Green
