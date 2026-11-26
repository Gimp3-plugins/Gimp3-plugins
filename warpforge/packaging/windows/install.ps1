# SPDX-License-Identifier: GPL-3.0-or-later
# Install (or remove) WarpForge into the newest GIMP 3.x user profile.
#
# Run from the folder where you unpacked the ZIP:
#   powershell -ExecutionPolicy Bypass -File install.ps1            # install / update
#   powershell -ExecutionPolicy Bypass -File install.ps1 -Uninstall
#   powershell -ExecutionPolicy Bypass -File install.ps1 -GimpVersion 3.0
param(
    [switch]$Uninstall,
    [string]$GimpVersion = ""
)
$ErrorActionPreference = "Stop"

$gimpRoot = Join-Path $env:APPDATA "GIMP"
if ($GimpVersion) {
    $profileDir = Join-Path $gimpRoot $GimpVersion
} else {
    $candidates = Get-ChildItem -Path $gimpRoot -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match '^3\.\d+$' } |
        Sort-Object { [version]$_.Name } -Descending
    if (-not $candidates) {
        Write-Error "No GIMP 3 profile found in $gimpRoot. Start GIMP 3 once, then run this again."
    }
    $profileDir = $candidates[0].FullName
}

$target = Join-Path $profileDir "plug-ins\warpforge"
if (Test-Path $target) {
    Remove-Item -Recurse -Force $target
}
if ($Uninstall) {
    Write-Host "Removed WarpForge from $profileDir. Restart GIMP."
    exit 0
}

$source = Join-Path $PSScriptRoot "warpforge"
if (-not (Test-Path (Join-Path $source "warpforge.py"))) {
    Write-Error "warpforge\warpforge.py not found next to this script. Unpack the whole ZIP first."
}
New-Item -ItemType Directory -Force (Split-Path $target) | Out-Null
Copy-Item -Recurse $source $target
Write-Host "Installed WarpForge into $target"
Write-Host "Restart GIMP, then use Filters > Distorts > WarpForge..."
