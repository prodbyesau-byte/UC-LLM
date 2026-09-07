$ErrorActionPreference='Stop'
$app=Join-Path $PSScriptRoot 'desktop\Local Agent.exe'
if (!(Test-Path -LiteralPath $app)) { & "$PSScriptRoot/desktop/build.ps1" }
Start-Process -FilePath $app -WorkingDirectory $PSScriptRoot -WindowStyle Normal
