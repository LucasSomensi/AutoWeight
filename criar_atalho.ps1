$ErrorActionPreference = 'Stop'
$executable = Join-Path $PSScriptRoot 'bin\autoweight.exe'
if (-not (Test-Path -LiteralPath $executable)) { throw 'Compile primeiro: powershell -ExecutionPolicy Bypass -File .\compilar_rust.ps1' }
$shortcutPath = Join-Path $PSScriptRoot 'AutoWeight.lnk'
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $executable
$shortcut.Arguments = '--diretorio "' + $PSScriptRoot + '"'
$shortcut.WorkingDirectory = $PSScriptRoot
$shortcut.IconLocation = (Join-Path $PSScriptRoot 'assets\robot.ico') + ',0'
$shortcut.Description = 'AutoWeight Rust - Monitoramento de pesagem'
$shortcut.Save()
Write-Output 'Atalho AutoWeight.lnk criado.'
