$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetFullPath($PSScriptRoot)
$dist = Join-Path $root 'dist'
New-Item -ItemType Directory -Path $dist -Force | Out-Null
$archive = Join-Path $dist 'zetmar-maski-1.0.0-windows.zip'
$archivePath = [IO.Path]::GetFullPath($archive)
if (-not $archivePath.StartsWith($dist.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Niepoprawny katalog archiwum.' }
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem
$stream = [IO.File]::Open($archivePath, [IO.FileMode]::Create)
$zip = New-Object IO.Compression.ZipArchive($stream, [IO.Compression.ZipArchiveMode]::Create)
try {
    $files = @(Get-ChildItem -LiteralPath (Join-Path $root 'plug-ins\zetmar-maski') -File -Filter '*.py')
    foreach ($name in @('README.md', 'README.en.md', 'LICENSE', 'VALIDATION.md', 'install.ps1', 'test.ps1', 'build.ps1', '.gitignore')) {
        $files += Get-Item -LiteralPath (Join-Path $root $name)
    }
    $files += Get-ChildItem -LiteralPath (Join-Path $root 'tests') -File
    $files += Get-ChildItem -LiteralPath (Join-Path $root 'docs') -File -Recurse
    foreach ($file in $files) {
        $relative = $file.FullName.Substring($root.Length + 1).Replace('\', '/')
        [IO.Compression.ZipFileExtensions]::CreateEntryFromFile($zip, $file.FullName, $relative) | Out-Null
    }
} finally { $zip.Dispose(); $stream.Dispose() }
$screenshot = Join-Path $dist 'zetmar-maski-1.0.0-screenshot.png'
Copy-Item -LiteralPath (Join-Path $root 'docs\screenshot.png') -Destination $screenshot -Force
$checksums = foreach ($file in @($archive, $screenshot)) {
    $hash = (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant()
    "$hash  $(Split-Path $file -Leaf)"
}
$checksums | Set-Content -LiteralPath (Join-Path $dist 'SHA256SUMS.txt') -Encoding ascii
Write-Output $archive
