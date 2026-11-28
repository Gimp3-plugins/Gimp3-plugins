$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$env:GIMP3_DIRECTORY = Join-Path $root 'work\test-profile'
$env:ZETMAR_MASKI_TEST_ROOT = $root
& (Join-Path $root 'install.ps1') -ProfileDirectory $env:GIMP3_DIRECTORY
$testFile = (Join-Path $PSScriptRoot 'ui_smoke.py').Replace('\', '/')
$code = "exec(compile(open(r'$testFile', encoding='utf-8').read(), r'$testFile', 'exec'))"
& "$env:LOCALAPPDATA\Programs\GIMP 3\bin\gimp-console-3.2.exe" --new-instance --no-interface --no-data --no-fonts --batch-interpreter=python-fu-eval -b $code --quit
