# Start the Kairos web app on http://localhost:3000 (proxies /api/* to the API on port 8000).
param([int]$Port = 3000)

$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\common.ps1"
Use-Node
Set-Location (Join-Path (Get-RepoRoot) 'apps\web')
$env:NEXT_TELEMETRY_DISABLED = '1'
& npx.cmd next dev --webpack -p $Port
