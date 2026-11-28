[CmdletBinding(SupportsShouldProcess)]
param([string]$ProfileDirectory, [switch]$CheckOnly)
$ErrorActionPreference = 'Stop'
$source = Join-Path $PSScriptRoot 'plug-ins\zetmar-maski'
if (-not $ProfileDirectory) {
    $profiles = @(Get-ChildItem -LiteralPath (Join-Path $env:APPDATA 'GIMP') -Directory |
        Where-Object { $_.Name -match '^3\.\d+$' } | Sort-Object { [version]$_.Name } -Descending)
    if (-not $profiles.Count) { throw 'Uruchom raz GIMP 3, aby powstal profil, albo podaj -ProfileDirectory.' }
    $ProfileDirectory = $profiles[0].FullName
}
$profilePath = [IO.Path]::GetFullPath($ProfileDirectory)
$pluginsPath = Join-Path $profilePath 'plug-ins'
$destination = Join-Path $pluginsPath 'zetmar-maski'
$files = @(Get-ChildItem -LiteralPath $source -File -Filter '*.py')
if ($files.Count -ne 4) { throw 'Niekompletna paczka: wymagane cztery moduly Python.' }
Write-Output "Zetmar Maski 1.0.0 -> $destination"
if ($CheckOnly) { Write-Output 'Pliki zrodlowe sprawdzone. Bez zmian w profilu.'; return }
if (-not $PSCmdlet.ShouldProcess($destination, 'Zainstaluj Zetmar Maski')) { return }
New-Item -ItemType Directory -Path $pluginsPath -Force | Out-Null
$stage = Join-Path $profilePath ('zetmar-maski-stage-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $stage | Out-Null
$backup = $null
try {
    foreach ($file in $files) {
        $copy = Join-Path $stage $file.Name
        Copy-Item -LiteralPath $file.FullName -Destination $copy
        if ((Get-FileHash -LiteralPath $copy).Hash -ne (Get-FileHash -LiteralPath $file.FullName).Hash) {
            throw "Niepoprawna suma pliku $($file.Name)"
        }
    }
    if (Test-Path -LiteralPath $destination) {
        $backupRoot = Join-Path $profilePath 'zetmar-maski-backups'
        New-Item -ItemType Directory -Path $backupRoot -Force | Out-Null
        $backup = Join-Path $backupRoot (Get-Date -Format 'yyyyMMdd-HHmmss-ffff')
        # Every move stays within the explicitly selected profile.
        foreach ($pathToCheck in @($destination, $backup, $stage)) {
            if (-not ([IO.Path]::GetFullPath($pathToCheck).StartsWith($profilePath.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase))) {
                throw 'Sciezka wychodzi poza profil.'
            }
        }
        Move-Item -LiteralPath $destination -Destination $backup
    }
    Move-Item -LiteralPath $stage -Destination $destination
} catch {
    if ($backup -and (Test-Path -LiteralPath $backup) -and -not (Test-Path -LiteralPath $destination)) {
        Move-Item -LiteralPath $backup -Destination $destination
    }
    throw
}
Write-Output 'Zainstalowano. Uruchom ponownie GIMP: Filtry > Zetmar > Maski jasnosci i koloru.'
