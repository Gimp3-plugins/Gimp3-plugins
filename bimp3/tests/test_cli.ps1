[CmdletBinding()]
param([string]$GimpExe = "$env:LOCALAPPDATA\Programs\GIMP 3\bin\gimp-console-3.exe")
# Uses the plug-in from this source tree and an isolated profile in tests\output.
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$work = Join-Path $PSScriptRoot ('output\cli-' + [Guid]::NewGuid().ToString('N'))
$inbox = Join-Path $work 'inbox'
$out = Join-Path $work 'out'
New-Item -ItemType Directory -Path $inbox -Force | Out-Null
$fixture = Join-Path $PSScriptRoot 'output\źródło.png'
if (-not (Test-Path -LiteralPath $fixture)) { throw 'Najpierw uruchom .\test.ps1 (tworzy obraz testowy).' }
$settings = Join-Path $work 'web.json'
$preset = '{"bimp3": 1, "steps": [{"type": "changeformat", "settings": {"format": 3, "max_kb": 0, "arguments": {}}}]}'
[IO.File]::WriteAllText($settings, $preset, [Text.UTF8Encoding]::new($false))
$common = @{ GimpExe = $GimpExe; Settings = $settings; Output = $out; PluginDirectory = $root; ProfileDirectory = (Join-Path $PSScriptRoot 'output\cli-profile') }

Copy-Item -LiteralPath $fixture -Destination (Join-Path $inbox 'a.png')
& (Join-Path $root 'bimp3-cli.ps1') @common -Files (Join-Path $inbox 'a.png') | Write-Output
if (-not (Test-Path -LiteralPath (Join-Path $out 'a.jpg'))) { throw 'CLI nie zapisało a.jpg.' }

# Watch: b.png is stable after two scans; a.png is skipped as existing output (collision skip).
Copy-Item -LiteralPath $fixture -Destination (Join-Path $inbox 'b.png')
& (Join-Path $root 'bimp3-cli.ps1') @common -InputFolder $inbox -Watch -PollSeconds 1 -MaxCycles 3 | Write-Output
if (-not (Test-Path -LiteralPath (Join-Path $out 'b.jpg'))) { throw 'Tryb obserwacji nie przetworzył b.png.' }
$state = Get-Content -LiteralPath (Join-Path $out '.bimp3-watch.json') -Raw | ConvertFrom-Json
if (-not $state.PSObject.Properties.Name.Where({ $_ -like '*b.png' })) { throw 'Brak b.png w stanie obserwacji.' }
Remove-Item -LiteralPath $work -Recurse -Force
Write-Output 'CLI_TEST_OK: pojedynczy przebieg i obserwowany folder.'
