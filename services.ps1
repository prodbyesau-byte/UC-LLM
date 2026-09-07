$ErrorActionPreference = 'Stop'
$Root = $PSScriptRoot
$Config = Get-Content -LiteralPath "$Root/config.json" -Raw | ConvertFrom-Json
$StateFile = "$Root/runtime/services.json"
function Read-State {
    if (Test-Path -LiteralPath $StateFile) {
        $parsed=Get-Content -LiteralPath $StateFile -Raw | ConvertFrom-Json
        if ($null -eq $parsed) { return @() }
        return @($parsed | Where-Object { $null -ne $_ })
    }
    return @()
}
function Get-OwnedProcess($Record) {
    $p = Get-Process -Id $Record.Id -ErrorAction SilentlyContinue
    if ($p -and $p.StartTime.ToUniversalTime().Ticks.ToString() -eq $Record.StartTicks -and $p.Path -eq $Record.Executable) { return $p }
    return $null
}
function Test-Endpoint($Url) {
    try {
        $request=[Net.HttpWebRequest]::Create($Url)
        $request.Timeout=3000
        $response=$request.GetResponse()
        try { return ([int]$response.StatusCode -eq 200) } finally { $response.Dispose() }
    } catch { return $false }
}
function Test-OwnedListener($Record, $ProcessId) {
    $owner = Get-OwnedProcess $Record
    if (!$owner) { return $false }
    $current = $ProcessId
    for ($i=0; $i -lt 5; $i++) {
        if ($current -eq $owner.Id) { return $true }
        $child = Get-CimInstance Win32_Process -Filter "ProcessId=$current" -ErrorAction SilentlyContinue
        if (!$child -or $child.CreationDate.ToUniversalTime() -lt $owner.StartTime.ToUniversalTime()) { return $false }
        $current = $child.ParentProcessId
    }
    return $false
}
function Get-ServiceDefinitions {
    @(
        @{Name='llm';Port=$Config.LLM_PORT;Url="http://127.0.0.1:$($Config.LLM_PORT)/health";Exe="$Root/apps/llama/llama-server.exe";Cwd=$Root;Args=@('-m',"`"$Root/$($Config.MODEL_PATH)`"",'--alias',$Config.MODEL_NAME,'--host','127.0.0.1','--port',$Config.LLM_PORT,'-ngl','99','-c',$Config.CONTEXT_SIZE,'-t',$Config.CPU_THREADS,'-b','256','-ub','128','-fa','on','-ctk','q8_0','-ctv','q8_0','--parallel','1','--cache-ram','0','--reasoning','off','--load-mode','none','--no-host','--cors-origins','http://127.0.0.1:8000','--no-cors-credentials')},
        @{Name='searxng';Port=$Config.SEARXNG_PORT;Url="http://127.0.0.1:$($Config.SEARXNG_PORT)/";Exe="$Root/runtime/python/Scripts/python.exe";Cwd=$Root;Args=@("`"$Root/searx_server.py`"")},
        @{Name='files';Port=$Config.FILES_PORT;Url="http://127.0.0.1:$($Config.FILES_PORT)/health";Exe="$Root/runtime/python/Scripts/python.exe";Cwd=$Root;Args=@("`"$Root/file_registry_server.py`"")},
        @{Name='sillytavern';Port=$Config.SILLYTAVERN_PORT;Url="http://127.0.0.1:$($Config.SILLYTAVERN_PORT)/";Exe=(Get-Command node.exe).Source;Cwd="$Root/apps/SillyTavern";Args=@('server.js')}
    )
}
