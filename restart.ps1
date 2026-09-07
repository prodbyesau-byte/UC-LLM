param([switch]$OpenApp, [switch]$OpenBrowser)
& "$PSScriptRoot/stop.ps1"
& "$PSScriptRoot/start.ps1" -OpenApp:($OpenApp -or $OpenBrowser)
