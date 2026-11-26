# Start API + web app in two new PowerShell windows, then open the app.
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\common.ps1"
$common = @('-NoExit', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File')
Start-Process powershell -ArgumentList ($common + "$PSScriptRoot\run-api.ps1")
Start-Process powershell -ArgumentList ($common + "$PSScriptRoot\run-web.ps1")
Write-Step 'API  -> http://127.0.0.1:8000/docs'
Write-Step 'App  -> http://localhost:3000   (first compile takes ~20 s)'
Start-Sleep -Seconds 12
Start-Process 'http://localhost:3000'
