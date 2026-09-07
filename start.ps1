param([switch]$OpenApp, [switch]$OpenBrowser)
. "$PSScriptRoot/services.ps1"
$state = @(Read-State)
$definitions = @(Get-ServiceDefinitions)
# Validate all ports before starting any service. Never stop an unrelated listener.
foreach ($s in $definitions) {
    $record = $state | Where-Object Name -eq $s.Name | Select-Object -First 1
    $owned = if ($record) { Get-OwnedProcess $record } else { $null }
    $listeners = @(Get-NetTCPConnection -State Listen -LocalPort $s.Port -ErrorAction SilentlyContinue)
    if ($listeners.Count -and (!$owned -or @($listeners | Where-Object { !(Test-OwnedListener $record $_.OwningProcess) }).Count)) { throw "Port $($s.Port) is occupied by another process. No process was stopped. Choose a free port in config.json and run configure.py/setup_frontend.py, or close that service yourself." }
}
foreach ($s in $definitions) {
    $record = $state | Where-Object Name -eq $s.Name | Select-Object -First 1
    if (!$record -or !(Get-OwnedProcess $record)) {
        $p = Start-Process -FilePath $s.Exe -ArgumentList $s.Args -WorkingDirectory $s.Cwd -WindowStyle Hidden -RedirectStandardOutput "$Root/logs/$($s.Name).out.log" -RedirectStandardError "$Root/logs/$($s.Name).err.log" -PassThru
        $record = [pscustomobject]@{Name=$s.Name;Id=$p.Id;StartTicks=$p.StartTime.ToUniversalTime().Ticks.ToString();Executable=(Get-Item -LiteralPath $s.Exe).FullName}
        $state = @($state | Where-Object Name -ne $s.Name) + @($record)
        ConvertTo-Json -InputObject @($state) | Set-Content -LiteralPath $StateFile
    }
    $deadline = (Get-Date).AddSeconds(180)
    while (!(Test-Endpoint $s.Url)) {
        if (!(Get-OwnedProcess $record)) { throw "$($s.Name) exited. Read logs/$($s.Name).err.log." }
        if ((Get-Date) -gt $deadline) { throw "$($s.Name) did not become ready. Read logs/$($s.Name).err.log." }
        Start-Sleep -Seconds 2
    }
    Write-Host "[OK] $($s.Name)"
}
try {
    $search=Invoke-RestMethod "http://127.0.0.1:$($Config.SEARXNG_PORT)/search?q=Python+programming&format=json" -TimeoutSec 25
    if (!$search.results.Count) { throw 'No search results returned' }
    Write-Host '[OK] Live web search'
} catch { Write-Warning 'Search is temporarily unavailable. Local conversation is still available.' }
Write-Host "Ready: http://127.0.0.1:$($Config.SILLYTAVERN_PORT)"
if ($OpenApp -or $OpenBrowser) { & "$Root/open-app.ps1" }

