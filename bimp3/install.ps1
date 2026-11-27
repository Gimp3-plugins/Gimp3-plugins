[CmdletBinding(SupportsShouldProcess)]
param(
    [string]$GimpExe,
    [string]$PluginDirectory,
    [switch]$CheckOnly
)
$ErrorActionPreference = 'Stop'
if (-not $GimpExe) {
    $candidates = @(
        (Join-Path $env:LOCALAPPDATA 'Programs\GIMP 3\bin\gimp-console-3.exe'),
        (Join-Path $env:ProgramFiles 'GIMP 3\bin\gimp-console-3.exe'),
        'C:\gimp3\bin\gimp-console-3.exe'
    )
    $GimpExe = $candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
}
if (-not $GimpExe -or -not (Test-Path -LiteralPath $GimpExe)) {
    throw 'Nie znaleziono GIMP. Podaj -GimpExe z pełną ścieżką do gimp-console-3.exe.'
}
$GimpExe = (Resolve-Path -LiteralPath $GimpExe).Path
$versionText = (& $GimpExe --version) -join ' '
# GIMP translates "version" (e.g. Polish: "w wersji"), so match only the number.
if ($LASTEXITCODE -ne 0 -or $versionText -notmatch '(?<![\d.])(3)\.(\d+)\.(\d+)(?![\d.])') {
    throw "Nie można potwierdzić GIMP 3: $versionText"
}
$profileVersion = "$($Matches[1]).$($Matches[2])"
$pythonExe = Join-Path (Split-Path -Parent $GimpExe) 'python.exe'
if (-not (Test-Path -LiteralPath $pythonExe)) {
    throw 'Brak interpretera Python w instalacji GIMP.'
}
& $pythonExe -c "import gi; gi.require_version('Gimp','3.0'); gi.require_version('GimpUi','3.0'); gi.require_version('Gtk','3.0'); gi.require_version('Gegl','0.4'); from gi.repository import Gimp,GimpUi,Gtk,Gegl; print('Python / GI / GIMP / GTK / GEGL: OK')"
if ($LASTEXITCODE -ne 0) { throw 'Brak wymaganych bibliotek w instalacji GIMP.' }
if (-not $PluginDirectory) {
    $profileRoot = if ($env:GIMP3_DIRECTORY) { $env:GIMP3_DIRECTORY } else { Join-Path $env:APPDATA "GIMP\$profileVersion" }
    $PluginDirectory = Join-Path $profileRoot 'plug-ins'
}
$target = [IO.Path]::GetFullPath((Join-Path $PluginDirectory 'bimp3'))
$source = Join-Path $PSScriptRoot 'bimp3'
$files = @(Get-ChildItem -LiteralPath $source -File | Where-Object { $_.Extension -in @('.py', '.dll', '.c', '.sha256') -or $_.Name -eq 'LICENSE' } | Select-Object -ExpandProperty Name)
foreach ($required in @('bimp3.py', 'bimp_engine.py', 'bimp_model.py', 'bimp_ui.py', 'bimp_window.py', 'bimp_jobs.py', 'bimp_worker.py', 'bimp_preview.py', 'bimp_lut.py', 'bimp_lut_native.dll', 'bimp_lut_native.dll.sha256', 'bimp_presets.py', 'bimp_i18n.py', 'bimp_history.py', 'bimp_naming.py', 'LICENSE')) {
    if ($required -notin $files) { throw "Brak wymaganego pliku: $required" }
}
foreach ($file in $files) {
    if (-not (Test-Path -LiteralPath (Join-Path $source $file))) { throw "Brak pliku: $file" }
}
Write-Output $versionText
Write-Output "Katalog instalacji: $target"
if ($CheckOnly) { return }
if ($PSCmdlet.ShouldProcess($target, 'Zainstaluj BIMP 3; zachowaj kopię wcześniejszej wersji')) {
    $pluginRoot = [IO.Path]::GetFullPath($PluginDirectory)
    New-Item -ItemType Directory -Path $pluginRoot -Force | Out-Null
    $stage = [IO.Path]::GetFullPath((Join-Path $pluginRoot ('.bimp3-stage-' + [Guid]::NewGuid().ToString('N'))))
    if ((Split-Path -Parent $stage) -ne $pluginRoot -or (Split-Path -Parent $target) -ne $pluginRoot) { throw 'Niebezpieczny katalog instalacji.' }
    New-Item -ItemType Directory -Path $stage | Out-Null
    foreach ($file in $files) {
        Copy-Item -LiteralPath (Join-Path $source $file) -Destination (Join-Path $stage $file)
        if ((Get-FileHash -LiteralPath (Join-Path $source $file)).Hash -ne (Get-FileHash -LiteralPath (Join-Path $stage $file)).Hash) {
            throw "Weryfikacja kopii nie powiodła się: $file"
        }
    }
    & $pythonExe -c "import sys; sys.path.insert(0,sys.argv[1]); import bimp_window,bimp_worker,bimp_lut,bimp_history,bimp_naming; assert bimp_lut.native_module() is not None, bimp_lut.native_problem; print('Komplet modułów i akcelerator LUT: OK')" $stage
    if ($LASTEXITCODE -ne 0) { throw "Weryfikacja wersji nie powiodła się. Zachowano poprzednią instalację. Staging: $stage" }
    $backup = $null
    try {
        if (Test-Path -LiteralPath $target) {
            $backupRoot = [IO.Path]::GetFullPath((Join-Path (Split-Path -Parent $pluginRoot) 'bimp3-backups'))
            $backup = [IO.Path]::GetFullPath((Join-Path $backupRoot (Get-Date -Format 'yyyyMMdd-HHmmss-ffff')))
            if ((Split-Path -Parent $backup) -ne $backupRoot) { throw 'Niebezpieczny katalog kopii.' }
            New-Item -ItemType Directory -Path $backupRoot -Force | Out-Null
            Move-Item -LiteralPath $target -Destination $backup
            Write-Output "Kopia poprzedniej wersji: $backup"
        }
        Move-Item -LiteralPath $stage -Destination $target
    }
    catch {
        if ($backup -and (Test-Path -LiteralPath $backup) -and -not (Test-Path -LiteralPath $target)) {
            Move-Item -LiteralPath $backup -Destination $target
        }
        throw
    }
    Write-Output 'BIMP 3 zainstalowany. Uruchom ponownie GIMP; wybierz Plik > BIMP 3 — przetwarzanie wsadowe…'
}
