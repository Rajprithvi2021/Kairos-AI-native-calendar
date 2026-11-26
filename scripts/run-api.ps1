# Start the Kairos API on http://127.0.0.1:8000  (OpenAPI docs: /docs)
#   ./scripts/run-api.ps1            # normal
#   ./scripts/run-api.ps1 -Reload    # auto-reload on code changes
param([int]$Port = 8000, [switch]$Reload)

$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\common.ps1"
Set-Location (Join-Path (Get-RepoRoot) 'services\api')
$env:PYTHONUTF8 = '1'
# "python -m" instead of the uvicorn.exe shim: works even where Application Control blocks unsigned launchers.
$uvArgs = @('run', '--no-sync', 'python', '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', "$Port")
if ($Reload) { $uvArgs += '--reload' }
& uv @uvArgs
