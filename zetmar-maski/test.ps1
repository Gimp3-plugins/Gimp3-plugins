param([string]$GimpBin = "$env:LOCALAPPDATA\Programs\GIMP 3\bin")
$ErrorActionPreference = 'Stop'
& (Join-Path $GimpBin 'python.exe') -m unittest discover -s (Join-Path $PSScriptRoot 'tests') -p 'test_*.py' -v
if ($LASTEXITCODE -ne 0) { throw 'Testy jednostkowe nie przeszly.' }
$work = Join-Path $PSScriptRoot 'work'
$profile = Join-Path $work 'test-profile-headless'
New-Item -ItemType Directory -Path $profile -Force | Out-Null
& (Join-Path $PSScriptRoot 'install.ps1') -ProfileDirectory $profile
$previous = $env:GIMP3_DIRECTORY
$previousRoot = $env:ZETMAR_MASKI_TEST_ROOT
try {
    $env:GIMP3_DIRECTORY = $profile
    $env:ZETMAR_MASKI_TEST_ROOT = $PSScriptRoot
    $testFile = (Join-Path $PSScriptRoot 'tests\integration.py').Replace('\', '/')
    $code = "exec(compile(open(r'$testFile', encoding='utf-8').read(), r'$testFile', 'exec'))"
    $report = Join-Path $work 'integration.json'
    if (Test-Path -LiteralPath $report) { Remove-Item -LiteralPath $report }
    & (Join-Path $GimpBin 'gimp-console-3.2.exe') --new-instance --no-interface --no-data --no-fonts --batch-interpreter=python-fu-eval -b $code --quit
    if ($LASTEXITCODE -ne 0) { throw 'GIMP zakonczyl prace bledem.' }
    if (-not (Test-Path -LiteralPath $report)) { throw 'Brak raportu integracyjnego.' }
    $result = @(Get-Content -LiteralPath $report -Raw | ConvertFrom-Json)
    $failed = @($result | Where-Object { -not $_.pass })
    Write-Output "GIMP integration: $($result.Count - $failed.Count)/$($result.Count) PASS"
    if ($failed.Count) { throw 'Testy integracyjne nie przeszly. Sprawdz work/integration.json.' }
} finally {
    $env:GIMP3_DIRECTORY = $previous
    $env:ZETMAR_MASKI_TEST_ROOT = $previousRoot
}
