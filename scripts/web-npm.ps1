<#
.SYNOPSIS
  Run an npm dependency command for apps/web (install / uninstall / update / ci).

.DESCRIPTION
  Outside OneDrive this is plain `npm <args>` in apps/web.
  Inside OneDrive the packages are installed in a local cache folder (not synced) and linked into
  apps/web/node_modules with a junction; package.json and package-lock.json are kept in sync.

.EXAMPLE
  ./scripts/web-npm.ps1 install
  ./scripts/web-npm.ps1 install -D some-package
#>
# No param() block on purpose: npm flags such as -D must reach npm untouched (an advanced-script
# param block would bind -D to PowerShell's -Debug).
$NpmArgs = @($args)
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\common.ps1"
if ($NpmArgs.Count -eq 0) { $NpmArgs = @('install') }
Use-Node
$web = Join-Path (Get-RepoRoot) 'apps\web'

if (-not (Test-InOneDrive $web)) {
  Push-Location $web
  try { & npm.cmd @NpmArgs; exit $LASTEXITCODE } finally { Pop-Location }
}

$deps = Join-Path (Get-CacheRoot) 'web-deps'
New-Item -ItemType Directory -Force $deps | Out-Null
Copy-Item (Join-Path $web 'package.json') $deps -Force
$lock = Join-Path $web 'package-lock.json'
if (Test-Path $lock) { Copy-Item $lock $deps -Force }

Push-Location $deps
try { & npm.cmd @NpmArgs --no-audit --no-fund; $code = $LASTEXITCODE } finally { Pop-Location }

Copy-Item (Join-Path $deps 'package.json') $web -Force
if (Test-Path (Join-Path $deps 'package-lock.json')) { Copy-Item (Join-Path $deps 'package-lock.json') $web -Force }
Set-Junction (Join-Path $web 'node_modules') (Join-Path $deps 'node_modules')
# .next must live beside node_modules: compiled server chunks resolve packages from their real path.
Set-Junction (Join-Path $web '.next') (Join-Path $deps '.next')
exit $code
