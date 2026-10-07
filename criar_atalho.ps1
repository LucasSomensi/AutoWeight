$ErrorActionPreference = 'Stop'
$pythonPath = (& python -c "import sys; print(sys.executable)").Trim()
if ($LASTEXITCODE -ne 0) { throw 'Não foi possível localizar o Python.' }
$pythonwPath = Join-Path (Split-Path $pythonPath) 'pythonw.exe'
if (-not (Test-Path -LiteralPath $pythonwPath)) { throw 'pythonw.exe não encontrado.' }
$shortcutPath = Join-Path $PSScriptRoot 'AutoWeight.lnk'
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $pythonwPath
$shortcut.Arguments = '"' + (Join-Path $PSScriptRoot 'AutoWeight.pyw') + '"'
$shortcut.WorkingDirectory = $PSScriptRoot
$shortcut.IconLocation = (Join-Path $PSScriptRoot 'assets\robot.ico') + ',0'
$shortcut.Description = 'AutoWeight - Monitoramento de pesagem'
$shortcut.Save()
Write-Output 'Atalho AutoWeight.lnk criado.'
