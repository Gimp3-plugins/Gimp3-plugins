<#
.SYNOPSIS
    BIMP 3 bez okna: przetwarza zdjęcia zapisanym zestawem albo obserwuje folder.

.DESCRIPTION
    Uruchamia konsolowy GIMP z osobnym, stałym profilem (szybszy kolejny start, główny
    profil GIMP nie jest zmieniany) i wywołuje procedurę PDB plug-in-bimp3.
    W trybie -Watch co -PollSeconds sekund wyszukuje nowe zdjęcia w -InputFolder.
    Plik jest przetwarzany dopiero, gdy jego rozmiar i data nie zmieniły się między
    dwoma przeglądami (kopiowanie się zakończyło). Stan obserwacji: .bimp3-watch.json
    w folderze wyników. Zatrzymanie: Ctrl+C.

.EXAMPLE
    .\bimp3-cli.ps1 -Settings .\examples\web-1600.bimp3.json -InputFolder D:\Zdjecia -Output D:\Wyniki

.EXAMPLE
    .\bimp3-cli.ps1 -Settings web.json -InputFolder D:\Import -Output D:\Web -Watch -Collision suffix
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string]$Settings,
    [Parameter(Mandatory)] [string]$Output,
    [string[]]$Files,
    [string]$InputFolder,
    [switch]$Recurse,
    [ValidateSet('skip', 'replace', 'suffix')] [string]$Collision = 'skip',
    [ValidateSet('strip-gps', 'preserve', 'strip')] [string]$Metadata = 'strip-gps',
    [ValidateSet('preserve', 'srgb')] [string]$OutputColor = 'preserve',
    [switch]$KeepHierarchy,
    [switch]$KeepDates,
    [switch]$NoAutoOrient,
    [switch]$NoColorProfile,
    [switch]$Watch,
    [ValidateRange(1, 3600)] [int]$PollSeconds = 5,
    # Stops watching after this many scans (0 = until Ctrl+C); used by tests.
    [int]$MaxCycles = 0,
    [string]$GimpExe,
    # Folder containing the bimp3 plug-in folder; default: GIMP's user plug-ins folder.
    [string]$PluginDirectory,
    [string]$ProfileDirectory = (Join-Path $env:LOCALAPPDATA 'bimp3-cli\profile')
)
$ErrorActionPreference = 'Stop'
$extensions = @('bmp', 'gif', 'ico', 'jpg', 'jpeg', 'png', 'tga', 'tif', 'tiff', 'heif', 'heic', 'webp', 'avif', 'exr',
    'xcf', 'psd', 'ora', 'svg', 'jxl', 'jp2', 'j2k', 'pbm', 'pgm', 'ppm', 'pnm', 'pdf', 'dds')

