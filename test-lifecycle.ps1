. "$PSScriptRoot/services.ps1"
$result=@{}
& "$Root/stop.ps1"
$ports=@($Config.LLM_PORT,$Config.SEARXNG_PORT,$Config.SILLYTAVERN_PORT)
if (@(Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object LocalPort -in $ports).Count) { throw 'Project listeners remain after stop.' }
$listener=[Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback,$Config.LLM_PORT)
$listener.Start()
try {
    $detected=$false
    try { & "$Root/start.ps1" } catch { $detected=$_.Exception.Message -like '*occupied by another process*' }
    if (!$detected -or !$listener.Server.IsBound) { throw 'Port conflict handling failed.' }
    $result['8_port_conflict']=@{pass=$true;evidence='Startup refused occupied port; unrelated test listener remained alive.'}
} finally { $listener.Stop() }
& "$Root/start.ps1"
foreach($s in Get-ServiceDefinitions) { if (!(Test-Endpoint $s.Url)) { throw "Restart health failed: $($s.Name)" } }
$before=(Read-State).Id -join ','
& "$Root/start.ps1"
if (((Read-State).Id -join ',') -ne $before) { throw 'Repeated start created duplicate processes.' }
$result['7_restart']=@{pass=$true;evidence='All three services stopped, ports released, restarted, and repeated start preserved process IDs.'}
$memory=Get-CimInstance Win32_PerfFormattedData_PerfOS_Memory
$gpu=& nvidia-smi --query-gpu=name,memory.used,memory.free --format=csv,noheader
$result['9_memory']=@{pass=($memory.AvailableMBytes -ge 1500);available_ram_mb=$memory.AvailableMBytes;commit_percent=$memory.PercentCommittedBytesInUse;gpu=$gpu;llm_working_set_bytes=(Get-Process llama-server).WorkingSet64}
$result | ConvertTo-Json -Depth 8 | Set-Content "$Root/logs/lifecycle-tests.json"
if (!$result['9_memory'].pass) { throw 'Insufficient free physical memory.' }
Write-Host 'Restart, duplicate prevention, port conflict, and memory tests PASS.'
