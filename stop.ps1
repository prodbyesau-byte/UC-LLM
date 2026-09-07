. "$PSScriptRoot/services.ps1"
$remaining = @()
foreach ($record in @(Read-State)) {
    $p = Get-OwnedProcess $record
    if ($p) {
        try { Stop-Process -Id $p.Id; if (!$p.WaitForExit(10000)) { throw 'Process did not exit' }; Write-Host "Stopped $($record.Name)" }
        catch { $remaining += $record; Write-Warning "Could not stop $($record.Name): $_" }
    }
}
ConvertTo-Json -InputObject @($remaining) | Set-Content -LiteralPath $StateFile