if (-not $GimpExe) {
    $GimpExe = @(
        (Join-Path $env:LOCALAPPDATA 'Programs\GIMP 3\bin\gimp-console-3.exe'),
        (Join-Path $env:ProgramFiles 'GIMP 3\bin\gimp-console-3.exe')
    ) | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
}
if (-not $GimpExe -or -not (Test-Path -LiteralPath $GimpExe)) { throw 'Nie znaleziono GIMP. Podaj -GimpExe.' }
if (-not $PluginDirectory) {
    $versionText = (& $GimpExe --version) -join ' '
    if ($versionText -notmatch '(?<![\d.])(3)\.(\d+)\.(\d+)(?![\d.])') { throw "Nie można potwierdzić GIMP 3: $versionText" }
    $PluginDirectory = Join-Path $env:APPDATA "GIMP\$($Matches[1]).$($Matches[2])\plug-ins"
}
if (-not (Test-Path -LiteralPath (Join-Path $PluginDirectory 'bimp3\bimp3.py'))) {
    throw "Brak wtyczki: $PluginDirectory\bimp3\bimp3.py. Zainstaluj ją przez install.ps1 albo podaj -PluginDirectory."
}
if (-not $Files -and -not $InputFolder) { throw 'Podaj -Files (pliki) albo -InputFolder.' }
if ($Watch -and -not $InputFolder) { throw 'Tryb -Watch wymaga -InputFolder.' }
$Settings = (Resolve-Path -LiteralPath $Settings).Path
New-Item -ItemType Directory -Path $Output -Force | Out-Null
$Output = (Resolve-Path -LiteralPath $Output).Path
New-Item -ItemType Directory -Path $ProfileDirectory -Force | Out-Null
$pluginPath = (Resolve-Path -LiteralPath $PluginDirectory).Path.Replace('\', '/')
$gimprc = '(plug-in-path "${gimp_plug_in_dir}/plug-ins;' + $pluginPath + '")' + "`n(check-updates no)`n"
[IO.File]::WriteAllText((Join-Path $ProfileDirectory 'gimprc'), $gimprc, [Text.UTF8Encoding]::new($false))
$runner = (Join-Path $PSScriptRoot 'bimp3_cli_runner.py').Replace('\', '/')

function Get-Candidates {
    $items = if ($Recurse) { Get-ChildItem -LiteralPath $InputFolder -File -Recurse } else { Get-ChildItem -LiteralPath $InputFolder -File }
    $outputFull = [IO.Path]::GetFullPath($Output).TrimEnd('\') + '\'
    $items | Where-Object {
        $_.Extension.TrimStart('.').ToLowerInvariant() -in $extensions -and
        -not $_.Name.StartsWith('.bimp-') -and
        -not $_.FullName.StartsWith($outputFull, [StringComparison]::OrdinalIgnoreCase)
    }
}

function Invoke-Bimp([string[]]$Paths) {
    $work = Join-Path ([IO.Path]::GetTempPath()) ('bimp3-cli-' + [Guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $work | Out-Null
    try {
        $request = @{
            result    = (Join-Path $work 'result.json')
            arguments = [ordered]@{
                'settings-file'       = $Settings
                'input-files'         = (ConvertTo-Json -InputObject @($Paths) -Compress)
                'output-directory'    = $Output
                'keep-hierarchy'      = [bool]$KeepHierarchy
                'keep-dates'          = [bool]$KeepDates
                'collision-policy'    = $Collision
                'metadata-policy'     = $Metadata
                'output-color'        = $OutputColor
                'embed-color-profile' = -not $NoColorProfile
                'auto-orient'         = -not $NoAutoOrient
                'report-file'         = (Join-Path $work 'report.json')
            }
        }
        $requestPath = Join-Path $work 'request.json'
        [IO.File]::WriteAllText($requestPath, (ConvertTo-Json -InputObject $request -Depth 4), [Text.UTF8Encoding]::new($false))
        $runnerLiteral = ConvertTo-Json -InputObject $runner -Compress
        $requestLiteral = ConvertTo-Json -InputObject $requestPath.Replace('\', '/') -Compress
        $command = "exec(compile(open($runnerLiteral, encoding='utf-8').read(), $runnerLiteral, 'exec'), {'__name__': '__main__', 'BIMP_REQUEST': $requestLiteral})"
        $previous = $env:GIMP3_DIRECTORY
        try {
            $env:GIMP3_DIRECTORY = $ProfileDirectory
            & $GimpExe --new-instance --no-data --no-splash --console-messages --batch-interpreter=python-fu-eval -b $command --quit *> (Join-Path $work 'gimp.log')
        }
        finally { $env:GIMP3_DIRECTORY = $previous }
        if (-not (Test-Path -LiteralPath $request.result)) {
            throw "GIMP nie zwrócił wyniku. Dziennik: $(Get-Content -LiteralPath (Join-Path $work 'gimp.log') -Raw)"
        }
        $result = Get-Content -LiteralPath $request.result -Raw | ConvertFrom-Json
        $report = if (Test-Path -LiteralPath $request.arguments.'report-file') {
            @(Get-Content -LiteralPath $request.arguments.'report-file' -Raw | ConvertFrom-Json)
        } else { @() }
        foreach ($entry in $report) {
            $line = "{0,-8} {1} -> {2}" -f $entry.status, $entry.source, $entry.target
            if ($entry.error) { $line += "  ($($entry.error))" }
            Write-Host $line
        }
        if (-not $result.success) { Write-Warning $result.error }
        return [pscustomobject]@{ Success = [bool]$result.success; Report = $report }
    }
    finally { Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue }
}

if (-not $Watch) {
    $selected = if ($Files) { @($Files | ForEach-Object { (Resolve-Path -LiteralPath $_).Path }) } else { @(Get-Candidates | ForEach-Object FullName) }
    if (-not $selected) { Write-Output 'Brak zdjęć do przetworzenia.'; return }
    $outcome = Invoke-Bimp $selected
    if (-not $outcome.Success) { exit 1 }
    return
}

$statePath = Join-Path $Output '.bimp3-watch.json'
$done = @{}
if (Test-Path -LiteralPath $statePath) {
    (Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json).PSObject.Properties | ForEach-Object { $done[$_.Name] = $_.Value }
}
$seen = @{}
$cycle = 0
Write-Output "Obserwuję $InputFolder (co $PollSeconds s). Zatrzymaj: Ctrl+C."
while ($true) {
    $cycle++
    $ready = @()
    foreach ($file in Get-Candidates) {
        $stamp = "$($file.Length)|$($file.LastWriteTimeUtc.Ticks)"
        if ($done[$file.FullName] -eq $stamp) { continue }
        # Stable across two scans: the file is no longer being copied.
        if ($seen[$file.FullName] -eq $stamp) { $ready += $file } else { $seen[$file.FullName] = $stamp }
    }
    if ($ready) {
        Write-Output ("{0:HH:mm:ss} Nowe zdjęcia: {1}" -f (Get-Date), $ready.Count)
        $outcome = Invoke-Bimp @($ready | ForEach-Object FullName)
        $failed = @($outcome.Report | Where-Object status -eq 'error' | ForEach-Object source)
        foreach ($file in $ready) {
            # Failed files are retried after they change; others are remembered.
            if ($outcome.Report.Count -eq 0 -and -not $outcome.Success) { continue }
            if ($file.FullName -notin $failed) { $done[$file.FullName] = "$($file.Length)|$($file.LastWriteTimeUtc.Ticks)" }
            $seen.Remove($file.FullName)
        }
        $temporary = "$statePath.tmp"
        [IO.File]::WriteAllText($temporary, (ConvertTo-Json -InputObject $done -Compress), [Text.UTF8Encoding]::new($false))
        Move-Item -LiteralPath $temporary -Destination $statePath -Force
    }
    if ($MaxCycles -gt 0 -and $cycle -ge $MaxCycles) { break }
    Start-Sleep -Seconds $PollSeconds
}
