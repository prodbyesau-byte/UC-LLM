. "$PSScriptRoot/services.ps1"
Write-Host 'LOCAL AI AGENT STATUS'
foreach ($s in Get-ServiceDefinitions) {
    $label = if (Test-Endpoint $s.Url) {'OK'} else {'DOWN'}
    Write-Host "[$label] $($s.Name) $($s.Url)"
}
try {
    $models=Invoke-RestMethod "http://127.0.0.1:$($Config.LLM_PORT)/v1/models" -TimeoutSec 5
    Write-Host "[OK] Model: $($models.data.id -join ', ')"
} catch { Write-Host '[DOWN] Model API' }
try {
    $r=Invoke-RestMethod "http://127.0.0.1:$($Config.SEARXNG_PORT)/search?q=Python+programming&format=json" -TimeoutSec 25
    if (!$r.results.Count) { throw 'No results' }
    Write-Host "[OK] Live search: $($r.results.Count) results"
} catch { Write-Host '[DEGRADED] Live search unavailable; offline chat can still work.' }
& nvidia-smi --query-gpu=name,memory.used,memory.total --format=csv,noheader
Write-Host '[OPTIONAL] Tavily not configured; no key required.'
