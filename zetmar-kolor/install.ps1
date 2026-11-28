# Instalacja wtyczki Zetmar Kolor do GIMP-a 3.x (folder plug-ins uzytkownika).
#   powershell -ExecutionPolicy Bypass -File install.ps1            # instalacja / aktualizacja
#   powershell -ExecutionPolicy Bypass -File install.ps1 -Uninstall # usuniecie
param(
    [switch]$Uninstall,
    [string]$GimpVersion = ""
)
$ErrorActionPreference = "Stop"
$root = Join-Path $env:APPDATA "GIMP"
if (-not $GimpVersion) {
    $found = Get-ChildItem $root -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match '^3\.\d+$' } | Sort-Object { [version]$_.Name } -Descending |
        Select-Object -First 1
    if (-not $found) { throw "Nie znaleziono profilu GIMP 3.x w $root - uruchom GIMP-a raz i sprobuj ponownie." }
    $GimpVersion = $found.Name
}
$target = Join-Path $root "$GimpVersion\plug-ins\zetmar-kolor"

if ($Uninstall) {
    if (Test-Path $target) { Remove-Item $target -Recurse -Force; "Usunieto: $target" }
    else { "Wtyczki nie ma: $target" }
    return
}

$src = Join-Path $PSScriptRoot "plug-ins\zetmar-kolor"
New-Item -ItemType Directory -Force $target | Out-Null
Get-ChildItem $src -File | Where-Object { $_.Extension -in ".py", ".json" } |
    Copy-Item -Destination $target -Force
$license = Join-Path $PSScriptRoot "LICENSE"
if (Test-Path $license) { Copy-Item $license -Destination $target -Force }
"Zainstalowano do: $target"

$lutVendor = Join-Path $root "$GimpVersion\plug-ins\lut-cube\vendor"
if (Test-Path (Join-Path $target "vendor")) {
    "numpy: wlasny folder vendor"
} elseif (Test-Path $lutVendor) {
    "numpy: z wtyczki lut-cube ($lutVendor)"
} else {
    "Uwaga: brak numpy (nie ma wtyczki lut-cube) - wtyczka zadziala, ale wolniej (czysty Python)."
}
"Uruchom ponownie GIMP-a. Menu: Filtry > Zetmar > Kolor (krzywe, Cz-B, duotone, toning)..."
