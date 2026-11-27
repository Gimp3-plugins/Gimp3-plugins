[CmdletBinding()]
param([string]$Compiler = 'C:\msys64\ucrt64\bin\gcc.exe')
$ErrorActionPreference = 'Stop'
if (-not (Test-Path -LiteralPath $Compiler)) { throw 'Podaj ścieżkę do GCC x64 przez -Compiler.' }
$previousPath = $env:PATH
try {
    $env:PATH = (Split-Path -Parent $Compiler) + ';' + $env:PATH
    & $Compiler -O3 -Wall -Wextra -Werror -shared -static-libgcc -o (Join-Path $PSScriptRoot 'bimp3\bimp_lut_native.dll') (Join-Path $PSScriptRoot 'bimp3\bimp_lut_native.c')
    if ($LASTEXITCODE -ne 0) { throw 'Nie udało się zbudować akceleratora LUT.' }
    # bimp_lut.py loads the library only when it matches this reviewed checksum.
    $dll = Join-Path $PSScriptRoot 'bimp3imp_lut_native.dll'
    $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $dll).Hash.ToLowerInvariant()
    [IO.File]::WriteAllText("$dll.sha256", "$hash  bimp_lut_native.dll`n", [Text.Encoding]::ASCII)
}
finally { $env:PATH = $previousPath }
