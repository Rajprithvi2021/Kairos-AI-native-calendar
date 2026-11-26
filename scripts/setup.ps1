<#
.SYNOPSIS
  One-time setup on Windows (PowerShell 5.1+). Safe to re-run.

  1. Checks prerequisites (Git, uv, Node.js).
  2. Inside OneDrive: keeps .venv, the SQLite file, node_modules and .next in a local, non-synced
     cache and links them into the repo (junctions), so OneDrive never uploads ~1 GB of regenerable files.
  3. Installs Python dependencies (uv) and web dependencies (npm).
  4. Seeds the demo database.

  Run:  powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
#>
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\common.ps1"
$repo = Get-RepoRoot
$api = Join-Path $repo 'services\api'

Write-Step 'Checking prerequisites'
foreach ($t in 'git', 'uv') {
  if (-not (Get-Command $t -ErrorAction SilentlyContinue)) { throw "$t is required - see REQUIREMENTS.md" }
}
Use-Node
Write-Host ("  node {0}, npm {1}, {2}" -f (node --version), (npm.cmd --version), (uv --version))

if (Test-InOneDrive $repo) {
  Write-Step "Repo is inside OneDrive - linking heavy folders to $(Get-CacheRoot)"
  $venv = Join-Path (Get-CacheRoot) 'api-venv'
  if (-not (Test-Path (Join-Path $venv 'pyvenv.cfg'))) { uv venv $venv --python 3.12 --quiet }
  Set-Junction (Join-Path $api '.venv') $venv
  Set-Junction (Join-Path $api '.data') (Join-Path (Get-CacheRoot) 'api-data')
}

Write-Step 'Installing Python dependencies (uv sync)'
Push-Location $api
try { uv sync --quiet; if ($LASTEXITCODE) { throw 'uv sync failed' } } finally { Pop-Location }

Write-Step 'Installing web dependencies (npm ci)'
& powershell -NoProfile -ExecutionPolicy Bypass -File "$PSScriptRoot\web-npm.ps1" ci
if ($LASTEXITCODE) { throw 'npm ci failed' }

Write-Step 'Seeding the demo database'
Push-Location $api
try { $env:PYTHONUTF8 = '1'; uv run --no-sync python -m app.seed } finally { Pop-Location }

Write-Step 'Done. Start everything with:  powershell -ExecutionPolicy Bypass -File scripts\dev.ps1'
