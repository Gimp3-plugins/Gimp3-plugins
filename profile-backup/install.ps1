<#
.SYNOPSIS
  Instaluje wtyczkę „Profile Backup" w profilu GIMP 3 (Windows).
  Installs the "Profile Backup" plug-in into the GIMP 3 profile (Windows).

.PARAMETER ProfileDir
  Katalog profilu GIMP 3 (domyślnie wykrywany) / GIMP 3 profile folder (auto-detected).

.PARAMETER Force
  Nadpisz istniejącą instalację bez pytania / overwrite an existing install without asking.
#>
param(
    [string]$ProfileDir,
    [switch]$Force
)
$ErrorActionPreference = 'Stop'
$src = Join-Path $PSScriptRoot 'plug-ins\profile-backup'
$core = Join-Path $src 'pb_core.py'

function Find-Python {
    $cands = @(
        (Join-Path $env:LOCALAPPDATA 'Programs\GIMP 3\bin\python.exe'),
        (Join-Path $env:ProgramFiles 'GIMP 3\bin\python.exe')
    )
    foreach ($c in $cands) { if ($c -and (Test-Path $c)) { return $c } }
    foreach ($n in 'py', 'python', 'python3') {
        $cmd = Get-Command $n -ErrorAction SilentlyContinue
        if ($cmd) { return $cmd.Source }
    }
    return $null
}

if (-not $ProfileDir) {
    $py = Find-Python
    if ($py) {
        # The same detection function the plug-in uses.
        $json = & $py $core detect --json 2>$null
        if ($LASTEXITCODE -eq 0 -and $json) {
            $data = $json | ConvertFrom-Json
            $list = @($data.candidates)
            if ($list.Count -gt 1) {
                Write-Host 'Znaleziono kilka profili / Several profiles found:'
                for ($i = 0; $i -lt $list.Count; $i++) { Write-Host "  [$i] $($list[$i].path)  ($($list[$i].source))" }
                $sel = Read-Host 'Numer / Number [0]'
                if (-not $sel) { $sel = 0 }
                $ProfileDir = $list[[int]$sel].path
            } elseif ($list.Count -eq 1) {
                $ProfileDir = $list[0].path
            }
            foreach ($l in @($data.legacy)) { if ($l) { Write-Host "Uwaga / Note: GIMP 2.x profile: $l (pominięty / not touched)" } }
        }
    }
    if (-not $ProfileDir) {
        # Fallback without Python: GIMP3_DIRECTORY, then %APPDATA%\GIMP\3.x (newest).
        if ($env:GIMP3_DIRECTORY -and (Test-Path $env:GIMP3_DIRECTORY)) {
            $ProfileDir = $env:GIMP3_DIRECTORY
        } else {
            $base = Join-Path $env:APPDATA 'GIMP'
            $d = Get-ChildItem $base -Directory -ErrorAction SilentlyContinue |
                 Where-Object { $_.Name -match '^3\.\d+$' } |
                 Sort-Object { [int]($_.Name.Split('.')[1]) } -Descending | Select-Object -First 1
            if ($d) { $ProfileDir = $d.FullName }
        }
    }
}

if (-not $ProfileDir -or -not (Test-Path $ProfileDir)) {
    Write-Error 'Nie znaleziono profilu GIMP 3. Uruchom GIMP 3 raz albo podaj -ProfileDir. / No GIMP 3 profile found. Start GIMP 3 once or pass -ProfileDir.'
}

$target = Join-Path $ProfileDir 'plug-ins\profile-backup'
Write-Host "Profil / Profile: $ProfileDir"
Write-Host "Cel / Target:     $target"

if (Test-Path $target) {
    if (-not $Force) {
        $ans = Read-Host 'Wtyczka już istnieje. Nadpisać? / Plug-in already installed. Overwrite? [t/y/N]'
        if ($ans -notmatch '^(t|tak|y|yes)$') { Write-Host 'Przerwano / Aborted.'; exit 1 }
    }
} else {
    New-Item -ItemType Directory -Path $target | Out-Null
}

foreach ($f in 'profile-backup.py', 'pb_core.py', 'pb_i18n.py') {
    Copy-Item -LiteralPath (Join-Path $src $f) -Destination (Join-Path $target $f) -Force
}
Write-Host 'Zainstalowano. Uruchom ponownie GIMP-a: Plik > Kopia profilu. / Installed. Restart GIMP: File > Profile Backup.'
