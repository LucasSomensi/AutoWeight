param([switch]$Depuracao)
$ErrorActionPreference = 'Stop'
$cargo = Join-Path $env:USERPROFILE '.cargo\bin\cargo.exe'
if (-not (Test-Path -LiteralPath $cargo)) { $cargo = 'cargo' }
$manifest = Join-Path $PSScriptRoot 'rust\Cargo.toml'
$buildArgs = @('build', '--locked', '--manifest-path', $manifest, '--bins')
$buildProfile = 'release'
if ($Depuracao) { $buildProfile = 'debug' } else { $buildArgs += '--release' }
& $cargo @buildArgs
if ($LASTEXITCODE -ne 0) { throw 'Falha ao compilar o AutoWeight Rust.' }
$destination = Join-Path $PSScriptRoot 'bin'
New-Item -ItemType Directory -Path $destination -Force | Out-Null
foreach ($name in @('autoweight.exe', 'autoweight-cli.exe')) {
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot "rust\target\$buildProfile\$name") -Destination (Join-Path $destination $name) -Force
}
Write-Output "Executáveis oficiais disponíveis em $destination"
