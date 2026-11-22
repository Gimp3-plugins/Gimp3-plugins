[CmdletBinding()]
param(
    [string]$GimpExe = "$env:LOCALAPPDATA\Programs\GIMP 3\bin\gimp-console-3.exe",
    [string]$PluginSearchDirectory = $PSScriptRoot
)
$ErrorActionPreference = 'Stop'
$pythonExe = Join-Path (Split-Path -Parent $GimpExe) 'python.exe'
& $pythonExe -m unittest discover -s (Join-Path $PSScriptRoot 'tests') -p 'test_*.py' -v
if ($LASTEXITCODE -ne 0) { throw 'Testy modelu nie przeszły.' }
$previousProfile = $env:GIMP3_DIRECTORY
try {
    $env:GIMP3_DIRECTORY = Join-Path $PSScriptRoot 'tests\profile'
    New-Item -ItemType Directory -Path $env:GIMP3_DIRECTORY -Force | Out-Null
    # This is an isolated test profile, never the user's normal gimprc.
    $pluginPath = $PluginSearchDirectory.Replace('\', '/')
    $config = '(plug-in-path "${gimp_plug_in_dir}/plug-ins;' + $pluginPath + '")' + "`n(check-updates no)`n"
    [IO.File]::WriteAllText((Join-Path $env:GIMP3_DIRECTORY 'gimprc'), $config, [Text.UTF8Encoding]::new($false))
    [IO.File]::WriteAllText((Join-Path $env:GIMP3_DIRECTORY 'theme.css'), '', [Text.UTF8Encoding]::new($false))
    $scriptPath = (Join-Path $PSScriptRoot 'tests\integration.py').Replace('\', '/')
    $literal = ConvertTo-Json -InputObject $scriptPath -Compress
    $command = "exec(compile(open($literal, encoding='utf-8').read(), $literal, 'exec'), {'__file__':$literal})"
    $resultPath = Join-Path $PSScriptRoot 'tests\integration-result.json'
    $startTime = [DateTime]::UtcNow
    & $GimpExe --new-instance --no-data --no-splash --console-messages --batch-interpreter=python-fu-eval -b $command --quit
    if ($LASTEXITCODE -ne 0) { throw 'Testy w GIMP nie przeszły.' }
    if (-not (Test-Path -LiteralPath $resultPath) -or (Get-Item -LiteralPath $resultPath).LastWriteTimeUtc -lt $startTime) { throw 'Brak świeżego raportu testów.' }
    $result = Get-Content -LiteralPath $resultPath -Raw | ConvertFrom-Json
    if ($result.failed -ne 0) { throw "Błędy: $($result.failed)" }
    Write-Output "GIMP $($result.gimp): $($result.passed) testów integracyjnych OK."
}
finally {
    $env:GIMP3_DIRECTORY = $previousProfile
}
