# Shared helpers for the Kairos PowerShell scripts (Windows PowerShell 5.1+ / PowerShell 7).
# Dot-source it:  . "$PSScriptRoot\common.ps1"

function Get-RepoRoot { Split-Path -Parent $PSScriptRoot }

function Get-CacheRoot { Join-Path $env:LOCALAPPDATA 'kairos-ai-calendar' }

# True when the path sits inside a OneDrive-synced folder (e.g. a redirected Desktop).
# There we keep node_modules, .next, .venv and the SQLite file in a local, non-synced cache and
# link them into the repo with NTFS junctions, so OneDrive never uploads ~1 GB of regenerable files.
function Test-InOneDrive([string]$Path) {
  $roots = @($env:OneDrive, $env:OneDriveConsumer, $env:OneDriveCommercial) | Where-Object { $_ }
  foreach ($r in $roots) { if ($Path.StartsWith($r, [StringComparison]::OrdinalIgnoreCase)) { return $true } }
  return ($Path -match '\\OneDrive( - [^\\]+)?\\')
}

# Make sure node/npm are reachable even in shells opened before Node was installed.
function Use-Node {
  if (Get-Command node -ErrorAction SilentlyContinue) { return }
  $c = Get-ChildItem (Join-Path $env:LOCALAPPDATA 'Programs') -Directory -Filter 'node-v*-win-x64' -ErrorAction SilentlyContinue |
    Sort-Object Name -Descending | Select-Object -First 1
  if ($c) { $env:Path = "$($c.FullName);$env:Path"; return }
  throw 'Node.js 22+ was not found. Install it from https://nodejs.org and re-run.'
}

# Point $Link at $Target with a junction. A real folder at $Link is regenerable output, so it is removed.
function Set-Junction([string]$Link, [string]$Target) {
  New-Item -ItemType Directory -Force $Target | Out-Null
  if (Test-Path $Link) {
    $item = Get-Item $Link -Force
    if ($item.LinkType -eq 'Junction') {
      if (@($item.Target) -contains $Target) { return }
      cmd /c rmdir "$Link"          # removes only the link, never the target's contents
    } else {
      cmd /c rmdir /s /q "$Link"    # a real folder of regenerable output inside OneDrive
    }
  }
  New-Item -ItemType Junction -Path $Link -Target $Target | Out-Null
}

function Write-Step([string]$Message) { Write-Host "==> $Message" -ForegroundColor Cyan }
