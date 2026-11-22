[CmdletBinding()]
param([string]$Compiler = 'C:\msys64\ucrt64\bin\gcc.exe')
$ErrorActionPreference = 'Stop'
if (-not (Test-Path -LiteralPath $Compiler)) { throw 'Podaj ścieżkę do GCC x64 przez -Compiler.' }
$previousPath = $env:PATH
try {
    $env:PATH = (Split-Path -Parent $Compiler) + ';' + $env:PATH
    & $Compiler -O3 -Wall -Wextra -Werror -shared -static-libgcc -o (Join-Path $PSScriptRoot 'bimp3\bimp_lut_native.dll') (Join-Path $PSScriptRoot 'bimp3\bimp_lut_native.c')
    if ($LASTEXITCODE -ne 0) { throw 'Nie udało się zbudować akceleratora LUT.' }
}
finally { $env:PATH = $previousPath }
