[CmdletBinding()]
param([string]$GimpExe = "$env:LOCALAPPDATA\Programs\GIMP 3\bin\gimp-console-3.exe")
$ErrorActionPreference = 'Stop'
$packageRoot = Split-Path -Parent $PSScriptRoot
$sandbox = Join-Path $PSScriptRoot ('output\install-sandbox-' + [Guid]::NewGuid().ToString('N'))
$plugins = Join-Path $sandbox 'plug-ins'
& (Join-Path $packageRoot 'install.ps1') -GimpExe $GimpExe -PluginDirectory $plugins
$target = Join-Path $plugins 'bimp3'
if (-not (Test-Path -LiteralPath (Join-Path $target 'bimp_lut_native.dll'))) { throw 'Nie zainstalowano LUT.' }
& (Join-Path $packageRoot 'install.ps1') -GimpExe $GimpExe -PluginDirectory $plugins
if (-not (Get-ChildItem -LiteralPath (Join-Path $sandbox 'bimp3-backups') -Directory)) { throw 'Nie zachowano kopii.' }
$originalHash = (Get-FileHash -LiteralPath (Join-Path $target 'bimp3.py')).Hash
# Fail only the final stage rename; the actual rollback uses native Move-Item.
function Move-Item {
    param([string]$LiteralPath, [string]$Destination)
    if ((Split-Path -Leaf $LiteralPath).StartsWith('.bimp3-stage-')) { throw 'Simulated installation commit failure' }
    Microsoft.PowerShell.Management\Move-Item -LiteralPath $LiteralPath -Destination $Destination
}
$caught = $false
try { & (Join-Path $packageRoot 'install.ps1') -GimpExe $GimpExe -PluginDirectory $plugins }
catch { $caught = $_.Exception.Message -like '*Simulated installation commit failure*' }
if (-not $caught) { throw 'Nie odtworzono testowanego błędu instalacji.' }
if ((Get-FileHash -LiteralPath (Join-Path $target 'bimp3.py')).Hash -ne $originalHash) { throw 'Rollback nie przywrócił poprzedniej wersji.' }
Write-Output 'INSTALL_TEST_OK: pierwsza instalacja, aktualizacja, backup i rollback.'
