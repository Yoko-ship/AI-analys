param([Parameter(Mandatory=$true)][string]$ConfigPath)
$ErrorActionPreference = 'Stop'
$projectDirectory = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$privateConfig = (Resolve-Path -LiteralPath $ConfigPath).Path
$pythonPath = Join-Path $projectDirectory '.venv\Scripts\pythonw.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) { throw 'Install the project Python environment first.' }
$startupDirectory = [Environment]::GetFolderPath('Startup')
$shortcutPath = Join-Path $startupDirectory 'UZStock Video Worker.lnk'
$shellLink = New-Object -ComObject WScript.Shell
$shortcut = $shellLink.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $pythonPath
$shortcut.Arguments = '-m video_worker.worker --config "' + $privateConfig + '"'
$shortcut.WorkingDirectory = $projectDirectory
$shortcut.WindowStyle = 7
$shortcut.Save()
Start-Process -FilePath $pythonPath -ArgumentList $shortcut.Arguments -WorkingDirectory $projectDirectory -WindowStyle Hidden
Write-Output 'Video worker started and will start at Windows sign-in.'
